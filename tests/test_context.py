import hashlib
import json
import socket
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.context import (CONTEXT, assign_road, cached_rainfall, distance_to_line,
    geography, load_context_demo, load_roads, manifest, rainfall_from_response, read_verified)
from backend.app.engine import haversine, run_engine
from backend.app.main import create_app
from backend.app.models import ContextSource, Dataset

UTC = timezone.utc
CLOCK = datetime(2025, 1, 1, 11, 15, tzinfo=UTC)


def weather():
    entry = manifest()["weather"]
    return json.loads(read_verified(entry)), ContextSource.model_validate(entry["source"])


def adapt(data, source, clock=CLOCK):
    raw = json.dumps(data).encode()
    source = source.model_copy(update={"raw_sha256": hashlib.sha256(raw).hexdigest()})
    return rainfall_from_response(raw, source, clock, retrospective_demo=True)


def run(dataset):
    return run_engine(dataset, max(s.available_at for s in dataset.signals))[0]


def candidate(items):
    return next(i for i in items if "b-water-first" in i.signal_ids or i.status == "candidate")


def test_authentic_assets_integrity_and_bounded_catalog():
    info = manifest()
    for key in ("roads", "weather", "geography", "catalog"):
        assert read_verified(info[key])
    roads = load_roads()
    assert len(roads) == 20
    assert len(geography()["features"]) == 910
    for road in roads:
        a, b = road.coordinates
        assert haversine(a[1], a[0], b[1], b[0]) <= 110.001
        assert road.compatible_ids == []
        assert road.provenance.content_origin == "public_source"
        assert road.source.provider == "OpenStreetMap"
        lon, lat = [(a[k] + b[k]) / 2 for k in (0, 1)]
        assert assign_road(lon, lat, 5)["road_context_id"] == road.road_context_id


def test_integrity_mismatch_rejected(tmp_path):
    (tmp_path / "bad.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="integrity"):
        read_verified({"raw_ref": "bad.json", "raw_sha256": "0" * 64}, tmp_path)


def test_truncated_compressed_cache_rejected(tmp_path):
    import gzip
    (tmp_path / "bad.gz").write_bytes(gzip.compress(b"source")[:-5])
    with pytest.raises(ValueError, match="Truncated"):
        read_verified({"raw_ref": "bad.gz", "raw_sha256": "0" * 64}, tmp_path)


def test_hour_end_semantics_select_six_completed_hours():
    data, source = weather()
    data["hourly"]["rain"] = list(range(48))  # Deliberately synthetic adapter guard.
    rain = adapt(data, source)
    assert rain.hourly_mm == [6, 7, 8, 9, 10, 11]
    assert rain.source.interval_ends[0] == datetime(2025, 1, 1, 6, tzinfo=UTC)
    assert rain.source.interval_ends[-1] == CLOCK.replace(minute=0)


@pytest.mark.parametrize("change", ["null", "missing"])
def test_missing_hours_remain_unknown_and_cannot_claim_dry(change):
    data, source = weather()
    if change == "null":
        data["hourly"]["rain"][8] = None
    else:
        del data["hourly"]["time"][8]
        del data["hourly"]["rain"][8]
    rain = adapt(data, source)
    assert None in rain.hourly_mm
    dataset = load_context_demo("context_archive")
    dataset.rainfall = [rain]
    item = candidate(run(dataset))
    assert item.features["rainfall_context"].value is None
    assert "rainfall relationship unknown" in item.hypotheses[0].title
    assert not any(c.rule_id.endswith((".R", ".N")) for h in item.hypotheses for c in h.contributions)


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), "0", True])
def test_invalid_provider_values_reject_whole_context(bad):
    data, source = weather()
    data["hourly"]["rain"][8] = bad
    with pytest.raises(ValueError):
        adapt(data, source)


@pytest.mark.parametrize("kind", ["units", "timezone", "duplicate", "length", "off_hour", "grid", "product"])
def test_invalid_provider_metadata_rejected(kind):
    data, source = weather()
    if kind == "units": data["hourly_units"]["rain"] = "inch"
    if kind == "timezone": data["utc_offset_seconds"] = 7200
    if kind == "duplicate": data["hourly"]["time"][8] = data["hourly"]["time"][7]
    if kind == "length": data["hourly"]["rain"].pop()
    if kind == "off_hour": data["hourly"]["time"][8] = "2025-01-01T08:30"
    if kind == "grid": data["latitude"] = 0
    if kind == "product": source = source.model_copy(update={"product": "best_match"})
    with pytest.raises(ValueError): adapt(data, source)


def test_acquisition_is_not_fabricated_as_issued_availability():
    entry = manifest()["weather"]
    source = ContextSource.model_validate(entry["source"])
    rain = rainfall_from_response(read_verified(entry), source, CLOCK)
    assert rain.available_at == source.acquired_at > CLOCK
    dataset = load_context_demo("context_archive")
    dataset.rainfall = [rain]
    assert candidate(run(dataset)).features["rainfall_context"].state == "unknown"
    replay, status = cached_rainfall(CLOCK, retrospective_demo=True)
    assert status == "complete_retrospective"
    assert replay.source.application == "retrospective_demo"
    assert replay.source.acquired_at == source.acquired_at
    assert replay.provenance.time_origin == "original"
    assert replay.hourly_mm == [0] * 6
    _, status = cached_rainfall(datetime(2026, 9, 7, tzinfo=UTC))
    assert status == "missing_hours"


