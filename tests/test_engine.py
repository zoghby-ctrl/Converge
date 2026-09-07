from copy import deepcopy
from datetime import timedelta

import pytest
from pydantic import ValidationError

from backend.app.engine import (deduplicate, haversine, hypotheses, risk_result, run_engine)
from backend.app.models import Dataset, Signal
from fixtures.generate import BASE, build, dataset, signal


def run(payload, clock=None, disabled=()):
    data = Dataset.model_validate(payload)
    return run_engine(data, clock or max(s.available_at for s in data.signals), disabled)


def b_incident(items):
    return next(i for i in items if any(s.startswith('b-water') for s in i.signal_ids))


def test_haversine_known_equatorial_degree_and_symmetry():
    assert haversine(0, 0, 0, 1) == pytest.approx(111195.0802, abs=0.001)
    assert haversine(30, 31, 30.001, 31.002) == haversine(30.001, 31.002, 30, 31)
    assert haversine(30, 31, 30, 31) == 0


@pytest.mark.parametrize('name,counts', [('spatial_119m', [2]), ('spatial_121m', [1, 1]),
    ('time_5h59', [2]), ('time_6h', [2]), ('time_over_6h', [1]), ('road_incompatible', [1, 1]), ('chain_guard', [1, 2])])
def test_frozen_membership_boundaries(name, counts):
    items, excluded, _ = run(build()[name])
    assert sorted(i.independent_capture_count for i in items) == counts
    assert all(i.max_pair_distance_m <= 120 for i in items)
    if name == 'time_over_6h':
        assert any('admission.stale' in e['rule_ids'] for e in excluded)


def test_exact_spatial_boundary_is_inclusive():
    items, _, _ = run(dataset('boundary', [signal('edge-a'), signal('edge-b', meters=120)]))
    assert len(items) == 1
    assert items[0].independent_capture_count == 2


def test_signature_candidate_and_duplicate_invariance():
    payload = build()['signature']
    items, _, _ = run(payload)
    a = next(i for i in items if 'a-original' in i.signal_ids)
    assert a.status == 'watch' and a.independent_capture_count == 1 and len(a.signal_ids) == 8
    b = b_incident(items)
    assert (b.status, b.tag, b.independent_capture_count, b.evidence_strength) == ('candidate', 'water + road condition', 3, 'Moderate')
    assert b.risk.risk_min == b.risk.risk_max == 67.5
    assert b.risk.display == '68'
    # Strip seven copies at the same fixed analysis clock.
    payload['signals'] = [s for s in payload['signals'] if not s['signal_id'].startswith('a-copy')]
    clean, _, _ = run(payload)
    clean_a = next(i for i in clean if 'a-original' in i.signal_ids)
    assert clean_a.risk == a.risk
    assert clean_a.hypotheses == a.hypotheses


def test_image_signature_preserves_frozen_signature_outcomes():
    payload = build()['signature_image']
    items, _, _ = run(payload)
    image = next(item for item in payload['signals'] if item['signal_id'] == 'b-road-image')
    b = b_incident(items)
    assert payload['mode'] == 'cached_extraction'
    assert image['image_path'] == 'fixtures/images/damage-01.jpg'
    assert image['provenance']['annotation_method'] == 'ai_image'
    assert (b.status, b.risk.display, b.evidence_strength,
            b.independent_capture_count) == ('candidate', '68', 'Moderate', 3)
    without_image = b_incident(run(payload, disabled=['image'])[0])
    assert (without_image.risk.display, without_image.evidence_strength,
            without_image.independent_capture_count) == ('52–83', 'Limited', 2)


def test_ten_copies_cannot_refresh_features_or_inflate_score():
    payload = dataset('dup', [signal('original'), signal('independent', minutes=180)])
    base, _, _ = run(payload)
    for n in range(10):
        copy = signal(f'zz-copy-{n}', minutes=0, received=180, text=payload['signals'][0]['text'])
        copy['dataset_id'] = 'dup'
        payload['signals'].append(copy)
    changed, _, _ = run(payload)
    assert changed[0].independent_capture_count == 2
    assert changed[0].risk == base[0].risk
    assert changed[0].hypotheses == base[0].hypotheses


def test_same_capture_multimodal_and_exact_image_reuse_count_once():
    text, photo = signal('text'), signal('photo', family='image', damage=True)
    photo['capture_group_id'] = text['capture_group_id']
    photo['exact_image_hash'] = 'a' * 64
    copied_photo = deepcopy(photo)
    copied_photo.update(signal_id='reuse', source_record_id='reuse', idempotency_key='reuse', capture_group_id='new-account')
    for e in copied_photo['evidence']:
        e.update(signal_id='reuse', evidence_id='reuse-' + e['feature'])
    items, _, _ = run(dataset('capture', [text, photo, copied_photo]))
    assert items[0].independent_capture_count == 1
    assert items[0].status == 'watch' and items[0].evidence_strength == 'Limited'
    assert len(items[0].trace['member_evidence']) == 3


