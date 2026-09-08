import pytest
from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.app.perception import Settings
from backend.app.models import ImageObservationMetadata

@pytest.mark.parametrize("origin,accuracy", [("synthetic", None), ("collected", 17.25), ("collected", 750)])
def test_honest_unknown_location_contract(tmp_path, origin, accuracy):
    payload = dict(text="Release location contract", lat=30.054, lon=31.336,
                   observed_at="2026-09-08T12:00:00Z", location_accuracy_m=accuracy,
                   road_context_id=None, capture_group_id="release-location", independence="uncertain",
                   operator="Citizen report", content_origin=origin, idempotency_key="release-location")
    image = ImageObservationMetadata.model_validate(payload)
    assert image.location_accuracy_m == accuracy
    assert image.road_context_id is None
    if origin == "synthetic":
        assert image.placement_origin == "simulated"
    app = create_app(tmp_path / "release.sqlite3", perception_settings=Settings(api_key=""))
    with TestClient(app) as client:
        response = client.post("/api/v1/signals", json=payload)
        assert response.status_code == 202, response.text
        sid = response.json()["signal_id"]
        with app.state.observations.store.connection() as db:
            import json
            signal = json.loads(db.execute("SELECT payload FROM signals WHERE signal_id=?", (sid,)).fetchone()[0])
            assert signal["location_accuracy_m"] == accuracy
            assert signal["road_context_id"] is None
            assert signal["independence"] == "uncertain"
            assert signal["provenance"]["content_origin"] == origin
            assert db.execute("SELECT count(*) FROM road_contexts").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM api_usage").fetchone()[0] == 0

