from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewState(str, Enum):
    unreviewed = "unreviewed"
    inspection_needed = "inspection_needed"
    inspected = "inspected"
    dismissed = "dismissed"
    closed = "closed"


class Provenance(Contract):
    content_origin: Literal["synthetic", "public_source", "collected"]
    placement_origin: Literal["simulated", "original", "unknown"]
    time_origin: Literal["simulated", "original", "inferred", "unknown"]
    source_ref: str
    author_category: str
    license: str
    annotation_method: Literal["manual_structured", "ai_text", "ai_image", "human_reviewed"] = "manual_structured"
    reviewer: str


class Evidence(Contract):
    evidence_id: str
    signal_id: str
    feature: Literal["standing_water", "visible_road_damage", "passage_obstruction",
                     "reported_duration", "non_rainfall_discharge", "transient_verified"]
    state: Literal["positive", "negative", "unknown"]
    value: Literal[0, 0.5, 1] | None = None
    basis: Literal["reported", "visually_suggested", "verified", "derived"]
    quality: Literal[0, 0.4, 0.7, 0.9] = 0.9
    span: str
    field_verified: bool = False
    quality_reason: str = "Reviewed structured demo annotation; not physical field verification."

    @model_validator(mode="after")
    def validate_value(self):
        if self.state == "unknown" and self.value is not None:
            raise ValueError("Unknown evidence cannot have an ordinal value")
        if self.state == "negative" and self.value not in (0, None):
            raise ValueError("Negative evidence cannot have positive severity")
        if self.field_verified and self.basis != "verified":
            raise ValueError("Field verification requires verified basis")
        return self


