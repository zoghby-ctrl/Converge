"""Bounded public context adapters. No network at import, replay, or scoring time."""
import gzip
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .engine import haversine
from .models import ContextSource, Provenance, RainContext, RoadContext

ROOT = Path(__file__).resolve().parents[2]
CONTEXT = ROOT / "fixtures" / "context"
BBOX = (31.325, 30.045, 31.346, 30.063)
WEATHER_URL = "https://archive-api.open-meteo.com/v1/archive?latitude=30.054&longitude=31.3355&start_date=2025-01-01&end_date=2025-01-02&hourly=rain&models=era5&timezone=GMT"
OSM_URL = "https://api.openstreetmap.org/api/0.6/map?bbox=31.325,30.045,31.346,30.063"


def read_verified(entry, directory=CONTEXT):
    path = directory / entry["raw_ref"]
    try:
        raw = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    except EOFError:
        raise ValueError("Truncated compressed context cache") from None
    if hashlib.sha256(raw).hexdigest() != entry["raw_sha256"]:
        raise ValueError("Context cache integrity mismatch")
    return raw


def manifest():
    return json.loads((CONTEXT / "manifest.json").read_text(encoding="utf-8"))


def distance_to_line(lon, lat, coordinates):
    """Local tangent-plane distance, meters; bounded to the ~2 km demo extent."""
    scale_x, scale_y = 111195.0802 * math.cos(math.radians(lat)), 111195.0802
    best = math.inf
    for a, b in zip(coordinates, coordinates[1:]):
        ax, ay = (a[0] - lon) * scale_x, (a[1] - lat) * scale_y
        bx, by = (b[0] - lon) * scale_x, (b[1] - lat) * scale_y
        dx, dy = bx - ax, by - ay
        fraction = max(0, min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy))) if dx or dy else 0
        best = min(best, math.hypot(ax + fraction * dx, ay + fraction * dy))
    return best


def load_roads():
    info = manifest()
    # Verify the derived catalog as well as its unmodified source bytes.
    read_verified(info["roads"])
    raw = read_verified(info["catalog"])
    return [RoadContext.model_validate(r) for r in json.loads(raw)]


def geography():
    return json.loads(read_verified(manifest()["geography"]))


def assign_road(lon, lat, accuracy_m, roads=None, background=None):
    """30 m nearest gate; incompatible competitor within nearest+10 m abstains.

    Unreviewed map ways also compete, so a partial reviewed catalog cannot hide
    a nearby parallel carriageway, crossing or bridge. No topology is inferred.
    """
    if not (math.isfinite(lon) and math.isfinite(lat) and BBOX[0] <= lon <= BBOX[2]
            and BBOX[1] <= lat <= BBOX[3]):
        return {"road_context_id": None, "reason": "outside_study_extent"}
    if accuracy_m is None or not math.isfinite(accuracy_m) or not 0 <= accuracy_m <= 50:
        return {"road_context_id": None, "reason": "location_quality"}
    roads = load_roads() if roads is None else roads
    background = geography() if background is None else background
    distances = sorted((distance_to_line(lon, lat, r.coordinates), r.road_context_id, r) for r in roads)
    if not distances or distances[0][0] > 30 + 1e-7:
        return {"road_context_id": None, "reason": "no_reviewed_segment_within_30m"}
    nearest, _, chosen = distances[0]
    for distance, _, other in distances[1:]:
        mutual = other.road_context_id in chosen.compatible_ids and chosen.road_context_id in other.compatible_ids
        if distance <= nearest + 10 + 1e-7 and not mutual:
            return {"road_context_id": None, "reason": "ambiguous_incompatible_segment"}
    way_id = chosen.road_context_id.split("-")[1]
    for feature in background["features"]:
        if str(feature["properties"]["osm_way_id"]) != way_id and distance_to_line(
                lon, lat, feature["geometry"]["coordinates"]) <= nearest + 10 + 1e-7:
            return {"road_context_id": None, "reason": "ambiguous_mapped_way"}
    return {"road_context_id": chosen.road_context_id, "reason": "bounded_nearest_segment", "distance_m": round(nearest, 3)}


def attach_operator_road(dataset, signal):
    """Only explicit OSM IDs opt in; prior operator-asserted road behavior stays intact."""
    if not (signal.road_context_id or "").startswith("osm-"):
        return False
    from fastapi import HTTPException
    try:
        roads = load_roads()
        match = assign_road(signal.lon, signal.lat, signal.location_accuracy_m, roads)
    except (OSError, ValueError):
        raise HTTPException(422, "Road context unavailable; use a reviewed manual segment") from None
    if match["road_context_id"] != signal.road_context_id:
        raise HTTPException(422, "OSM road assignment requires review: " + match["reason"])
    if not any(r.road_context_id == signal.road_context_id for r in dataset.roads):
        dataset.roads.append(next(r for r in roads if r.road_context_id == signal.road_context_id))
    return True


