import io
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image

from backend.app.main import create_app
from backend.app.perception import Settings


def png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (80, 60), (100, 100, 100)).save(output, format="PNG")
    return output.getvalue()


def extraction():
    return {
        "standing_water": "present", "visible_surface_damage": "not_assessable",
        "passage_obstruction": "not_assessable", "image_quality": "usable",
        "visible_description": "Pooled water is visible.",
        "uncertainties": [
            {"field": "visible_surface_damage", "reason": "occluded"},
            {"field": "passage_obstruction", "reason": "unclear_boundary"},
        ],
        "support_descriptions": [{"field": "standing_water", "description": "Pooled water is visible."}],
    }


def text_extraction():
    return {
        "language": "english", "standing_water": "present",
        "road_damage": "not_mentioned", "passage_obstruction": "not_mentioned",
        "reported_duration": None, "recurrence": "not_mentioned",
        "reported_explanation": None, "temporal_status": "current",
        "evidence_spans": [{"field": "standing_water", "quote": "water here",
                            "temporal_status": "current"}],
        "uncertainties": [],
    }


class FakeClient:
    def __init__(self):
        self.calls = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        schema_name = kwargs["text"]["format"]["name"]
        output = extraction() if schema_name == "image_observation" else text_extraction()
        return SimpleNamespace(output_text=json.dumps(output), model=kwargs["model"],
                               id=f"image-response-{len(self.calls)}", status="completed",
                               usage=SimpleNamespace(input_tokens=20, output_tokens=20))


class AmbiguousDamageClient(FakeClient):
    def create(self, **kwargs):
        self.calls.append(kwargs)
        output = {
            "standing_water": "absent", "visible_surface_damage": "present",
            "passage_obstruction": "not_assessable", "image_quality": "usable",
            "visible_description": "A chipped concrete edge is visible beside a flat surface.",
            "uncertainties": [{"field": "passage_obstruction", "reason": "unclear_boundary"}],
            "support_descriptions": [
                {"field": "standing_water", "description": "No pooled water is visible."},
                {"field": "visible_surface_damage", "description": "Chipped concrete edges are visible."},
            ],
        }
        return SimpleNamespace(output_text=json.dumps(output), model=kwargs["model"],
                               id="ambiguous-damage", status="completed",
                               usage=SimpleNamespace(input_tokens=20, output_tokens=20))


def metadata(**changes):
    value = {
        "text": "water here", "lat": 30.054, "lon": 31.336,
        "observed_at": datetime.now(timezone.utc).isoformat(), "location_accuracy_m": 10,
        "road_context_id": "Operator road", "capture_group_id": "capture-1",
        "operator": "operator", "idempotency_key": "image-1", "content_origin": "collected",
        "source_ref": "field-photo-1", "license": "team owned",
        "placement_origin": "original", "time_origin": "original",
    }
    value.update(changes)
    return value


def upload(client, value):
    return client.post("/api/v1/images", data={"metadata": json.dumps(value)},
                       files={"image": ("road.png", png_bytes(), "image/png")})


def test_image_upload_pairs_text_reuses_capture_and_serves_scoped_image(tmp_path):
    fake = FakeClient()
    app = create_app(tmp_path / "operator.sqlite3", Settings(), fake)
    with TestClient(app) as client:
        response = upload(client, metadata(independence="asserted"))
        assert response.status_code == 202, response.text
        job = response.json()
        assert job["kind"] == "image" and job["linked_text_signal_id"]
        assert job["original"]["kind"] == "image"
        job = client.get(f"/api/v1/signals/{job['signal_id']}/processing").json()
        assert job["latest"]["extraction"]["standing_water"] == "present"
        assert client.get(f"/api/v1/signals/{job['signal_id']}/image").status_code == 200
        signals = client.get("/api/v1/live/incidents").json()["signals"]
        assert {item["source_family"] for item in signals} == {"image", "text"}
        assert all(item.get("image_path") is None for item in signals)
        assert next(item for item in signals if item["source_family"] == "image")["image_url"]
        incidents = client.get("/api/v1/live/incidents").json()["incidents"]
        assert len(incidents) == 1 and incidents[0]["independent_capture_count"] == 1
        assert len(fake.calls) == 2  # one image and one paired text extraction


def test_image_idempotency_and_wrong_kind_review_are_rejected(tmp_path):
    fake = FakeClient()
    app = create_app(tmp_path / "operator.sqlite3", Settings(), fake)
    with TestClient(app) as client:
        payload = metadata(text=None)
        first = upload(client, payload).json()
        again = upload(client, payload).json()
        assert again["signal_id"] == first["signal_id"]
        assert len(fake.calls) == 1
        wrong = client.post(f"/api/v1/signals/{first['signal_id']}/review", json={
            "extraction": {"language": "english", "standing_water": "not_mentioned",
                "road_damage": "not_mentioned", "passage_obstruction": "not_mentioned",
                "reported_duration": None, "recurrence": "not_mentioned",
                "reported_explanation": None, "temporal_status": "uncertain",
                "evidence_spans": [], "uncertainties": []},
            "reviewer": "engineer", "reason": "wrong modality", "expected_revision": 1})
        assert wrong.status_code == 422
        assert client.get(f"/api/v1/signals/{first['signal_id']}/image/../../../../etc/passwd").status_code in (404, 405)