def test_idempotency_key_collapses_repeated_submission_in_engine():
    first, second = signal('first'), signal('second')
    second['idempotency_key'] = first['idempotency_key']
    assert len(deduplicate([Signal.model_validate(first), Signal.model_validate(second)])) == 1


def test_inconsistent_capture_metadata_quarantines_reused_image():
    a, b = signal('photo-a', family='image'), signal('photo-b', family='image', meters=200)
    a['exact_image_hash'] = b['exact_image_hash'] = 'c' * 64
    items, excluded, _ = run(dataset('bad-copy', [a, b]))
    assert not items and len(excluded) == 2
    assert 'admission.capture_metadata_inconsistent' in excluded[0]['rule_ids']


def test_low_quality_attachment_does_not_overturn_eligible_capture():
    text, photo = signal('clear-report'), signal('poor-photo', family='image', water=False)
    photo['capture_group_id'] = text['capture_group_id']
    photo['evidence'][0]['quality'] = 0.4
    i = run(dataset('limited-attachment', [text, photo]))[0][0]
    assert i.independent_capture_count == 1
    assert i.features['standing_water'].state == 'positive'
    assert i.evidence_strength == 'Limited'
    assert any(e.get('evidence_id') == 'poor-photo-standing_water' for e in i.trace['excluded_evidence'])


def test_image_ablation_reruns_fusion_and_widens_unknown_road_risk():
    full, _, _ = run(build()['signature'])
    ablated, _, _ = run(build()['signature'], disabled=['image'])
    before, after = b_incident(full), b_incident(ablated)
    assert before.risk.components['road_condition'] == 0.5
    assert after.risk.components['road_condition'] is None
    assert after.features['visible_road_damage'].state == 'unknown'
    assert (after.risk.risk_min, after.risk.risk_max, after.risk.display) == (52.5, 82.5, '52–83')
    assert after.evidence_strength == 'Limited'
    assert after.independent_capture_count == 2


def test_candidate_gates_context_only_no_water_and_low_quality():
    context_only = dataset('context', [])
    assert run(context_only, BASE)[0] == []
    damage = dataset('damage', [signal('d1', water=None, damage=True), signal('d2', water=None, damage=True)])
    assert run(damage)[0][0].status == 'watch'
    poor = signal('poor')
    poor['evidence'][0]['quality'] = 0.4
    items, excluded, _ = run(dataset('poor', [signal('good'), poor]))
    assert items[0].status == 'watch' and len(excluded) == 1


def test_risk_arithmetic_ranges_and_unrounded_band():
    known = risk_result(dict(water_extent=.5, road_condition=.5, persistence=1, exposure=1), {})
    assert known.risk_min == known.risk_max == 67.5 and known.risk_band == 'inspect first'
    missing = risk_result(dict(water_extent=None, road_condition=None, persistence=None, exposure=None), {})
    assert (missing.risk_min, missing.risk_max, missing.known_component_coverage) == (0, 100, 0)
    assert missing.risk_band == 'provisional'
    partial = risk_result(dict(water_extent=.5, road_condition=None, persistence=1, exposure=1), {})
    assert partial.known_component_coverage == pytest.approx(.7)
    assert partial.risk_max - partial.risk_min == 30


def test_material_water_conflict_abstains_and_widens_risk():
    items, _, _ = run(build()['conflicting_water'])
    i = items[0]
    assert i.features['standing_water'].state == 'conflicting'
    assert i.risk.components['water_extent'] is None
    assert i.risk.components['persistence'] is None
    assert i.evidence_strength == 'Limited' and i.hypothesis_abstention
    assert len(i.features['standing_water'].evidence_ids) == 2


def test_later_resolution_is_temporal_update_and_blocks_persistence():
    payload = dataset('resolution', [signal('w-first'), signal('w-repeat', minutes=150), signal('w-clear', minutes=200, water=False)])
    i = run(payload)[0][0]
    assert i.features['standing_water'].state == 'negative'
    assert i.features['persistence'].value is None
    assert i.risk.components['water_extent'] == 0
    rules = [c.rule_id for h in i.hypotheses for c in h.contributions]
    assert any(r.endswith('.C') for r in rules) and not any(r.endswith('.P') for r in rules)
    assert i.hypothesis_abstention


def test_intervening_negative_blocks_derived_persistence():
    payload = dataset('interruption', [signal('first'), signal('dry', minutes=60, water=False), signal('later', minutes=180)])
    assert run(payload)[0][0].features['persistence'].state == 'unknown'


