import json
from pathlib import Path
from threading import RLock
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from .engine import run_engine
from .models import Contract, Dataset, Signal
from .store import ROOT, Store

FIXTURES = ROOT / "fixtures"


class ReplayRequest(Contract):
    action: Literal["start", "advance", "reset"]
    scenario: str = "signature"
    # Reviewed structured input enters through the phase-1 replay boundary only.
    dataset: Dataset | None = None


class CompareRequest(Contract):
    disable_families: list[Literal["image"]] = Field(default_factory=list, max_length=1)
    add_duplicates: int = Field(default=0, ge=0, le=10)


def load_fixture(name):
    allowed = {p.stem: p for p in FIXTURES.glob("*.json") if not p.stem.startswith("text_")}
    if name not in allowed:
        raise HTTPException(404, "Unknown bundled scenario")
    return Dataset.model_validate_json(allowed[name].read_text(encoding="utf-8"))


def create_app(db_path=None, perception_settings=None, perception_client=None):
    app = FastAPI(title="Converge — Phase 2A", version="2.0", docs_url=None, redoc_url=None)
    store = Store(db_path)
    app.state.store = store
    lock = RLock()
    from .observations import Observations, register_observations
    live_store = Store(store.path.with_name(store.path.stem + '-text.sqlite3'))
    observations = Observations(live_store, perception_settings, perception_client)
    app.state.observations = observations
    register_observations(app, observations)

    def response():
        state = store.state()
        if not state:
            return {"dataset_id": None, "version": "1.0", "incidents": [], "step": 0, "total_steps": 0,
                    "clock": None, "signals": [], "roads": [], "excluded": [], "mode": "manual_structured"}
        dataset = Dataset.model_validate_json(state["fixture_json"])
        times = sorted({s.available_at for s in dataset.signals})
        visible = [store.get_signal(s.signal_id) for s in dataset.signals]
        return {"dataset_id": dataset.dataset_id, "version": "1.0", "title": dataset.title,
                "incidents": store.incidents(), "step": state["step"], "total_steps": len(times),
                "clock": state["clock"], "signals": [s for s in visible if s], "roads": dataset.roads,
                "excluded": json.loads(state["excluded_json"]), "mode": dataset.mode}

    @app.get("/api/v1/health")
    def health():
        with store.connection() as db:
            ready = db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        return {"status": "ok", "version": "1.0", "sqlite_foreign_keys": ready,
                "mode": "manual_structured", "openai_enabled": False, "network_dependencies": [],
                "text_perception": {"configured": bool(observations.perception.settings.api_key),
                    "primary": observations.perception.settings.primary, "fallback": observations.perception.settings.fallback,
                    "fallback_enabled": observations.perception.settings.fallback_enabled,
                    "reasoning_effort": observations.perception.settings.reasoning}}

    @app.get("/api/v1/incidents")
    def incidents():
        with lock:
            return response()

    @app.get("/api/v1/incidents/{incident_id}")
    def detail(incident_id: str):
        with lock:
            item = next((i for i in store.incidents(active_only=False) if i.incident_id == incident_id), None)
            if item is None:
                raise HTTPException(404, "Incident not found")
            return item

    @app.get("/api/v1/signals/{signal_id}")
    def signal(signal_id: str):
        with lock:
            item = store.get_signal(signal_id) or live_store.get_signal(signal_id)
            if item is None:
                raise HTTPException(404, "Signal not yet available or not found")
            return item

    @app.post("/api/v1/demo/replay")
    def replay(request: ReplayRequest):
        with lock:
            if request.dataset is not None and request.action != "reset":
                raise HTTPException(422, "A structured dataset can only be supplied on reset")
            if request.action == "reset" or not store.state():
                dataset = request.dataset or load_fixture(request.scenario)
                if not dataset.signals:
                    raise HTTPException(422, "Demo requires at least one observation")
                if any(s.provenance.content_origin != "synthetic" or s.provenance.placement_origin != "simulated"
                       or s.provenance.time_origin != "simulated" for s in dataset.signals):
                    raise HTTPException(422, "Phase 1 accepts explicitly synthetic demo observations only")
                if len({s.idempotency_key for s in dataset.signals}) != len(dataset.signals):
                    raise HTTPException(422, "Duplicate idempotency keys in structured dataset")
                store.reset(dataset)
                if request.action == "reset":
                    return response()
            state = store.state()
            dataset = Dataset.model_validate_json(state["fixture_json"])
            times = sorted({s.available_at for s in dataset.signals})
            if request.action == "start" and state["step"] > 0 or state["step"] >= len(times):
                return response()
            step = state["step"] + 1
            clock = times[step - 1]
            try:
                result, excluded, available = run_engine(dataset, clock)
                store.commit_step(dataset, clock, step, result, excluded, available)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            return response()

    @app.post("/api/v1/demo/compare")
    def compare(request: CompareRequest):
        with lock:
            state = store.state()
            if not state or not state["clock"]:
                raise HTTPException(409, "Start the replay before comparing evidence")
            dataset = Dataset.model_validate_json(state["fixture_json"])
            from datetime import datetime
            clock = datetime.fromisoformat(state["clock"])
            baseline, _, _ = run_engine(dataset, clock)
            originals = sorted([s for s in dataset.signals if s.available_at <= clock and s.source_family == "text"],
                               key=lambda s: s.signal_id)
            if request.add_duplicates and originals:
                original = originals[0]
                for n in range(request.add_duplicates):
                    payload = original.model_dump(mode="json")
                    sid = f"zz-compare-copy-{n}"
                    payload.update(signal_id=sid, source_record_id=sid, idempotency_key=sid, capture_group_id=sid)
                    for e in payload["evidence"]:
                        e.update(signal_id=sid, evidence_id=sid + "-" + e["feature"])
                    dataset.signals.append(Signal.model_validate(payload))
            try:
                changed, excluded, signals = run_engine(dataset, clock, request.disable_families)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            return {"dataset_id": dataset.dataset_id, "version": "1.0", "clock": clock, "sandbox": True,
                    "disable_families": request.disable_families, "added_duplicates": request.add_duplicates,
                    "baseline": baseline, "incidents": changed, "signals": signals, "excluded": excluded}

    dist = ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
