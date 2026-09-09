"""Durable local text jobs and revisions, using the existing Signal/Store/engine."""
import json
import re
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import BackgroundTasks, HTTPException, Request, UploadFile

from .engine import run_engine
from .models import Dataset, Provenance, RoadContext, Signal
from .perception import Perception, ProcessingError, digest, now
from .text_contract import (Correction, NewObservation, Reanalysis, TextExtraction,
                            PROMPT_VERSION, SCHEMA_VERSION, TASK_VERSION, evidence_from)
from .image_observations import ImageObservations, signal_for_client


async def _read_multipart_fallback(request: Request):
    """Small bounded parser used only when python-multipart is unavailable."""
    content_type = request.headers.get("content-type", "")
    match = re.search(r"boundary=(?:\"([^\"]+)\"|([^;]+))", content_type)
    if not match:
        raise HTTPException(422, "Multipart image upload is required")
    boundary = (match.group(1) or match.group(2)).encode()
    chunks, total, limit = [], 0, 5 * 1024 * 1024 + 256 * 1024
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, "Image upload is too large")
        chunks.append(chunk)
    body = b"".join(chunks)
    delimiter = b"--" + boundary
    fields = {}
    for part in body.split(delimiter)[1:]:
        part = part.strip(b"\r\n-")
        if not part:
            continue
        header_blob, separator, value = part.partition(b"\r\n\r\n")
        if not separator:
            raise HTTPException(422, "Malformed multipart image upload")
        headers = header_blob.decode("latin-1").split("\r\n")
        disposition = next((h for h in headers if h.lower().startswith("content-disposition:")), "")
        name = re.search(r'name="([^"]+)"', disposition)
        if not name or name.group(1) in fields:
            raise HTTPException(422, "metadata JSON and image file are required")
        fields[name.group(1)] = value
    if set(fields) != {"metadata", "image"}:
        raise HTTPException(422, "metadata JSON and image file are required")
    return fields["metadata"], fields["image"]


