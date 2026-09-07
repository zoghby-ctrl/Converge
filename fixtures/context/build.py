"""Rebuild derived offline assets from authentic, hash-locked provider responses.

No network and no AI. Raw responses are acquired separately; this does not refresh
them or claim to review changes in the real road network.
"""
import gzip
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone

from backend.app.context import CONTEXT, BBOX, assign_road
from backend.app.engine import haversine
from backend.app.models import ContextSource, Dataset, Provenance, RoadContext


def save(name, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (CONTEXT / name).write_bytes(raw)
    return {"raw_ref": name, "raw_sha256": hashlib.sha256(raw).hexdigest()}


def build():
    info = json.loads((CONTEXT / "manifest.json").read_text(encoding="utf-8"))
    raw = gzip.decompress((CONTEXT / info["roads"]["raw_ref"]).read_bytes())
    assert hashlib.sha256(raw).hexdigest() == info["roads"]["raw_sha256"]
    root = ET.fromstring(raw)
    nodes = {n.attrib["id"]: (float(n.attrib["lon"]), float(n.attrib["lat"])) for n in root.findall("node")}
    features, candidates = [], []
    for way in root.findall("way"):
        tags = {t.attrib["k"]: t.attrib["v"] for t in way.findall("tag")}
        if "highway" not in tags:
            continue
        coords = [nodes[n.attrib["ref"]] for n in way.findall("nd")]
        if len(coords) < 2:
            continue
        wid = way.attrib["id"]
        features.append({"type": "Feature", "properties": {"osm_way_id": wid, "name": tags.get("name:en", tags.get("name", "Unnamed mapped way")),
            "highway": tags["highway"], "layer": tags.get("layer", "0"), "bridge": tags.get("bridge", "no"),
            "tunnel": tags.get("tunnel", "no")}, "geometry": {"type": "LineString", "coordinates": coords}})
        road_class = {"residential": "local", "living_street": "local", "primary": "primary",
            "secondary": "secondary", "tertiary": "tertiary"}.get(tags["highway"])
        # Service does not imply restricted access; leave it out of reviewed exposure.
        if road_class is None or tags.get("layer", "0") != "0" or tags.get("bridge", "no") != "no" or tags.get("tunnel", "no") != "no":
            continue
        for edge, (a, b) in enumerate(zip(coords, coords[1:])):
            if not all(BBOX[0] <= p[0] <= BBOX[2] and BBOX[1] <= p[1] <= BBOX[3] for p in (a, b)):
                continue
            length = haversine(a[1], a[0], b[1], b[0])
            pieces = max(1, math.ceil(length / 110))
            if length / pieces < 50:
                continue
            for piece in range(pieces):
                points = [tuple(a[k] + (b[k] - a[k]) * f for k in (0, 1)) for f in (piece / pieces, (piece + 1) / pieces)]
                source = ContextSource.model_validate(info["roads"]["source"])
                road = RoadContext(road_context_id=f"osm-{wid}-{edge}-{piece}", name=tags.get("name:en", tags.get("name", "Unnamed mapped street")),
                    coordinates=points, road_class=road_class, compatible_ids=[], source=source,
                    provenance=Provenance(content_origin="public_source", placement_origin="original", time_origin="original",
                        source_ref=f"https://www.openstreetmap.org/way/{wid}", author_category="OpenStreetMap contributors",
                        license="Open Database License (ODbL) 1.0", reviewer="Phase 3 source-geometry/code review; no independent human or field review"))
                candidates.append(road)
    background = {"type": "FeatureCollection", "features": features}
    def center(r):
        return tuple(sum(p[k] for p in r.coordinates) / 2 for k in (0, 1))
    candidates.sort(key=lambda r: (haversine(center(r)[1], center(r)[0], 30.054, 31.3355), r.road_context_id))
    counts, reviewed = Counter(), []
    for road in candidates:
        wid = road.road_context_id.split("-")[1]
        if counts[wid] >= 3:
            continue
        lon, lat = center(road)
        if assign_road(lon, lat, 5, candidates, background)["road_context_id"] != road.road_context_id:
            continue
        reviewed.append(road)
        counts[wid] += 1
        if len(reviewed) == 20:
            break
    assert len(reviewed) == 20
    info["catalog"] = save("roads.json", [r.model_dump(mode="json") for r in reviewed])
    info["geography"] = save("roads.geojson", background)
    info["review"] = {"method": "Conservative source-geometry/code review, no human field verification", "segments": 20,
        "max_segment_length_m": 110, "compatible_pairs": [], "notes": "Same short section only. Cross-segment matches abstain; all source highway ways compete during pin assignment. No routing, barrier inference, or drainage connectivity."}
    base = Dataset.model_validate_json((CONTEXT.parent / "signature_image.json").read_text(encoding="utf-8"))
    b = next(r for r in reviewed if r.road_class in ("primary", "secondary", "tertiary"))
    remote = [r for r in reviewed if haversine(center(r)[1], center(r)[0], center(b)[1], center(b)[0]) > 200]
    a = remote[0]
    c = next(r for r in remote if haversine(center(r)[1], center(r)[0], center(a)[1], center(a)[0]) > 120)
    info["demo_placement"] = {"a": a.road_context_id, "b": b.road_context_id, "c": c.road_context_id,
        "notes": "All observations deliberately placed at segment midpoints; public image location/time are simulated. No real event is claimed."}
    origin = min(s.observed_at for s in base.signals)
    for name in ("context_signature", "context_archive"):
        dataset = base.model_copy(deep=True)
        dataset.dataset_id = name
        dataset.title = "Synthetic incident replay on real road geography" + (" / authentic retrospective ERA5 context" if name == "context_archive" else " / synthetic rainfall")
        dataset.roads = []  # Loaded through the integrity-checked adapter at replay reset.
        for signal in dataset.signals:
            road = {"a": a, "b": b, "c": c}[signal.signal_id[0]]
            signal.lon, signal.lat = center(road)
            signal.road_context_id = road.road_context_id
            signal.dataset_id = name
            signal.location_method = "synthetic placement on sourced OSM short section; not original image location"
            if name == "context_archive":
                delta = datetime(2025, 1, 1, 8, tzinfo=timezone.utc) - origin
                for field in ("observed_at", "received_at", "available_at"):
                    setattr(signal, field, getattr(signal, field) + delta)
        if name == "context_archive":
            dataset.rainfall = []  # Authentic cache is normalized at replay reset, with explicit retrospective availability.
        save(name + ".json", dataset.model_dump(mode="json"))
    save("manifest.json", info)
    print(json.dumps({"map_ways": len(features), "reviewed_segments": len(reviewed), "placement": info["demo_placement"]}, indent=2))


if __name__ == "__main__":
    build()