class Signal(Contract):
    signal_id: str
    schema_version: str = "1.0"
    dataset_id: str
    idempotency_key: str
    source_record_id: str
    source_family: Literal["text", "image"]
    capture_group_id: str
    copy_lineage: str | None = None
    independence: Literal["asserted", "uncertain"] = "asserted"
    text: str | None = Field(default=None, max_length=4000)
    image_path: str | None = None
    exact_image_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    content_hash: str | None = None
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    location_accuracy_m: float | None = Field(default=None, ge=0)
    location_method: str = "manual reviewed demo pin"
    road_context_id: str | None
    observed_at: datetime
    received_at: datetime
    available_at: datetime
    time_uncertainty_minutes: float = Field(default=0, ge=0)
    provenance: Provenance
    evidence: list[Evidence] = Field(max_length=12)
    duplicate_of: str | None = None

    @field_validator("observed_at", "received_at", "available_at")
    @classmethod
    def utc(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def lineage_valid(self):
        if any(e.signal_id != self.signal_id for e in self.evidence):
            raise ValueError("Evidence signal_id must match parent")
        if self.available_at < self.received_at:
            raise ValueError("available_at cannot precede received_at")
        if len({e.evidence_id for e in self.evidence}) != len(self.evidence):
            raise ValueError("Duplicate evidence IDs")
        return self


class ImageObservationMetadata(Contract):
    """Operator-owned metadata for an uploaded image.

    The image itself is handled by the image adapter.  This contract deliberately
    contains no model, extraction, score, or incident fields.
    """
    text: str | None = Field(default=None, max_length=4000)
    lat: float = Field(ge=30.045, le=30.063)
    lon: float = Field(ge=31.325, le=31.346)
    observed_at: datetime
    location_accuracy_m: float | None = Field(default=None, ge=0)
    road_context_id: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[\w -]+$")
    capture_group_id: str = Field(min_length=1, max_length=80, pattern=r"^[\w-]+$")
    independence: Literal["asserted", "uncertain"] = "uncertain"
    copy_lineage: str | None = Field(default=None, max_length=80)
    operator: str = Field(min_length=1, max_length=80)
    idempotency_key: str = Field(min_length=1, max_length=80)
    content_origin: Literal["public_source", "collected", "synthetic"] = "collected"
    source_ref: str = Field(default="", max_length=500)
    license: str = Field(default="local operator supplied", max_length=240)
    placement_origin: Literal["simulated", "original", "unknown"] = "unknown"
    time_origin: Literal["simulated", "original", "inferred", "unknown"] = "unknown"

    _utc = field_validator("observed_at")(classmethod(Signal.utc.__func__))

    @field_validator("operator", "road_context_id")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Must not be blank")
        return value

    @model_validator(mode="after")
    def provenance_is_explicit(self):
        # Synthetic placement is never silently represented as an original
        # photograph.  Callers may still explicitly use unknown for an
        # unverified public source.
        if self.content_origin == "synthetic" and self.placement_origin == "unknown":
            self.placement_origin = "simulated"
        if self.content_origin == "synthetic" and self.time_origin == "unknown":
            self.time_origin = "simulated"
        if self.content_origin == "public_source" and (not self.source_ref.strip() or not self.license.strip()):
            raise ValueError("Public-source images require source_ref and license")
        if self.placement_origin == "simulated" and self.content_origin != "synthetic":
            # A real image can be deliberately relocated for a demo, but the
            # caller must say so through source metadata; accepting it is safe.
            pass
        return self


class ContextSource(Contract):
    provider: str
    product: str
    request_url: str
    acquired_at: datetime
    raw_ref: str
    raw_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    application: Literal["original", "retrospective_demo"] = "original"
    grid_center: tuple[float, float] | None = None
    resolution_degrees: float | None = None
    interval_ends: list[datetime] = Field(default_factory=list)
    notes: str

    _utc = field_validator("acquired_at")(classmethod(Signal.utc.__func__))


class RoadContext(Contract):
    road_context_id: str
    name: str
    road_class: Literal["service", "local", "primary", "secondary", "tertiary"] | None
    compatible_ids: list[str] = Field(default_factory=list)
    coordinates: list[tuple[float, float]]
    provenance: Provenance
    source: ContextSource | None = None


class RainContext(Contract):
    context_id: str
    end_at: datetime
    available_at: datetime
    hourly_mm: list[float | None] = Field(min_length=6, max_length=6)
    bbox: tuple[float, float, float, float]
    provenance: Provenance
    source: ContextSource | None = None

    _utc = field_validator("end_at", "available_at")(classmethod(Signal.utc.__func__))

    @field_validator("hourly_mm")
    @classmethod
    def nonnegative(cls, values):
        if any(v is not None and v < 0 for v in values):
            raise ValueError("Rainfall cannot be negative")
        return values


class CaptureGroup(Contract):
    capture_group_id: str
    signal_ids: list[str]
    evidence_ids: list[str]


class Contribution(Contract):
    rule_id: str
    evidence_ids: list[str]
    strength: float
    weight: float
    points: float


class HypothesisResult(Contract):
    hypothesis_id: str
    title: str
    support_points: float
    contributions: list[Contribution]
    missing_discriminators: list[str]
    tied_or_leading: Literal["leading", "tied", "alternative", "abstained"]
    tied_with: list[str] = Field(default_factory=list)


class RiskResult(Contract):
    risk_min: float
    risk_max: float
    display: str
    risk_band: str
    provisional: bool
    components: dict[str, float | None]
    known_component_coverage: float
    contributions: list[Contribution]
    rule_version: str


class FeatureResult(Contract):
    state: Literal["positive", "negative", "unknown", "conflicting"]
    strength: float = 0
    value: float | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    rule_id: str


class Incident(Contract):
    incident_id: str
    dataset_id: str
    revision: int = 1
    algorithm_version: str = "phase1-engine-1.0"
    config_version: str
    status: Literal["watch", "candidate"]
    active: bool = True
    tag: str
    road_name: str
    lat: float
    lon: float
    max_pair_distance_m: float
    first_observed_at: datetime
    last_observed_at: datetime
    computed_as_of: datetime
    signal_ids: list[str]
    capture_groups: list[CaptureGroup]
    independent_capture_count: int
    features: dict[str, FeatureResult]
    hypotheses: list[HypothesisResult]
    hypothesis_abstention: bool
    risk: RiskResult
    evidence_strength: Literal["Limited", "Moderate", "Strong corroboration"]
    review_state: ReviewState = ReviewState.unreviewed
    trace: dict


class IncidentRevision(Contract):
    incident_id: str
    revision: int
    previous_revision: int | None
    snapshot: Incident


class Dataset(Contract):
    dataset_id: str
    title: str
    mode: Literal["manual_structured", "cached_extraction"] = "manual_structured"
    roads: list[RoadContext]
    rainfall: list[RainContext]
    signals: list[Signal] = Field(max_length=1000)

    @model_validator(mode="after")
    def isolated(self):
        if any(s.dataset_id != self.dataset_id for s in self.signals):
            raise ValueError("Cross-dataset signal rejected")
        for values in ([s.signal_id for s in self.signals],
                       [e.evidence_id for s in self.signals for e in s.evidence],
                       [r.road_context_id for r in self.roads]):
            if len(set(values)) != len(values):
                raise ValueError("Identifiers must be unique")
        return self