def test_missing_or_corrupt_cache_does_not_synthesize_zero(monkeypatch):
    import backend.app.context as module
    def fail(*args, **kwargs): raise OSError("offline missing file")
    monkeypatch.setattr(module, "read_verified", fail)
    rain, status = cached_rainfall(CLOCK)
    assert rain is None and status == "cache_unavailable_or_invalid"


@pytest.mark.parametrize("kind", ["stale", "future_available", "outside_footprint"])
def test_context_validity_guards(kind):
    dataset = load_context_demo("context_archive")
    rain = dataset.rainfall[-1]
    if kind == "stale": rain.end_at -= timedelta(hours=1)
    if kind == "future_available": rain.available_at += timedelta(days=1)
    if kind == "outside_footprint": rain.bbox = (0, 0, 1, 1)
    dataset.rainfall = [rain]
    assert candidate(run(dataset)).features["rainfall_context"].state == "unknown"


def test_real_context_only_changes_frozen_context_paths():
    dry = load_context_demo("context_archive")
    before = candidate(run(dry))
    assert (before.risk.display, before.independent_capture_count, before.evidence_strength) == ("68", 3, "Moderate")
    assert before.features["rainfall_context"].value == 0
    no_rain = dry.model_copy(deep=True)
    no_rain.rainfall = []
    after = candidate(run(no_rain))
    assert before.risk == after.risk
    assert before.independent_capture_count == after.independent_capture_count
    assert before.hypotheses != after.hypotheses
    dry.rainfall += [r.model_copy(update={"context_id": "zz-copy-" + r.context_id}) for r in dry.rainfall]
    repeated = candidate(run(dry))
    assert before.hypotheses == repeated.hypotheses
    assert before.risk == repeated.risk
    for road in dry.roads: road.road_class = None
    missing = candidate(run(dry))
    assert missing.risk.components["exposure"] is None
    assert (missing.risk.risk_min, missing.risk.risk_max) == (52.5, 67.5)
    assert missing.independent_capture_count == 3
    dry.signals = []
    assert run_engine(dry, CLOCK)[0] == []


@pytest.mark.parametrize("accuracy", [None, -1, 50.001, float("nan")])
def test_bad_location_accuracy_abstains(accuracy):
    assert assign_road(31.335, 30.054, accuracy)["road_context_id"] is None


def test_nearest_30m_ambiguity_10m_and_parallel_barrier_guards():
    road = load_roads()[0].model_copy(deep=True)
    road.coordinates = [(31.335, 30.053), (31.335, 30.055)]
    empty = {"features": []}
    scale = 111195.0802 * __import__('math').cos(__import__('math').radians(30.054))
    assert assign_road(31.335 + 30 / scale, 30.054, 50, [road], empty)["road_context_id"]
    assert assign_road(31.335 + 30.01 / scale, 30.054, 5, [road], empty)["road_context_id"] is None
    parallel = road.model_copy(deep=True, update={"road_context_id": "osm-other-0-0",
        "coordinates": [(31.335 + 20 / scale, 30.053), (31.335 + 20 / scale, 30.055)]})
    assert assign_road(31.335 + 5 / scale, 30.054, 5, [road, parallel], empty)["reason"] == "ambiguous_incompatible_segment"
    # An unreviewed crossing/parallel/bridge way must compete too.
    background = {"features": [{"properties": {"osm_way_id": "other", "bridge": "yes"},
        "geometry": {"coordinates": parallel.coordinates}}]}
    assert assign_road(31.335 + 5 / scale, 30.054, 5, [road], background)["reason"] == "ambiguous_mapped_way"
    assert assign_road(0, 0, 5, [road], empty)["reason"] == "outside_study_extent"


def test_sourced_different_sections_do_not_merge():
    dataset = load_context_demo("context_signature")
    signals = [s for s in dataset.signals if s.signal_id.startswith("b-")][:2]
    signals[1].road_context_id = next(r.road_context_id for r in dataset.roads if r.road_context_id != signals[0].road_context_id)
    dataset.signals = signals
    assert len(run(dataset)) == 2


