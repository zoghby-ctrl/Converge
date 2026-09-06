"""Hand-authored structured fixtures; no AI and no generated outcome labels."""
import json
import math
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = datetime(2026, 9, 9, 6, tzinfo=timezone.utc)
PROVENANCE = dict(content_origin="synthetic", placement_origin="simulated", time_origin="simulated",
                  source_ref="fixtures/generate.py", author_category="team-authored demo",
                  license="Team-authored synthetic fixture", reviewer="Phase 1 fixture author; not field verification")


def signal(sid, minutes=0, meters=0, family="text", water=True, damage=None, road="road-b", text=None, received=None):
    time = BASE + timedelta(minutes=minutes)
    acquired = BASE + timedelta(minutes=received if received is not None else minutes)
    evidence = []
    for feature, state, value in (("standing_water", water, 0.5), ("visible_road_damage", damage, 0.5)):
        if state is not None:
            evidence.append(dict(evidence_id=sid + "-" + feature, signal_id=sid, feature=feature,
                state="positive" if state else "negative", value=value if state else 0,
                basis="reported" if family == "text" else "visually_suggested",
                span="Hand-authored localized standing-water annotation" if feature == "standing_water" else
                     "Hand-authored visible surface-damage annotation; no actual photograph in Phase 1"))
    return dict(signal_id=sid, dataset_id="signature", idempotency_key=sid, source_record_id=sid,
                source_family=family, capture_group_id="capture-" + sid,
                text=text or f"Synthetic observation {sid}: reviewed local conditions.",
                lat=30.054 + math.degrees(meters / 6371008.8), lon=31.336, location_accuracy_m=5,
                road_context_id=road, observed_at=time.isoformat(), received_at=acquired.isoformat(),
                available_at=acquired.isoformat(), provenance=deepcopy(PROVENANCE), evidence=evidence)


def roads():
    return [dict(road_context_id="road-" + letter, name=f"Location {letter.upper()} · simulated study segment",
                 road_class="primary" if letter == "b" else "local", compatible_ids=[],
                 coordinates=[[31.336, 30.052 + offset], [31.336, 30.056 + offset]], provenance=deepcopy(PROVENANCE))
            for letter, offset in (("a", math.degrees(-450 / 6371008.8)), ("b", 0), ("c", math.degrees(550 / 6371008.8)))]


def dataset(name, signals):
    for s in signals:
        s["dataset_id"] = name
    clocks = sorted({s["available_at"][:13] for s in signals})
    rain = [dict(context_id="rain-" + str(i), end_at=stamp + ":00:00+00:00", available_at=stamp + ":00:00+00:00",
                 hourly_mm=[0, 0, 1, 2, 2, 1], bbox=[31.325, 30.045, 31.346, 30.067], provenance=deepcopy(PROVENANCE))
            for i, stamp in enumerate(clocks)]
    return dict(dataset_id=name, title=name.replace("_", " ").title(), roads=roads(), rainfall=rain, signals=signals)


def build():
    a = signal("a-original", road="road-a", meters=-450, text="المياه متجمعة عند الشارع.")
    copies = []
    for i in range(7):
        s = deepcopy(a)
        sid = f"a-copy-{i}"
        s.update(signal_id=sid, source_record_id=sid, idempotency_key=sid, capture_group_id="copy-" + sid,
                 copy_lineage="a-original", received_at=(BASE + timedelta(minutes=1)).isoformat(),
                 available_at=(BASE + timedelta(minutes=1)).isoformat())
        for e in s["evidence"]:
            e.update(signal_id=sid, evidence_id=sid + "-" + e["feature"])
        copies.append(s)
    b1 = signal("b-water-first", minutes=10, text="في مياه متجمعة جنب الرصيف ومش عارفين سببها.")
    b2 = signal("b-road-image", minutes=20, meters=20, family="image", water=None, damage=True,
                text="Structured image-family fixture: localized broken road surface. No photograph supplied.")
    b3 = signal("b-water-later", minutes=190, meters=10, text="المياه لسه موجودة في نفس المكان في الملاحظة الجديدة.")
    c = signal("c-separate", minutes=195, meters=550, road="road-c", text="Separate synthetic water observation at C.")
    # Road image captured later ensures it remains current to the road feature; no inference of worsening.
    main = [a] + copies + [b1, b2, b3, c]
    cases = {"signature": dataset("signature", main)}
    cases["missing_road_damage"] = dataset("missing_road_damage", [deepcopy(s) for s in main if s["source_family"] != "image"])
    cases["conflicting_water"] = dataset("conflicting_water", [signal("conflict-positive"), signal("conflict-negative", minutes=5, water=False)])
    for label, meters in (("spatial_119m", 119), ("spatial_121m", 121)):
        cases[label] = dataset(label, [signal(label + "-a"), signal(label + "-b", meters=meters)])
    for label, minutes in (("time_5h59", 359), ("time_6h", 360), ("time_over_6h", 361)):
        cases[label] = dataset(label, [signal(label + "-a"), signal(label + "-b", minutes=minutes)])
    cases["chain_guard"] = dataset("chain_guard", [signal("chain-a"), signal("chain-b", meters=80), signal("chain-c", meters=160)])
    cases["road_incompatible"] = dataset("road_incompatible", [signal("parallel-a"), signal("parallel-b", meters=10, road="road-c")])
    return cases


if __name__ == "__main__":
    for name, payload in build().items():
        (Path(__file__).parent / (name + ".json")).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