def test_image_idempotency_rejects_changed_metadata(tmp_path):
    app = create_app(tmp_path / "operator.sqlite3", Settings(), FakeClient())
    with TestClient(app) as client:
        payload = metadata(text=None)
        assert upload(client, payload).status_code == 202
        changed = {**payload, "lat": payload["lat"] + 0.001}
        assert upload(client, changed).status_code == 409


def test_image_upload_rejects_invalid_format_size_and_extra_metadata(tmp_path):
    app = create_app(tmp_path / "operator.sqlite3", Settings(), FakeClient())
    with TestClient(app) as client:
        invalid = client.post("/api/v1/images", data={"metadata": json.dumps(metadata(text=None))},
                              files={"image": ("road.txt", b"not an image", "text/plain")})
        assert invalid.status_code == 422 and invalid.json()["detail"] == "invalid_image"
        large = client.post("/api/v1/images", data={"metadata": json.dumps(metadata(
            text=None, idempotency_key="large-1"))}, files={
                "image": ("large.png", b"x" * (5 * 1024 * 1024 + 1), "image/png")})
        assert large.status_code == 413 and large.json()["detail"] == "image_too_large"
        extra = upload(client, metadata(text=None, idempotency_key="extra-1", model="gpt-anything"))
        assert extra.status_code == 422


def test_ambiguous_damage_is_held_for_review_before_incident_use(tmp_path):
    app = create_app(tmp_path / "operator.sqlite3", Settings(), AmbiguousDamageClient())
    with TestClient(app) as client:
        created = upload(client, metadata(text=None)).json()
        job = client.get(f"/api/v1/signals/{created['signal_id']}/processing").json()
        assert job["status"] == "needs_review"
        assert job["latest"]["admission_warnings"] == [
            "surface_damage_travel_surface_not_explicit"
        ]
        signal = next(item for item in client.get("/api/v1/live/incidents").json()["signals"]
                      if item["signal_id"] == created["signal_id"])
        assert "visible_road_damage" not in {item["feature"] for item in signal["evidence"]}


def test_exact_image_reuse_does_not_inflate_independent_corroboration(tmp_path):
    app = create_app(tmp_path / "operator.sqlite3", Settings(), FakeClient())
    with TestClient(app) as client:
        first = metadata(text=None, idempotency_key="image-a", capture_group_id="capture-a",
                         independence="asserted")
        second = metadata(text=None, idempotency_key="image-b", capture_group_id="capture-b",
                          independence="asserted")
        assert upload(client, first).status_code == 202
        assert upload(client, second).status_code == 202
        snapshot = client.get("/api/v1/live/incidents").json()
        assert len(snapshot["incidents"]) == 1
        assert snapshot["incidents"][0]["status"] == "watch"
        assert snapshot["incidents"][0]["independent_capture_count"] == 1
        image_signals = [item for item in snapshot["signals"] if item["source_family"] == "image"]
        assert len(image_signals) == 2 and sum(item["duplicate_of"] is not None for item in image_signals) == 1


def test_human_image_correction_preserves_history_and_recomputes(tmp_path):
    app = create_app(tmp_path / "operator.sqlite3", Settings(), FakeClient())
    with TestClient(app) as client:
        created = upload(client, metadata(text=None)).json()
        job = client.get(f"/api/v1/signals/{created['signal_id']}/processing").json()
        original_hash = job["original"]["raw_hash"]
        correction = {
            "standing_water": "absent", "visible_surface_damage": "present",
            "passage_obstruction": "not_assessable", "image_quality": "usable",
            "visible_description": "A dry road surface with a visibly broken area.",
            "uncertainties": [{"field": "passage_obstruction", "reason": "unclear_boundary"}],
            "support_descriptions": [
                {"field": "standing_water", "description": "The visible road surface is dry."},
                {"field": "visible_surface_damage", "description": "Broken asphalt is visible."},
            ],
        }
        reviewed = client.post(f"/api/v1/signals/{created['signal_id']}/review", json={
            "extraction": correction, "reviewer": "engineer", "reason": "Pixel review",
            "expected_revision": job["revision"],
        })
        assert reviewed.status_code == 200, reviewed.text
        result = reviewed.json()
        assert result["revision"] == 2 and len(result["revisions"]) == 2
        assert result["revisions"][0]["extraction"]["standing_water"] == "present"
        assert result["latest"]["source"] == "manual"
        assert result["original"]["raw_hash"] == original_hash
        signal = next(item for item in client.get("/api/v1/live/incidents").json()["signals"]
                      if item["signal_id"] == created["signal_id"])
        assert signal["provenance"]["annotation_method"] == "human_reviewed"
        assert {e["feature"] for e in signal["evidence"]} == {"standing_water", "visible_road_damage"}