class Observations:
    def __init__(self, store, settings=None, client=None):
        self.store, self.lock = store, store.lock
        self.perception = Perception(store, settings, client)
        if store.backend == "sqlite":
            self._initialize_sqlite()
        if not store.state():
            store.reset(Dataset(dataset_id="operator-text", title="Operator text observations", roads=[], rainfall=[], signals=[]))
        self.images = ImageObservations(self)

    def _initialize_sqlite(self):
        with self.store.connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS text_jobs(signal_id TEXT PRIMARY KEY, original_json TEXT NOT NULL,
                status TEXT NOT NULL, error_code TEXT, revision INTEGER NOT NULL DEFAULT 0,
                linked_image_signal_id TEXT);
            CREATE TABLE IF NOT EXISTS extraction_revisions(signal_id TEXT NOT NULL, revision INTEGER NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(signal_id,revision));
            """)
            # Phase 2A databases predate the paired image column.
            columns = {r[1] for r in db.execute("PRAGMA table_info(text_jobs)")}
            if "linked_image_signal_id" not in columns:
                db.execute("ALTER TABLE text_jobs ADD COLUMN linked_image_signal_id TEXT")
            db.execute("UPDATE text_jobs SET status='needs_review',error_code='interrupted_restart' WHERE status IN ('pending','analyzing')")

    def dataset(self):
        return Dataset.model_validate_json(self.store.state()["fixture_json"])

    def submit(self, request):
        with self.lock:
            dataset = self.dataset()
            with self.store.connection() as db:
                return self._submit_text_locked(request, db, dataset)

    def _submit_text_locked(self, request, db, dataset, link_image=None):
        """Insert a text signal inside a caller-owned transaction and lock."""
        for row in db.execute("SELECT signal_id,original_json FROM text_jobs"):
            previous = NewObservation.model_validate_json(row["original_json"])
            if previous.idempotency_key == request.idempotency_key:
                if previous != request:
                    raise HTTPException(409, "Idempotency key has different input")
                return row["signal_id"], False
        if len(dataset.signals) >= 500:
            raise HTTPException(409, "Local observation capacity (500) reached")
        sid, timestamp = "text-" + uuid4().hex, datetime.now(timezone.utc)
        simulated = request.content_origin == "synthetic"
        provenance = Provenance(content_origin=request.content_origin,
            placement_origin="simulated" if simulated else "original",
            time_origin="simulated" if simulated else "original", source_ref=sid,
            author_category="operator report", license="local operator supplied",
            annotation_method="ai_text", reviewer=request.operator)
        signal = Signal(signal_id=sid, dataset_id=dataset.dataset_id,
            idempotency_key="text:" + request.idempotency_key,
            source_record_id=sid, source_family="text", capture_group_id=request.capture_group_id,
            copy_lineage=request.copy_lineage, independence=request.independence, text=request.text,
            lat=request.lat, lon=request.lon, location_accuracy_m=request.location_accuracy_m,
            location_method="submission coordinates", road_context_id=request.road_context_id,
            observed_at=request.observed_at, received_at=timestamp, available_at=timestamp,
            provenance=provenance, evidence=[])
        from .context import attach_operator_road
        sourced = attach_operator_road(dataset, signal)
        if signal.road_context_id is not None and not sourced and not any(r.road_context_id == request.road_context_id for r in dataset.roads):
            dataset.roads.append(RoadContext(road_context_id=request.road_context_id, name=request.road_context_id,
                road_class=None, coordinates=[(request.lon, request.lat), (request.lon, request.lat)],
                provenance=provenance.model_copy(update={"annotation_method": "manual_structured"})))
        dataset.signals.append(signal)
        db.execute("INSERT INTO text_jobs(signal_id,original_json,status,error_code,revision,linked_image_signal_id) VALUES(?,?, 'pending',NULL,0,?)",
                   (sid, request.model_dump_json(), link_image))
        db.execute("UPDATE datasets SET fixture_json=?", (dataset.model_dump_json(),))
        db.execute("INSERT INTO signals VALUES(?,?,?,?,?,?,?)", (sid, dataset.dataset_id, "text", sid,
            signal.idempotency_key, request.observed_at.isoformat(), signal.model_dump_json()))
        return sid, True

    def get(self, sid):
        image = self.images.get(sid)
        if image is not None:
            return image
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM text_jobs WHERE signal_id=?", (sid,)).fetchone()
            if not row:
                raise HTTPException(404, "Observation not found")
            revisions = [json.loads(r[0]) for r in db.execute(
                "SELECT payload FROM extraction_revisions WHERE signal_id=? ORDER BY revision", (sid,))]
        incidents = [i for i in self.store.incidents() if sid in i.signal_ids]
        state = self.store.state()
        exclusions = [e for e in json.loads(state["excluded_json"]) if e["signal_id"] == sid]
        return {"signal_id": sid, "kind": "text", "original": json.loads(row["original_json"]), "status": row["status"],
            "error_code": row["error_code"], "revision": row["revision"], "revisions": revisions,
            "latest": revisions[-1] if revisions else None, "incidents": incidents, "excluded": exclusions,
            "linked_image_signal_id": row["linked_image_signal_id"],
            "disposition": "candidate" if any(i.status == "candidate" for i in incidents) else
                "watch" if incidents else "not_admitted"}

    def all(self):
        with self.lock:
            with self.store.connection() as db:
                ids = [r[0] for r in db.execute("SELECT signal_id FROM text_jobs UNION ALL SELECT signal_id FROM image_jobs")]
            return [self.get(sid) for sid in ids]

    def process(self, sid, deeper=False):
        image = self.images.get(sid)
        if image is not None:
            return self.images.process(sid, deeper)
        with self.lock:
            job = self.get(sid)
            with self.store.connection() as db:
                db.execute("UPDATE text_jobs SET status='analyzing',error_code=NULL WHERE signal_id=?", (sid,))
        try:
            result = self.perception.extract(job["original"]["text"], deeper)
            with self.lock:
                self.accept(sid, result)
        except ProcessingError as error:
            with self.store.connection() as db:
                db.execute("UPDATE text_jobs SET status=?,error_code=? WHERE signal_id=?", (error.state, error.code, sid))
        except Exception:
            # Never log provider exception bodies or report content. Keep a recoverable local job.
            with self.store.connection() as db:
                db.execute("UPDATE text_jobs SET status='failed',error_code='local_processing_error' WHERE signal_id=?", (sid,))

    def accept(self, sid, result):
        job = self.get(sid)
        extraction = TextExtraction.model_validate(result["extraction"]).validate_source(job["original"]["text"])
        revision = job["revision"] + 1
        result = {**result, "signal_id": sid, "content_hash": digest(job["original"]["text"]),
                  "revision": revision, "recorded_at": now()}
        dataset = self.dataset()
        signal = next(s for s in dataset.signals if s.signal_id == sid)
        reviewed = result["source"] == "manual"
        signal.evidence = [] if result["review_state"] == "needs_review" else evidence_from(extraction, sid, revision, reviewed)
        signal.provenance.annotation_method = "human_reviewed" if reviewed else "ai_text"
        if reviewed:
            signal.provenance.reviewer = result["reviewer"]
        clock = datetime.now(timezone.utc)
        incidents, excluded, signals = run_engine(dataset, clock)
        step = self.store.state()["step"] + 1
        with self.store.connection() as db:
            db.execute("INSERT INTO extraction_revisions VALUES(?,?,?)", (sid, revision, json.dumps(result)))
            db.execute("UPDATE text_jobs SET status=?,error_code=NULL,revision=? WHERE signal_id=?",
                ("needs_review" if result["review_state"] == "needs_review" else "processed", revision, sid))
            db.execute("UPDATE datasets SET fixture_json=?", (dataset.model_dump_json(),))
            self.store.commit_step(dataset, clock, step, incidents, excluded, signals, db_connection=db)

    def review(self, sid, request):
        image = self.images.get(sid)
        if image is not None:
            try:
                from .image_observations import ImageCorrection
                image_request = ImageCorrection.model_validate(request)
            except ImportError:
                raise HTTPException(422, "Image correction schema unavailable") from None
            except Exception:
                raise HTTPException(422, "Invalid image correction") from None
            return self.images.review(sid, image_request)
        with self.lock:
            if isinstance(request, dict):
                try:
                    request = Correction.model_validate(request)
                except Exception:
                    raise HTTPException(422, "Invalid text correction") from None
            job = self.get(sid)
            self.guard_revision(job, request.expected_revision)
            try:
                request.extraction.validate_source(job["original"]["text"])
            except ValueError:
                raise HTTPException(422, "Correction spans must be original report substrings") from None
            self.accept(sid, {"extraction": request.extraction.model_dump(mode="json"), "source": "manual",
                "provider": "human", "model": None, "model_identifier": None, "prompt_version": PROMPT_VERSION,
                "schema_version": SCHEMA_VERSION, "task_version": TASK_VERSION, "processed_at": now(),
                "raw_response_reference": None, "fallback_used": False, "fallback_reason": None,
                "review_state": "human_reviewed", "reviewer": request.reviewer, "review_reason": request.reason})
            return self.get(sid)

    @staticmethod
    def guard_revision(job, expected):
        if job["status"] in ("pending", "analyzing"):
            raise HTTPException(409, "Processing already in progress")
        if job["revision"] != expected:
            raise HTTPException(409, "Revision changed; reload before reviewing")

    def snapshot(self):
        with self.lock:
            dataset, state = self.dataset(), self.store.state()
            return {"dataset_id": dataset.dataset_id, "mode": "operator_multimodal", "clock": state["clock"],
                "step": state["step"], "total_steps": state["step"], "incidents": self.store.incidents(),
                "signals": [signal_for_client(self.store.get_signal(s.signal_id)) for s in dataset.signals],
                "roads": dataset.roads,
                "excluded": json.loads(state["excluded_json"])}


def register_observations(app, observations):
    @app.post("/api/v1/signals", status_code=202)
    def submit(request: NewObservation, tasks: BackgroundTasks):
        sid, created = observations.submit(request)
        if created:
            tasks.add_task(observations.process, sid)
        return observations.get(sid)

    @app.post("/api/v1/images", status_code=202)
    async def upload_image(request: Request, tasks: BackgroundTasks):
        """Accept multipart metadata JSON plus one bounded JPEG/PNG upload."""
        fallback_content = None
        try:
            form = await request.form(max_files=1, max_fields=1, max_part_size=5 * 1024 * 1024)
        except (RuntimeError, AssertionError) as error:
            if "python-multipart" not in str(error):
                raise HTTPException(422, "Multipart image upload is required") from None
            metadata, fallback_content = await _read_multipart_fallback(request)
            image = None
        metadata = form.get("metadata") if fallback_content is None else metadata
        image = form.get("image") if fallback_content is None else image
        if fallback_content is None and (set(form.keys()) != {"metadata", "image"} or metadata is None or
                not isinstance(image, UploadFile) and not hasattr(image, "read")):
            raise HTTPException(422, "metadata JSON and image file are required")
        try:
            raw_metadata = json.loads(metadata if isinstance(metadata, str) else metadata.decode("utf-8"))
        except (TypeError, ValueError, UnicodeDecodeError):
            raise HTTPException(422, "metadata must be valid JSON") from None
        try:
            chunks = []
            total = 0
            if fallback_content is not None:
                chunks = [fallback_content]
                total = len(fallback_content)
            else:
                while True:
                    chunk = await image.read(min(1024 * 1024, 5 * 1024 * 1024 + 1 - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > 5 * 1024 * 1024:
                        raise HTTPException(413, "image_too_large")
            sid, created, linked_text = observations.images.submit(raw_metadata, b"".join(chunks))
            if created:
                tasks.add_task(observations.images.process, sid)
                if linked_text:
                    tasks.add_task(observations.process, linked_text)
            return observations.get(sid)
        finally:
            if image is not None:
                await image.close()

    @app.get("/api/v1/observations")
    def listing():
        return observations.all()

    @app.get("/api/v1/signals/{sid}/processing")
    def processing(sid: str):
        with observations.lock:
            return observations.get(sid)

    @app.post("/api/v1/signals/{sid}/review")
    def review(sid: str, request: dict):
        return observations.review(sid, request)

    @app.post("/api/v1/signals/{sid}/reanalyze", status_code=202)
    def reanalyze(sid: str, request: Reanalysis, tasks: BackgroundTasks):
        with observations.lock:
            job = observations.get(sid)
            observations.guard_revision(job, request.expected_revision)
            if request.action == "deeper_review" and not observations.perception.settings.fallback_enabled:
                raise HTTPException(409, "Terra fallback is disabled")
            table = "image_jobs" if job.get("kind") == "image" else "text_jobs"
            with observations.store.connection() as db:
                db.execute(f"UPDATE {table} SET status='pending',error_code=NULL WHERE signal_id=?", (sid,))
            tasks.add_task(observations.process, sid, request.action == "deeper_review")
            return observations.get(sid)

    @app.get("/api/v1/live/incidents")
    def live_incidents():
        return observations.snapshot()

    @app.get("/api/v1/perception/usage")
    def usage():
        return observations.perception.summary()
