from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.app.perception import Settings
from tests.test_perception import FakeClient, extracted


def test_app_version_metadata(tmp_path):
    app = create_app(tmp_path / "meta.sqlite3")
    assert app.title == "Converge — Incident Intelligence"
    assert app.version == "4.0"


def test_out_of_area_geolocation_rejected_by_backend(tmp_path):
    app = create_app(tmp_path / "geo.sqlite3", Settings(),
                     FakeClient(extracted("Water pooling on the pavement")))
    with TestClient(app) as client:
        # 1. Coordinate south of Nasr City study area (lat < 30.045)
        res_south = client.post(
            "/api/v1/signals",
            json={
                "text": "Water pooling on the pavement",
                "lat": 30.020,
                "lon": 31.336,
                "observed_at": "2026-09-07T20:00:00Z",
                "location_accuracy_m": 10,
                "road_context_id": "Street 14",
                "capture_group_id": "cg-test-1",
                "independence": "asserted",
                "operator": "Citizen report",
                "content_origin": "collected",
                "idempotency_key": "idemp-geo-1",
            },
        )
        assert res_south.status_code == 422

        # 2. Coordinate west of Nasr City study area (lon < 31.325)
        res_west = client.post(
            "/api/v1/signals",
            json={
                "text": "Water pooling on the pavement",
                "lat": 30.054,
                "lon": 31.250,
                "observed_at": "2026-09-07T20:00:00Z",
                "location_accuracy_m": 10,
                "road_context_id": "Street 14",
                "capture_group_id": "cg-test-2",
                "independence": "asserted",
                "operator": "Citizen report",
                "content_origin": "collected",
                "idempotency_key": "idemp-geo-2",
            },
        )
        assert res_west.status_code == 422

        # 3. Coordinate inside Nasr City study area (Street 14 preset)
        res_valid = client.post(
            "/api/v1/signals",
            json={
                "text": "Water pooling on the pavement",
                "lat": 30.054,
                "lon": 31.336,
                "observed_at": "2026-09-07T20:00:00Z",
                "location_accuracy_m": 10,
                "road_context_id": "Street 14",
                "capture_group_id": "cg-test-3",
                "independence": "asserted",
                "operator": "Citizen report",
                "content_origin": "collected",
                "idempotency_key": "idemp-geo-3",
            },
        )
        assert res_valid.status_code == 202
        assert "signal_id" in res_valid.json()


def test_human_review_and_correction_lineage(tmp_path):
    # Revision history is a local contract test, independent of live credentials.
    app = create_app(tmp_path / "review.sqlite3", Settings(),
                     FakeClient(extracted("Severe flooding")))
    with TestClient(app) as client:
        # Submit a text observation with specific text
        submit_res = client.post(
            "/api/v1/signals",
            json={
                "text": "Severe flooding on Street 14 with asphalt crater",
                "lat": 30.054,
                "lon": 31.336,
                "observed_at": "2026-09-07T20:00:00Z",
                "location_accuracy_m": 10,
                "road_context_id": "way-street_14_segment_01",
                "capture_group_id": "cg-rev-1",
                "independence": "asserted",
                "operator": "Citizen report",
                "content_origin": "collected",
                "idempotency_key": "idemp-rev-1",
            },
        )
        assert submit_res.status_code == 202
        sid = submit_res.json()["signal_id"]

        # Fetch initial processing state
        proc = client.get(f"/api/v1/signals/{sid}/processing").json()
        assert proc["signal_id"] == sid
        assert proc["status"] == "processed"
        assert proc["revision"] == 1
        assert len(proc["revisions"]) == 1
        assert proc["original"]["text"] == "Severe flooding on Street 14 with asphalt crater"
        initial_ext = proc["latest"]["extraction"]

        # Engineer performs human review & correction
        revised_extraction = {
            "language": "english",
            "standing_water": "present",
            "road_damage": "present",
            "passage_obstruction": "not_mentioned",
            "reported_duration": None,
            "recurrence": "not_mentioned",
            "reported_explanation": None,
            "temporal_status": "current",
            "uncertainties": [],
            "evidence_spans": [
                {
                    "field": "standing_water",
                    "quote": "Severe flooding",
                    "temporal_status": "current",
                },
                {
                    "field": "road_damage",
                    "quote": "asphalt crater",
                    "temporal_status": "current",
                },
            ],
        }
        correction_payload = {
            "expected_revision": 1,
            "reviewer": "Eng. Tarek",
            "reason": "Field inspection confirmed severe pooling and asphalt crater",
            "extraction": revised_extraction,
        }

        review_res = client.post(f"/api/v1/signals/{sid}/review", json=correction_payload)
        assert review_res.status_code == 200
        reviewed_job = review_res.json()

        # Check revision lineage
        assert reviewed_job["revision"] == 2
        assert len(reviewed_job["revisions"]) == 2
        assert reviewed_job["revisions"][0]["revision"] == 1
        assert reviewed_job["revisions"][1]["revision"] == 2
        assert reviewed_job["revisions"][1]["review_state"] == "human_reviewed"
        assert reviewed_job["revisions"][1]["reviewer"] == "Eng. Tarek"
        assert (
            reviewed_job["revisions"][1]["review_reason"]
            == "Field inspection confirmed severe pooling and asphalt crater"
        )
        # Original text must remain untouched
        assert reviewed_job["original"]["text"] == "Severe flooding on Street 14 with asphalt crater"

        # Check that incidents recomputed and signal marked human_reviewed
        live = client.get("/api/v1/live/incidents").json()
        matching_signals = [s for s in live["signals"] if s["signal_id"] == sid]
        assert len(matching_signals) == 1
        assert matching_signals[0]["provenance"]["annotation_method"] == "human_reviewed"
        assert matching_signals[0]["provenance"]["reviewer"] == "Eng. Tarek"
        assert any(e["feature"] == "visible_road_damage" for e in matching_signals[0]["evidence"])


def test_service_worker_promise_fallback_fix(tmp_path):
    app = create_app(tmp_path / "sw_test.sqlite3")
    with TestClient(app) as client:
        res = client.get("/sw.js")
        assert res.status_code == 200
        content = res.text
        # Must contain the resolved Promise chaining:
        assert ".then((cached) => cached || caches.match('/'))" in content
        # Must not contain the buggy synchronous OR on un-awaited Promise:
        assert "caches.match('/index.html') || caches.match('/')" not in content


def test_runtime_ai_ledger_sanity(tmp_path):
    app = create_app(tmp_path / "ledger_test.sqlite3")
    with TestClient(app) as client:
        usage = client.get("/api/v1/perception/usage").json()
        assert "total_api_requests" in usage
        assert "max_requests" in usage
        assert "budget_accounted_usd" in usage
        # When under max_requests, not blocked
        assert usage["total_api_requests"] <= usage["max_requests"]