def test_context_offline_replay_persistence_and_ablation(tmp_path, monkeypatch):
    from tests.test_api import complete
    def blocked(*args, **kwargs): raise AssertionError("Network attempted in offline replay")
    monkeypatch.setattr(socket, "create_connection", blocked)
    original_connect = socket.socket.connect
    def offline_connect(sock, address):
        # Windows asyncio requires a loopback socket pair even for ASGI TestClient.
        if address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        return blocked()
    monkeypatch.setattr(socket.socket, "connect", offline_connect)
    path = tmp_path / "context.sqlite3"
    with TestClient(create_app(path)) as client:
        assert len(client.get("/api/v1/context").json()["roads"]) == 20
        for name in ("context_signature", "context_archive"):
            state = complete(client, name)
            assert state["context_notice"].startswith("Synthetic incident replay on real road geography")
            assert len(state["geography"]["features"]) == 910
            item = next(i for i in state["incidents"] if i["status"] == "candidate")
            assert item["risk"]["display"] == "68"
            rain = item["trace"]["context"]["rainfall"]
            assert rain["provenance"]["content_origin"] == ("synthetic" if name == "context_signature" else "public_source")
            comparison = client.post("/api/v1/demo/compare", json={"add_duplicates": 10}).json()
            assert [(i['risk'], i['hypotheses'], i['independent_capture_count']) for i in comparison['baseline']] == [(i['risk'], i['hypotheses'], i['independent_capture_count']) for i in comparison['incidents']]
            hidden = client.post("/api/v1/demo/compare", json={"disable_families": ["image"]}).json()
            assert next(i for i in hidden["incidents"] if i["status"] == "candidate")["risk"]["display"] == "52–83"
        assert client.get("/api/v1/incidents").json() == state
    with TestClient(create_app(path)) as client:
        assert client.get("/api/v1/incidents").json() == state


def test_frozen_engine_and_config_hashes():
    root = CONTEXT.parents[1]
    assert hashlib.sha256((root / 'backend/app/engine.py').read_bytes().replace(b'\r\n', b'\n')).hexdigest() == '5fe1a4471281bb0355fe45573610ab9679144401821b80c68c6e76394145b17b'
    assert hashlib.sha256((root / 'backend/app/config.py').read_bytes().replace(b'\r\n', b'\n')).hexdigest() == '7d07908512e641c760e5be40c6dfb4e57e9f30d5950206b9a26159b07f252667'


def test_operator_sourced_road_is_validated_before_perception(tmp_path):
    from tests.test_perception import FakeClient, extracted, request
    from backend.app.perception import Settings
    road = load_roads()[0]
    lon, lat = [sum(p[k] for p in road.coordinates) / 2 for k in (0, 1)]
    fake = FakeClient(extracted())
    with TestClient(create_app(tmp_path / "operator.sqlite3", Settings(api_key="test"), fake)) as client:
        match = client.get("/api/v1/context/road-match", params={"lon": lon, "lat": lat, "accuracy_m": 5}).json()
        assert match["road_context_id"] == road.road_context_id
        submitted = client.post("/api/v1/signals", json=request(lon=lon, lat=lat, road_context_id=road.road_context_id))
        assert submitted.status_code == 202
        snapshot = client.get("/api/v1/live/incidents").json()
        assert snapshot["roads"][0]["source"]["provider"] == "OpenStreetMap"
        assert snapshot["incidents"][0]["risk"]["components"]["exposure"] is not None
        assert len(fake.calls) == 1
        wrong = client.post("/api/v1/signals", json=request(idempotency_key="wrong", road_context_id="osm-unknown-0-0"))
        assert wrong.status_code == 422
        assert len(fake.calls) == 1
        assert len(client.get("/api/v1/observations").json()) == 1


def test_operator_image_uses_same_sourced_road_gate(tmp_path):
    from backend.app.perception import Settings
    road = load_roads()[0]
    lon, lat = [sum(p[k] for p in road.coordinates) / 2 for k in (0, 1)]
    metadata = dict(lon=lon, lat=lat, road_context_id=road.road_context_id,
        observed_at=datetime.now(UTC).isoformat(), location_accuracy_m=5, capture_group_id="image-context",
        independence="asserted", operator="test", idempotency_key="image-context", content_origin="synthetic")
    with TestClient(create_app(tmp_path / "image.sqlite3", Settings(api_key=""))) as client:
        result = client.post("/api/v1/images", data={"metadata": json.dumps(metadata)},
            files={"image": ("image.jpg", (CONTEXT.parent / "images/damage-01.jpg").read_bytes(), "image/jpeg")})
        assert result.status_code == 202, result.text
        roads = client.get("/api/v1/live/incidents").json()["roads"]
        assert roads[0]["source"]["provider"] == "OpenStreetMap"


def test_provider_fetch_exact_requests_and_hashes_with_mock_transport(tmp_path):
    import httpx
    from backend.fetch_context import fetch_snapshot
    from backend.app.context import OSM_URL, WEATHER_URL
    seen = []
    def handle(request):
        seen.append(str(request.url))
        return httpx.Response(200, content=read_verified(manifest()["weather" if "open-meteo" in str(request.url) else "roads"]))
    output = tmp_path / "new"
    info = fetch_snapshot(output, httpx.Client(transport=httpx.MockTransport(handle)))
    assert seen == [OSM_URL, WEATHER_URL]
    for key in ("roads", "weather"):
        assert info[key]["raw_sha256"] == manifest()[key]["raw_sha256"]
        assert read_verified(info[key], output)
    with pytest.raises(FileExistsError): fetch_snapshot(output)
