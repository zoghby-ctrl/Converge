"""Pure, network-free convergence. Inputs are reviewed observations, never prompts."""
import hashlib
import math
import re
import unicodedata
from datetime import datetime
from itertools import combinations

from .config import HYPOTHESIS_WEIGHTS, RISK_WEIGHTS, RULES
from .models import (CaptureGroup, Contribution, Dataset, FeatureResult,
                     HypothesisResult, Incident, RiskResult, Signal)


def haversine(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    dlat, dlon = b - a, math.radians(lon2 - lon1)
    h = math.sin(dlat / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(dlon / 2) ** 2
    return 6371008.8 * 2 * math.asin(min(1, math.sqrt(h)))


def distance(a, b):
    return haversine(a.lat, a.lon, b.lat, b.lon)


def normalized_hash(text):
    value = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def deduplicate(signals):
    """Union copy/capture lineage before any score. Earliest acquisition owns copies."""
    ordered = sorted(signals, key=lambda s: (s.received_at, s.signal_id))
    parent = {s.signal_id: s.signal_id for s in ordered}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    keys, duplicate_of = {}, {}
    for s in ordered:
        content = s.exact_image_hash if s.source_family == "image" else normalized_hash(s.text or "")
        s.content_hash = content
        tokens = [("capture", s.capture_group_id), ("idempotency", s.idempotency_key),
                  ("source", s.source_family, s.source_record_id)]
        if content and (s.source_family == "image" or s.text):
            tokens.append(("content", s.source_family, content))
        for token in tokens:
            if token in keys:
                old = keys[token]
                parent[root(s.signal_id)] = root(old)
                if token[0] != "capture":
                    duplicate_of[s.signal_id] = old
            else:
                keys[token] = s.signal_id
    grouped = {}
    for s in ordered:
        s.duplicate_of = duplicate_of.get(s.signal_id)
        grouped.setdefault(root(s.signal_id), []).append(s)
    return list(grouped.values())


def compatible(a, b, roads):
    ra, rb = roads.get(a.road_context_id), roads.get(b.road_context_id)
    return bool(ra and rb and (ra.road_context_id == rb.road_context_id or
                (rb.road_context_id in ra.compatible_ids and ra.road_context_id in rb.compatible_ids)))


def pair_reasons(a, b, roads):
    reasons = []
    if distance(a, b) > RULES.max_distance_m + 1e-7:
        reasons.append("membership.distance_120m")
    if abs((a.observed_at - b.observed_at).total_seconds()) > RULES.window_hours * 3600:
        reasons.append("membership.event_window_6h")
    if not compatible(a, b, roads):
        reasons.append("membership.road_compatibility")
    return reasons


def admission(s, clock, roads):
    reasons = []
    age = (clock - s.observed_at).total_seconds()
    if s.available_at > clock:
        reasons.append("admission.not_available")
    if age > RULES.window_hours * 3600:
        reasons.append("admission.stale")
    if age < -RULES.clock_tolerance_minutes * 60:
        reasons.append("admission.future_quarantine")
    if s.location_accuracy_m is None or s.location_accuracy_m > RULES.max_accuracy_m:
        reasons.append("admission.location_quality")
    if s.time_uncertainty_minutes > RULES.max_time_uncertainty_minutes:
        reasons.append("admission.time_quality")
    if s.road_context_id not in roads:
        reasons.append("admission.unreviewed_road")
    if s.independence != "asserted":
        reasons.append("admission.uncertain_independence")
    if not any(e.quality >= RULES.min_quality and e.state != "unknown" and
               e.feature in ("standing_water", "visible_road_damage", "passage_obstruction") for e in s.evidence):
        reasons.append("admission.no_qualifying_condition")
    return reasons


def strength(s, e, clock):
    age = max(0, (clock - s.observed_at).total_seconds() / 3600)
    return e.quality * 2 ** (-age / RULES.window_hours)


def fuse(feature, pairs, clock):
    items = [(s, e) for s, e in pairs if e.feature == feature and
             e.state != "unknown" and e.quality >= RULES.min_quality]
    if not items:
        return FeatureResult(state="unknown", rule_id="fusion.missing_is_unknown")
    latest = max(s.observed_at for s, _ in items)
    current = [(s, e) for s, e in items if (latest - s.observed_at).total_seconds() <= RULES.conflict_minutes * 60]
    states = {e.state for _, e in current}
    ids = [e.evidence_id for _, e in current]
    if len(states) > 1:
        return FeatureResult(state="conflicting", evidence_ids=ids, rule_id="fusion.material_conflict")
    state = next(iter(states))
    values = [e.value for _, e in current if e.value is not None]
    return FeatureResult(state=state, strength=max(strength(s, e, clock) for s, e in current),
                         value=0 if state == "negative" else max(values) if values else None,
                         evidence_ids=ids, rule_id="fusion.current_max_not_sum")


def persistence(pairs, group_of, water, clock):
    positives = [(s, e) for s, e in pairs if e.feature == "standing_water" and
                 e.state == "positive" and e.quality >= RULES.min_quality]
    negatives = [(s, e) for s, e in pairs if e.feature == "standing_water" and
                 e.state == "negative" and e.quality >= RULES.min_quality]
    if water.state == "conflicting":
        return FeatureResult(state="conflicting", evidence_ids=water.evidence_ids, rule_id="persistence.conflicted_water")
    verified = [(s, e) for s, e in pairs if e.feature == "transient_verified" and
                e.state == "positive" and e.field_verified and e.quality >= RULES.min_quality]
    if verified and water.state == "negative":
        return FeatureResult(state="positive", value=0, strength=max(strength(s, e, clock) for s, e in verified),
                             evidence_ids=[e.evidence_id for _, e in verified], rule_id="persistence.field_verified_transient")
    if water.state != "positive":
        return FeatureResult(state="unknown", rule_id="persistence.no_current_water")
    candidates = []
    for (a, ea), (b, eb) in combinations(positives, 2):
        lo, hi = sorted([a.observed_at, b.observed_at])
        hours = (hi - lo).total_seconds() / 3600
        if group_of[a.signal_id] == group_of[b.signal_id] or not 0.5 <= hours <= 6:
            continue
        # A clear negative blocks an endpoint series, including an earlier episode.
        if any(lo <= n.observed_at <= max(hi, water_time(pairs)) for n, _ in negatives):
            continue
        candidates.append((1 if hours >= 2 else 0.5,
                           min(strength(a, ea, clock), strength(b, eb, clock)), [ea.evidence_id, eb.evidence_id]))
    if not candidates:
        return FeatureResult(state="unknown", rule_id="persistence.independent_timed_endpoints_required")
    value, power, ids = max(candidates, key=lambda x: (x[0], x[1], x[2]))
    return FeatureResult(state="positive", value=value, strength=power,
                         evidence_ids=ids, rule_id="persistence.independent_timed_endpoints")


def water_time(pairs):
    return max(s.observed_at for s, e in pairs if e.feature == "standing_water" and e.quality >= RULES.min_quality)


def risk_result(components, refs):
    low = 100 * sum(RISK_WEIGHTS[k] * (v if v is not None else 0) for k, v in components.items())
    high = 100 * sum(RISK_WEIGHTS[k] * (v if v is not None else 1) for k, v in components.items())
    low, high = round(low, 6), round(high, 6)
    band = lambda v: "watch" if v < 35 else "inspect" if v < 65 else "inspect first"
    return RiskResult(risk_min=low, risk_max=high,
                      display=str(math.floor(low + 0.5)) if low == high else f"{math.floor(low)}–{math.ceil(high)}",
                      risk_band=band(low) if band(low) == band(high) else "provisional",
                      provisional=low != high, components=components,
                      known_component_coverage=sum(RISK_WEIGHTS[k] for k, v in components.items() if v is not None),
                      contributions=[Contribution(rule_id=f"risk.{k}", evidence_ids=refs.get(k, []),
                                     strength=v if v is not None else 0, weight=100 * RISK_WEIGHTS[k],
                                     points=round(100 * RISK_WEIGHTS[k] * (v or 0), 6)) for k, v in components.items()],
                      rule_version=RULES.version)


def hypotheses(features, water_supported, rain_known):
    titles = {"H1": "Persistent rainfall-associated ponding / possible drainage limitation" if rain_known else
              "Persistent ponding; rainfall relationship unknown",
              "H2": "Transient surface runoff or short-lived ponding",
              "H3": "Non-rainfall water source such as irrigation, washing, or leakage; subtype unverified"}
    missing_labels = {"P": "Independent timed water observations", "R": "Complete preceding-six-hour rainfall",
                      "C": "Later observation showing recession or resolution", "S": "Field-reviewed identifiable discharge"}
    results = []
    for hid, weights in HYPOTHESIS_WEIGHTS.items():
        contributions = [Contribution(rule_id=f"hypothesis.{hid}.{f}", evidence_ids=ids,
                         strength=x, weight=weights[f], points=round(weights[f] * x, 6))
                         for f, (x, ids) in features.items() if weights[f] != 0]
        results.append(HypothesisResult(hypothesis_id=hid, title=titles[hid],
                       support_points=round(sum(c.points for c in contributions), 6), contributions=contributions,
                       missing_discriminators=[label for f, label in missing_labels.items()
                                               if f not in features and not (f == "R" and rain_known)],
                       tied_or_leading="alternative"))
    results.sort(key=lambda h: (-h.support_points, h.hypothesis_id))
    abstain = not water_supported or results[0].support_points <= 0 or not (set(features) - {"W"})
    top = [h for h in results if results[0].support_points - h.support_points <= RULES.tie_margin]
    for h in results:
        h.tied_with = [other.hypothesis_id for other in results if other != h and
                       abs(h.support_points - other.support_points) <= RULES.tie_margin]
        h.tied_or_leading = "abstained" if abstain else ("leading" if len(top) == 1 else "tied") if h in top else "alternative"
    return results, abstain


def score_cluster(groups, dataset, clock, exclusions):
    roads = {r.road_context_id: r for r in dataset.roads}
    members = [s for group in groups for s in group]
    canonical = [s for s in members if s.duplicate_of is None]
    pairs = [(s, e) for s in canonical for e in s.evidence]
    group_of = {s.signal_id: group[0].capture_group_id for group in groups for s in group}
    captures = [CaptureGroup(capture_group_id=g[0].capture_group_id, signal_ids=[s.signal_id for s in g],
                evidence_ids=[e.evidence_id for s in g if not s.duplicate_of for e in s.evidence]) for g in groups]
    features = {f: fuse(f, pairs, clock) for f in ("standing_water", "visible_road_damage", "passage_obstruction")}
    w, d, o = (features[f] for f in ("standing_water", "visible_road_damage", "passage_obstruction"))
    p = persistence(pairs, group_of, w, clock)
    features["persistence"] = p
    rcontexts = [roads[r] for r in sorted({s.road_context_id for s in canonical})]
    exposure = None if any(r.road_class is None for r in rcontexts) else max(
        0 if r.road_class == "service" else 0.5 if r.road_class == "local" else 1 for r in rcontexts)
    features["road_exposure"] = FeatureResult(state="unknown" if exposure is None else "positive", value=exposure,
                                             evidence_ids=[r.road_context_id for r in rcontexts], rule_id="context.reviewed_road_class")
    valid_rain = [r for r in dataset.rainfall if r.available_at <= clock and r.end_at == clock.replace(minute=0, second=0, microsecond=0)
                  and all(v is not None for v in r.hourly_mm) and all(r.bbox[0] <= s.lon <= r.bbox[2] and
                      r.bbox[1] <= s.lat <= r.bbox[3] for s in canonical)]
    rain = sorted(valid_rain, key=lambda r: r.context_id)[0] if valid_rain else None
    features["rainfall_context"] = FeatureResult(state="positive" if rain else "unknown", strength=0.6 if rain else 0,
                                 value=sum(rain.hourly_mm) if rain else None, evidence_ids=[rain.context_id] if rain else [],
                                 rule_id="context.complete_preceding_6h")
    x = {}
    for key, f in (("W", w), ("D", d)):
        if f.state == "positive":
            x[key] = (f.strength, f.evidence_ids)
    if p.state == "positive" and p.value == 1:
        x["P"] = (p.strength, p.evidence_ids)
    if rain:
        total = sum(rain.hourly_mm)
        if total >= 5 or total <= 0.2:
            x["R" if total >= 5 else "N"] = (0.6, [rain.context_id])
    earlier = [(s, e) for s, e in pairs if e.feature == "standing_water" and e.state == "positive" and e.quality >= 0.5]
    if w.state == "negative" and earlier and any((water_time(pairs) - s.observed_at).total_seconds() > RULES.conflict_minutes * 60 for s, _ in earlier):
        x["C"] = (w.strength, w.evidence_ids + [e.evidence_id for _, e in earlier])
        x.pop("P", None)
    discharge = [(s, e) for s, e in pairs if e.feature == "non_rainfall_discharge" and e.state == "positive" and e.field_verified and e.quality >= 0.5]
    if discharge:
        x["S"] = (max(strength(s, e, clock) for s, e in discharge), [e.evidence_id for _, e in discharge])
    h, abstain = hypotheses(x, w.state == "positive", rain is not None)
    conflicts = [f for f, result in features.items() if result.state == "conflicting"]
    components = {"water_extent": w.value if w.state not in ("unknown", "conflicting") else None,
                  "road_condition": d.value if d.state not in ("unknown", "conflicting") else None,
                  "persistence": p.value if p.state == "positive" else None, "exposure": exposure}
    if o.state == "conflicting":
        # The generic obstruction tag cannot distinguish water versus road impact.
        components["water_extent"] = components["road_condition"] = None
    refs = {"water_extent": w.evidence_ids, "road_condition": d.evidence_ids,
            "persistence": p.evidence_ids, "exposure": [r.road_context_id for r in rcontexts]}
    risk = risk_result(components, refs)
    families = {s.source_family for s in canonical if any(e.quality >= 0.5 and e.state != "unknown" for e in s.evidence)}
    tier = "Limited"
    if len(groups) >= 2 and families == {"text", "image"} and not conflicts:
        tier = "Moderate"
        if len(groups) >= 3 and p.value is not None and any(e.field_verified and e.quality >= 0.5 for _, e in pairs):
            tier = "Strong corroboration"
    status = "candidate" if len(groups) >= 2 and earlier else "watch"
    medoid = min(canonical, key=lambda a: (sum(distance(a, b) for b in canonical), a.signal_id))
    max_dist = max((distance(a, b) for a, b in combinations(canonical, 2)), default=0)
    checks = [
        {"rule_id": "inspection.water_extent", "text": "Verify current standing water and passage obstruction.", "evidence_ids": w.evidence_ids},
        {"rule_id": "inspection.road_condition", "text": "Document the visible road surface; do not infer hidden depth or water-caused damage.", "evidence_ids": d.evidence_ids},
        {"rule_id": "inspection.discriminate_source", "text": "If safe, inspect drainage access and look for an identifiable non-rainfall water source.", "evidence_ids": list(dict.fromkeys(w.evidence_ids + features["rainfall_context"].evidence_ids))},
        {"rule_id": "inspection.repeat_observation", "text": "Record a new timed observation to distinguish persistence from transient ponding.", "evidence_ids": p.evidence_ids},
    ]
    trace = {"member_evidence": [e.model_dump(mode="json") for _, e in pairs],
             "membership_reasons": [{"signal_id": s.signal_id, "capture_group_id": group_of[s.signal_id],
                 "rule_ids": ["membership.all_pairs_120m", "membership.event_window_6h", "membership.road_compatibility", "admission.reviewed_metadata"],
                 "duplicate_of": s.duplicate_of} for s in members],
             "excluded_evidence": exclusions + [{"signal_id": s.signal_id, "evidence_id": e.evidence_id,
                 "rule_ids": ["admission.evidence_quality_or_unknown"]} for s, e in pairs if e.quality < 0.5 or e.state == "unknown"],
             "missing_fields": [f for f, v in features.items() if v.state == "unknown"] +
                               [k for k, v in components.items() if v is None and k not in features],
             "conflicts": conflicts, "inspection_checks": checks,
             "clock_skew_signal_ids": [s.signal_id for s in canonical if s.observed_at > clock],
             "urgent_human_review": o.state == "positive" and o.value == 1,
             "formation_rule": "formation.two_independent_groups_and_water" if status == "candidate" else "formation.watch",
             "evidence_strength_rule": "evidence_strength." + tier.lower().replace(" ", "_"),
             "context": {"roads": [r.model_dump(mode="json") for r in rcontexts], "rainfall": rain.model_dump(mode="json") if rain else None},
             "limitations": ["Working interpretations are not root-cause diagnoses.", "Road damage may pre-date the water.",
                            "Capture independence is asserted provenance, not authenticated identity."]}
    return Incident(incident_id="incident-" + min(s.signal_id for s in canonical), dataset_id=dataset.dataset_id,
                    config_version=RULES.version, status=status, tag="water + road condition" if w.state == d.state == "positive" else
                    "water observation" if earlier else "road / obstruction observation",
                    road_name=" / ".join(r.name for r in rcontexts), lat=medoid.lat, lon=medoid.lon,
                    max_pair_distance_m=round(max_dist, 3), first_observed_at=min(s.observed_at for s in canonical),
                    last_observed_at=max(s.observed_at for s in canonical), computed_as_of=clock,
                    signal_ids=[s.signal_id for s in members], capture_groups=captures,
                    independent_capture_count=len(groups), features=features, hypotheses=h, hypothesis_abstention=abstain,
                    risk=risk, evidence_strength=tier, trace=trace)


def run_engine(dataset: Dataset, clock: datetime, disabled_families=()):
    dataset = dataset.model_copy(deep=True)
    roads = {r.road_context_id: r for r in dataset.roads}
    available = [s for s in dataset.signals if s.available_at <= clock and s.source_family not in disabled_families]
    if len(available) > 500:
        raise ValueError("Phase 1 supports at most 500 available observation records")
    groups, excluded = [], []
    for group in deduplicate(available):
        reasons = set()
        canonical = [s for s in group if not s.duplicate_of]
        has_condition = False
        for s in canonical:
            signal_reasons = admission(s, clock, roads)
            has_condition |= "admission.no_qualifying_condition" not in signal_reasons
            reasons.update(r for r in signal_reasons if r != "admission.no_qualifying_condition")
        if not has_condition:
            reasons.add("admission.no_qualifying_condition")
        # Copied photos/text with inconsistent claimed capture metadata are quarantined.
        for a, b in combinations(group, 2):
            if pair_reasons(a, b, roads):
                reasons.add("admission.capture_metadata_inconsistent")
        if reasons:
            excluded.extend({"signal_id": s.signal_id, "evidence_ids": [e.evidence_id for e in s.evidence], "rule_ids": sorted(reasons)} for s in group)
        else:
            groups.append(group)
    groups.sort(key=lambda g: (min(s.observed_at for s in g if not s.duplicate_of), g[0].signal_id))
    clusters = []
    for group in groups:
        representatives = [s for s in group if not s.duplicate_of]
        choices = []
        for i, cluster in enumerate(clusters):
            others = [s for g in cluster for s in g if not s.duplicate_of]
            if all(not pair_reasons(a, b, roads) for a in representatives for b in others):
                diameter = max((distance(a, b) for a, b in combinations(representatives + others, 2)), default=0)
                choices.append((diameter, cluster[0][0].signal_id, i))
        if choices:
            clusters[min(choices)[2]].append(group)
        else:
            clusters.append([group])
    incidents = []
    for cluster in clusters:
        members = [s for g in cluster for s in g if not s.duplicate_of]
        other_exclusions = []
        for group in groups:
            if group not in cluster:
                for s in group:
                    reasons = sorted({r for a in members for r in pair_reasons(a, s, roads)})
                    other_exclusions.append({"signal_id": s.signal_id, "rule_ids": reasons or ["membership.deterministic_partition"]})
        incidents.append(score_cluster(cluster, dataset, clock, excluded + other_exclusions))
    incidents.sort(key=lambda i: (i.status != "candidate", not i.trace["urgent_human_review"], -i.risk.risk_min,
                                 -i.last_observed_at.timestamp(), i.incident_id))
    return incidents, excluded, available