@pytest.mark.parametrize('minutes,value', [(29, None), (30, .5), (119, .5), (120, 1)])
def test_persistence_requires_independent_timed_endpoints(minutes, value):
    i = run(dataset('duration', [signal('start'), signal('end', minutes=minutes)]))[0][0]
    assert i.risk.components['persistence'] == value


def test_reported_duration_does_not_establish_derived_duration():
    s = signal('claim')
    s['evidence'].append(dict(evidence_id='duration', signal_id='claim', feature='reported_duration', state='positive',
                              value=1, basis='reported', span='It has been here for hours'))
    i = run(dataset('reported', [s]))[0][0]
    assert i.risk.components['persistence'] is None


def test_hypothesis_frozen_arithmetic_and_alternative_ties():
    features = {k: (v, [k]) for k, v in dict(W=.9, D=.7, P=.7, R=.6).items()}
    results, abstain = hypotheses(features, True, True)
    assert not abstain
    assert {h.hypothesis_id: h.support_points for h in results} == {'H1': 5.1, 'H2': 1.6, 'H3': 1.9}
    assert results[0].tied_or_leading == 'leading'
    assert results[1].tied_with == ['H2']
    results, _ = hypotheses({k: v for k, v in features.items() if k != 'R'}, True, False)
    assert {h.hypothesis_id: h.support_points for h in results} == {'H1': 3.9, 'H2': .4, 'H3': 2.5}
    assert 'relationship unknown' in next(h.title for h in results if h.hypothesis_id == 'H1')


def test_hypothesis_abstention_and_top_tie():
    common, abstain = hypotheses({'W': (.9, ['water'])}, True, False)
    assert abstain and all(h.tied_or_leading == 'abstained' for h in common)
    tied, abstain = hypotheses({'W': (.9, ['water']), 'R': (.6, ['rain'])}, True, True)
    assert not abstain
    assert {h.hypothesis_id for h in tied if h.tied_or_leading == 'tied'} == {'H1', 'H2'}
    assert hypotheses({'N': (.6, ['rain'])}, False, True)[1]


def test_missing_incomplete_and_dry_rain_are_distinct_and_do_not_change_risk():
    payload = build()['signature']
    full = b_incident(run(payload)[0])
    for rain in payload['rainfall']:
        rain['hourly_mm'][0] = None
    incomplete = b_incident(run(payload)[0])
    assert incomplete.features['rainfall_context'].state == 'unknown'
    assert incomplete.risk == full.risk
    for rain in payload['rainfall']:
        rain['hourly_mm'] = [0] * 6
    dry = b_incident(run(payload)[0])
    rules = [c.rule_id for h in dry.hypotheses for c in h.contributions]
    assert any(r.endswith('.N') for r in rules) and not any(r.endswith('.R') for r in rules)


def test_metadata_admission_availability_future_and_quality():
    late = signal('late', minutes=0, received=60)
    data = dataset('late', [late])
    assert run(data, BASE)[0] == []
    assert run(data, BASE + timedelta(hours=1))[0][0].first_observed_at == BASE
    future = signal('future', minutes=6, received=0)
    assert 'admission.future_quarantine' in run(dataset('future', [future]), BASE)[1][0]['rule_ids']
    allowed = signal('clock-skew', minutes=5, received=0)
    assert run(dataset('skew', [allowed]), BASE)[0][0].trace['clock_skew_signal_ids'] == ['clock-skew']
    for field, value in [('location_accuracy_m', None), ('location_accuracy_m', 51), ('time_uncertainty_minutes', 31), ('independence', 'uncertain')]:
        s = signal('metadata'); s[field] = value
        assert run(dataset('metadata', [s]))[0] == []


def test_timezone_and_null_contract_validation():
    s = signal('naive'); s['observed_at'] = '2026-09-09T06:00:00'
    with pytest.raises(ValidationError): Signal.model_validate(s)
    s = signal('unknown'); s['evidence'][0]['state'] = 'unknown'
    with pytest.raises(ValidationError): Signal.model_validate(s)
    s = signal('wrong-parent'); s['evidence'][0]['signal_id'] = 'other'
    with pytest.raises(ValidationError): Signal.model_validate(s)


def test_strong_requires_field_verification_and_temporal_corroboration():
    payload = build()['signature']
    assert b_incident(run(payload)[0]).evidence_strength == 'Moderate'
    photo = next(s for s in payload['signals'] if s['source_family'] == 'image')
    photo['evidence'][0].update(basis='verified', field_verified=True)
    assert b_incident(run(payload)[0]).evidence_strength == 'Strong corroboration'


def test_replay_determinism_and_input_order_independence():
    payload = build()['signature']
    first = [i.model_dump(mode='json') for i in run(payload)[0]]
    payload['signals'].reverse()
    assert [i.model_dump(mode='json') for i in run(payload)[0]] == first
