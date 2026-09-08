"""Perception contract: no scoring, model routing, cause verification or identity fields."""
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .models import Contract, Evidence, Signal

TASK_VERSION = "text-perception-1"
PROMPT_VERSION = "text-1.1"
SCHEMA_VERSION = "text-1.0"
State = Literal["present", "absent", "uncertain", "not_mentioned"]
Temporal = Literal["current", "resolved", "historical", "uncertain"]
Fact = Literal["standing_water", "road_damage", "passage_obstruction", "recurrence",
               "reported_duration", "reported_explanation", "temporal_status"]


class Span(Contract):
    field: Fact
    quote: str = Field(min_length=1, max_length=180)
    temporal_status: Temporal


class Uncertainty(Contract):
    field: Fact
    reason: Literal["ambiguous_wording", "limited_visibility", "hearsay", "speculation",
                    "unclear_time", "unclear_duration", "unclear_causality"]
    affects_admission: bool


class Duration(Contract):
    minutes: float | None = Field(ge=0, le=5256000)
    phrase: str = Field(min_length=1, max_length=120)


class TextExtraction(Contract):
    language: Literal["egyptian_arabic", "standard_arabic", "english", "mixed", "unknown"]
    standing_water: State
    road_damage: State
    passage_obstruction: State
    reported_duration: Duration | None
    recurrence: State
    reported_explanation: str | None = Field(max_length=240)
    temporal_status: Temporal
    evidence_spans: list[Span] = Field(max_length=16)
    uncertainties: list[Uncertainty] = Field(max_length=12)

    @model_validator(mode="after")
    def supported(self):
        for field in ("standing_water", "road_damage", "passage_obstruction", "recurrence",
                      "reported_duration", "reported_explanation"):
            value = getattr(self, field)
            spans = [s for s in self.evidence_spans if s.field == field]
            asserted = value is not None and value != "not_mentioned"
            if asserted and not spans:
                raise ValueError("Every assertion requires a source span")
            if not asserted and spans:
                raise ValueError("Unmentioned fields must not have assertion spans")
            if value == "uncertain" and not any(u.field == field for u in self.uncertainties):
                raise ValueError("Uncertain fields require machine-readable uncertainty")
        return self

    def validate_source(self, text: str):
        if any(s.quote not in text for s in self.evidence_spans):
            raise ValueError("Evidence spans must be exact source substrings")
        if self.reported_duration and self.reported_duration.phrase not in text:
            raise ValueError("Duration phrase must be an exact source substring")
        return self


class NewObservation(Contract):
    text: str = Field(min_length=1, max_length=4000)
    lat: float = Field(ge=30.045, le=30.063)
    lon: float = Field(ge=31.325, le=31.346)
    observed_at: datetime
    location_accuracy_m: float | None = Field(default=None, ge=0)
    road_context_id: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[\w -]+$")
    capture_group_id: str = Field(min_length=1, max_length=80, pattern=r"^[\w-]+$")
    independence: Literal["asserted", "uncertain"] = "uncertain"
    copy_lineage: str | None = Field(default=None, max_length=80)
    operator: str = Field(min_length=1, max_length=80)
    content_origin: Literal["collected", "synthetic"] = "collected"
    idempotency_key: str = Field(min_length=1, max_length=80)

    _utc = field_validator("observed_at")(classmethod(Signal.utc.__func__))

    @field_validator("text", "operator", "road_context_id")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Must not be blank")
        return value


class Correction(Contract):
    extraction: TextExtraction
    reviewer: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=400)
    expected_revision: int = Field(ge=0)


class Reanalysis(Contract):
    action: Literal["retry_primary", "deeper_review"]
    expected_revision: int = Field(ge=0)


def evidence_from(extraction: TextExtraction, signal_id: str, revision: int, reviewed=False):
    """Conservative mapping. Presence is not a severity measurement or field verification."""
    items = []
    for field, feature in (("standing_water", "standing_water"), ("road_damage", "visible_road_damage"),
                           ("passage_obstruction", "passage_obstruction")):
        state = getattr(extraction, field)
        spans = [s for s in extraction.evidence_spans if s.field == field]
        current = [s for s in spans if s.temporal_status == "current"]
        blocked = any(u.field == field and u.affects_admission for u in extraction.uncertainties)
        if state not in ("present", "absent") or not current or blocked or extraction.temporal_status == "historical":
            continue
        if state == "present" and extraction.temporal_status == "uncertain":
            continue
        # A resolved episode cannot supply positive current water even if a model mislabels its span.
        if field == "standing_water" and extraction.temporal_status == "resolved" and state == "present":
            continue
        items.append(Evidence(evidence_id=f"{signal_id}-r{revision}-{field}", signal_id=signal_id,
            feature=feature, state="positive" if state == "present" else "negative",
            value=None if state == "present" else 0, basis="reported", quality=0.7,
            span=current[0].quote, quality_reason="Human-reviewed report claim; not field verification." if reviewed
            else "Schema-validated AI report claim; not field verification or severity measurement."))
    return items