def rainfall_from_response(raw, source, end_at, *, retrospective_demo=False):
    """Normalize ERA5 rain into the frozen six-completed-hour contract.

    Provider timestamps label interval ENDS. For 12:xx, use 07..12, not 06..11.
    Bad schema/units/duplicates reject the context; absent hours remain None.
    Acquisition is the earliest *known* availability, never historical as-issued.
    Only explicitly retrospective synthetic replay can relax that availability.
    """
    if end_at.tzinfo is None:
        raise ValueError("Context clock must be timezone aware")
    if hashlib.sha256(raw).hexdigest() != source.raw_sha256:
        raise ValueError("Weather cache integrity mismatch")
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("hourly"), dict):
        raise ValueError("Invalid weather response structure")
    if data.get("utc_offset_seconds") != 0 or data.get("hourly_units") != {"time": "iso8601", "rain": "mm"}:
        raise ValueError("Expected UTC hourly liquid rain in mm")
    if source.provider != "Open-Meteo" or source.product != "ERA5" or source.resolution_degrees != 0.25:
        raise ValueError("Unsupported weather product")
    center = (data["longitude"], data["latitude"])
    if center != source.grid_center:
        raise ValueError("Weather grid identity mismatch")
    if not all(math.isfinite(v) for v in center) or haversine(center[1], center[0], 30.054, 31.3355) > 25000:
        raise ValueError("Weather grid outside supported area")
    times, values = data["hourly"]["time"], data["hourly"]["rain"]
    if not isinstance(times, list) or not isinstance(values, list) or len(times) != len(values) or len(times) > 744:
        raise ValueError("Invalid or oversized weather series")
    series = {}
    for timestamp, value in zip(times, values):
        instant = datetime.fromisoformat(timestamp)
        if instant.tzinfo is not None or instant.minute or instant.second or instant.microsecond:
            raise ValueError("Expected whole-hour GMT provider timestamps")
        instant = instant.replace(tzinfo=timezone.utc)
        if instant in series:
            raise ValueError("Duplicate weather hour")
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError("Invalid rainfall value")
        series[instant] = value
    end = end_at.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    ends = [end - timedelta(hours=n) for n in range(5, -1, -1)]
    source = source.model_copy(update={"interval_ends": ends,
        "application": "retrospective_demo" if retrospective_demo else "original"})
    return RainContext(context_id="open-meteo-era5-" + end.strftime("%Y%m%dT%H") + "-" + source.raw_sha256[:12],
        end_at=end, available_at=end if retrospective_demo else max(end, source.acquired_at),
        hourly_mm=[series.get(t) for t in ends], bbox=BBOX, source=source,
        provenance=Provenance(content_origin="public_source", placement_origin="original", time_origin="original",
            source_ref=source.request_url, author_category="Open-Meteo / Copernicus ECMWF ERA5 reanalysis",
            license="CC BY 4.0; Open-Meteo free API non-commercial terms",
            reviewer="Phase 3 adapter; modeled grid context, not a gauge or field verification"))


def cached_rainfall(end_at, *, retrospective_demo=False):
    """Failures are explicit unknown context, not dry weather or synthetic fallback."""
    try:
        entry = manifest()["weather"]
        source = ContextSource.model_validate(entry["source"])
        context = rainfall_from_response(read_verified(entry), source, end_at, retrospective_demo=retrospective_demo)
        if any(v is None for v in context.hourly_mm):
            return context, "missing_hours"
        if context.available_at > end_at:
            return context, "not_available_at_analysis_clock"
        return context, "complete_retrospective" if retrospective_demo else "complete"
    except (OSError, ValueError, KeyError, TypeError):
        return None, "cache_unavailable_or_invalid"


def load_context_demo(name):
    from .models import Dataset
    dataset = Dataset.model_validate_json((CONTEXT / (name + ".json")).read_text(encoding="utf-8"))
    dataset.roads = load_roads()
    if name == "context_archive":
        dataset.rainfall = []
        for end in sorted({s.available_at.replace(minute=0, second=0, microsecond=0) for s in dataset.signals}):
            rain, _ = cached_rainfall(end, retrospective_demo=True)
            if rain is not None:
                dataset.rainfall.append(rain)
    return dataset
