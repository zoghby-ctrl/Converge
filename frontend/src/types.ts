export type Contribution = {rule_id: string; evidence_ids: string[]; strength: number; weight: number; points: number}
export type Evidence = {evidence_id: string; signal_id: string; feature: string; state: string; value: number | null; basis: string; quality: number; span: string; field_verified: boolean}
export type Provenance = {content_origin: string; placement_origin: string; time_origin: string; source_ref: string; reviewer: string; annotation_method: string}
export type Signal = {signal_id: string; source_family: string; capture_group_id: string; duplicate_of: string | null; text: string | null; image_url?: string | null; exact_image_hash?: string | null; lat: number; lon: number; observed_at: string; received_at: string; available_at: string; provenance: Provenance; evidence: Evidence[]}
export type ContextSource = {provider: string; product: string; request_url: string; acquired_at: string; raw_sha256: string; application: string; grid_center: [number, number] | null; resolution_degrees: number | null; notes: string}
export type Road = {road_context_id: string; name: string; coordinates: [number, number][]; provenance: Provenance; source?: ContextSource | null}
export type Exclusion = {signal_id: string; evidence_id?: string; rule_ids: string[]}
export type Feature = {state: string; strength: number; value: number | null; evidence_ids: string[]; rule_id: string}
export type Incident = {
  incident_id: string; revision: number; status: 'watch' | 'candidate'; tag: string; road_name: string;
  lat: number; lon: number; signal_ids: string[]; independent_capture_count: number;
  max_pair_distance_m: number; first_observed_at: string; last_observed_at: string;
  evidence_strength: string; review_state: string; hypothesis_abstention: boolean;
  risk: {risk_min: number; risk_max: number; display: string; risk_band: string; provisional: boolean; components: Record<string, number | null>; known_component_coverage: number; contributions: Contribution[]; rule_version: string};
  features: Record<string, Feature>;
  hypotheses: {hypothesis_id: string; title: string; support_points: number; tied_or_leading: string; tied_with: string[]; contributions: Contribution[]; missing_discriminators: string[]}[];
  trace: {member_evidence: Evidence[]; membership_reasons: {signal_id: string; capture_group_id: string; rule_ids: string[]; duplicate_of: string | null}[];
    excluded_evidence: Exclusion[]; missing_fields: string[]; conflicts: string[];
    inspection_checks: {rule_id: string; text: string; evidence_ids: string[]}[]; formation_rule: string; evidence_strength_rule: string;
    context: {roads: Road[]; rainfall: {context_id: string; hourly_mm: number[]; end_at: string; provenance: Provenance; source?: ContextSource | null} | null}; limitations: string[]}
}
export type Replay = {dataset_id: string | null; incidents: Incident[]; signals: Signal[]; roads: Road[]; step: number; total_steps: number; clock: string | null; mode: string; excluded: Exclusion[]; geography?: import('geojson').FeatureCollection | null; context_notice?: string}
export type Comparison = {incidents: Incident[]; baseline: Incident[]; signals: Signal[]; added_duplicates: number; disable_families: string[]; sandbox: boolean}
