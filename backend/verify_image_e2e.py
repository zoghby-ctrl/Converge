"""Offline end-to-end verification using two real cached OpenAI image extractions."""
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.image_ingestion import normalize_image
from backend.app.image_perception import ImagePerception
from backend.app.main import create_app
from backend.app.perception import Settings
from backend.app.store import ROOT, Store, default_path


IMAGE_IDS = ("water-04", "damage-01")


def verify():
    manifest = json.loads((ROOT / "fixtures/images/manifest.json").read_text(encoding="utf-8"))
    examples = {item["id"]: item for item in manifest["images"] if item["id"] in IMAGE_IDS}
    runtime = default_path().parent
    runtime.mkdir(parents=True, exist_ok=True)
    source_path = default_path().with_name(default_path().stem + "-text.sqlite3")
    source = ImagePerception(Store(source_path), Settings.from_env())
    results = []

    with tempfile.TemporaryDirectory(prefix="phase2b-e2e-", dir=runtime) as folder:
        directory = Path(folder)
        app_path = directory / "e2e.sqlite3"
        live_path = directory / "e2e-text.sqlite3"
        offline = Settings(api_key="")
        target = ImagePerception(Store(live_path), offline)
        prepared_metadata = {}

        # Copy only the two validated structured cache entries, rebinding their
        # deterministic normalized paths to this disposable runtime directory.
        for image_id in IMAGE_IDS:
            row = examples[image_id]
            raw = (ROOT / row["path"]).read_bytes()
            source_metadata = normalize_image(raw, source_path.parent)
            source_key = source.cache_key(source_metadata, source.settings.primary)
            with source.store.connection() as db:
                cached = db.execute(
                    "SELECT payload FROM extraction_cache WHERE cache_key=?", (source_key,)
                ).fetchone()
            if not cached:
                raise RuntimeError(f"Required locked cache entry is absent: {image_id}")
            target_metadata = normalize_image(raw, directory)
            prepared_metadata[image_id] = target_metadata
            payload = json.loads(cached[0])
            payload["image_metadata"] = target_metadata
            target_key = target.cache_key(target_metadata, target.settings.primary)
            with target.store.connection() as db:
                db.execute(
                    "INSERT INTO extraction_cache(cache_key,payload) VALUES(?,?)",
                    (target_key, json.dumps(payload)),
                )

        app = create_app(app_path, offline)
        before = app.state.observations.perception.summary()
        observed = datetime.now(timezone.utc).isoformat()
        with TestClient(app) as client:
            for index, image_id in enumerate(IMAGE_IDS):
                row = examples[image_id]
                metadata = {
                    "text": None, "lat": 30.054, "lon": 31.336 + index * 0.0001,
                    "observed_at": observed, "location_accuracy_m": 10,
                    "road_context_id": "Phase2B cached image E2E",
                    "capture_group_id": f"phase2b-e2e-{index}", "independence": "asserted",
                    "operator": "Phase 2B verification",
                    "idempotency_key": f"phase2b-e2e-{image_id}",
                    "content_origin": "public_source", "source_ref": row["source_url"],
                    "license": row["license"], "placement_origin": "simulated",
                    "time_origin": "simulated",
                }
                response = client.post(
                    "/api/v1/images", data={"metadata": json.dumps(metadata)},
                    files={"image": (Path(row["path"]).name,
                                     (ROOT / row["path"]).read_bytes(), "image/jpeg")},
                )
                if response.status_code != 202:
                    raise RuntimeError(f"Upload failed for {image_id}: {response.status_code}")
                created = response.json()
                job = client.get(
                    f"/api/v1/signals/{created['signal_id']}/processing"
                ).json()
                if job["status"] not in {"processed", "needs_review"}:
                    raise RuntimeError(
                        f"Extraction did not complete for {image_id}: "
                        f"{job['status']} ({job.get('error_code')})"
                    )
                if job.get("latest") is None:
                    with app.state.observations.store.connection() as db:
                        current = json.loads(db.execute(
                            "SELECT normalization_json FROM image_jobs WHERE signal_id=?",
                            (created["signal_id"],),
                        ).fetchone()[0])
                    differences = sorted(
                        key for key in current
                        if current.get(key) != prepared_metadata[image_id].get(key)
                    )
                    raise RuntimeError(
                        f"Extraction revision missing for {image_id}: "
                        f"{job['status']} ({job.get('error_code')}); metadata fields: {differences}"
                    )
                if job["latest"]["source"] != "cached" or job["latest"]["model"] != "gpt-5.6-luna":
                    raise RuntimeError(f"Unexpected perception provenance for {image_id}")
                if "stored_path" in job["original"] or "preserved_path" in job["original"]:
                    raise RuntimeError("Server paths escaped the processing response")
                image_response = client.get(f"/api/v1/signals/{created['signal_id']}/image")
                if image_response.status_code != 200:
                    raise RuntimeError(f"Normalized image is unavailable for {image_id}")
                results.append({
                    "id": image_id, "signal_id": created["signal_id"],
                    "status": job["status"], "source": job["latest"]["source"],
                    "model": job["latest"]["model"],
                    "states": {field: job["latest"]["extraction"][field] for field in (
                        "standing_water", "visible_surface_damage", "passage_obstruction")},
                    "image_status": image_response.status_code,
                })

            snapshot = client.get("/api/v1/live/incidents").json()
            signal_ids = {item["signal_id"] for item in results}
            incident = next(
                (item for item in snapshot["incidents"] if signal_ids <= set(item["signal_ids"])), None
            )
            if incident is None or incident["status"] != "candidate":
                raise RuntimeError("Cached image evidence did not form the expected candidate")

        after = app.state.observations.perception.summary()
        if after["total_api_requests"] != before["total_api_requests"]:
            raise RuntimeError("Offline E2E unexpectedly made an API request")
        report = {
            "passed": True, "verified_at": datetime.now(timezone.utc).isoformat(),
            "network_mode": "offline_api_key_blank", "api_requests": 0,
            "cache_hits": after["image_cache_hits"] - before["image_cache_hits"],
            "uploads": results,
            "incident": {
                "status": incident["status"],
                "independent_capture_count": incident["independent_capture_count"],
                "standing_water": incident["features"]["standing_water"]["state"],
                "visible_road_damage": incident["features"]["visible_road_damage"]["state"],
                "risk_display": incident["risk"]["display"],
                "evidence_strength": incident["evidence_strength"],
            },
        }
    output = ROOT / "docs/image-e2e-verification.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    verify()
