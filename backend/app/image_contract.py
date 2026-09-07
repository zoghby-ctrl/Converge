"""Bounded image perception contracts.

The image adapter describes pixels only.  It does not infer causes, severity,
incident membership, or field verification.
"""
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .models import Contract, Evidence

TASK_VERSION = "image-perception-1"
PROMPT_VERSION = "image-1.2"
SCHEMA_VERSION = "image-1.0"
NORMALIZATION_VERSION = "image-normalization-1"

ImageState = Literal["present", "absent", "uncertain", "not_assessable"]
ImageQuality = Literal["usable", "limited", "unusable"]
ImageField = Literal["standing_water", "visible_surface_damage", "passage_obstruction"]

# A description may name a visible object (for example, a drain cover) but it
# cannot turn that object into a physical explanation.  Phrase guards are used
# only for claims that require evidence outside one photograph; broad word
# bans would reject literal visual descriptions such as "drain cover" or
# "depth unknown".
_CAUSE_PATTERNS = (
    r"\b(?:burst|broken|blocked|clogged|failed|leaking)\s+(?:pipe|sewer|drain|drainage)\b",
    r"\b(?:pipe|sewer|drain|drainage)\s+(?:burst|failure|failed|leak|leaking)\b",
    r"\b(?:underground|structural|drainage)\s+(?:leak|failure)\b",
    r"\b(?:water|flood(?:ing)?|damage)\s+(?:was|is|were|are)?\s*caused\s+by\b",
    r"\b(?:because|due\s+to)\s+(?:of\s+)?(?:the\s+)?(?:water|flood|rain|drain|pipe|sewer)\b",
    r"\b(?:water|puddle|standing\s+water)\s+depth\b",
    r"\bdepth\s*(?:is|was|:|=)\s*\d",
    r"\b\d+(?:\.\d+)?\s*(?:cm|mm|m|meters?|feet)\s*(?:deep|depth)\b",
    r"\b(?:deterioration|degradation)\s+rate\b",
    r"\b(?:when|how\s+long\s+ago)\s+(?:the\s+)?(?:damage|failure|leak)\s+(?:occurred|started)\b",
    r"(?:ماسورة|صرف\s+صحي|تسريب)\s*(?:مكسورة|انفجرت|مسدودة|فاشلة|بسبب)",
)
_CAUSE_RE = tuple(re.compile(pattern, re.IGNORECASE) for pattern in _CAUSE_PATTERNS)
_TRAVEL_SURFACE_RE = re.compile(
    r"\b(?:road(?:way)?|street|lane|pavement|asphalt|carriageway|walkway|path|sidewalk)\b",
    re.IGNORECASE,
)


def _has_unsupported_claim(value: str) -> bool:
    return any(pattern.search(value) for pattern in _CAUSE_RE)


class ImageUncertainty(Contract):
    field: ImageField
    reason: Literal[
        "ambiguous_visual", "limited_visibility", "glare_or_reflection",
        "occluded", "poor_quality", "irrelevant_scene", "unclear_boundary",
    ]


class SupportDescription(Contract):
    field: ImageField
    description: str = Field(min_length=1, max_length=240)

    @field_validator("description")
    @classmethod
    def no_cause_claims(cls, value):
        if _has_unsupported_claim(value):
            raise ValueError("Image descriptions cannot infer physical causes")
        return value


class ImageExtraction(Contract):
    standing_water: ImageState
    visible_surface_damage: ImageState
    passage_obstruction: ImageState
    image_quality: ImageQuality
    visible_description: str = Field(min_length=1, max_length=400)
    # Required even when empty so a strict provider response cannot silently
    # omit uncertainty/support accounting.
    uncertainties: list[ImageUncertainty] = Field(max_length=12)
    support_descriptions: list[SupportDescription] = Field(max_length=12)

    @field_validator("visible_description")
    @classmethod
    def bounded_visual_description(cls, value):
        if _has_unsupported_claim(value):
            raise ValueError("Image descriptions cannot infer physical causes")
        return value

    @model_validator(mode="after")
    def supported_and_assessable(self):
        values = {
            "standing_water": self.standing_water,
            "visible_surface_damage": self.visible_surface_damage,
            "passage_obstruction": self.passage_obstruction,
        }
        supports = {item.field for item in self.support_descriptions}
        uncertain = {item.field for item in self.uncertainties}
        if self.image_quality == "unusable":
            if any(state != "not_assessable" for state in values.values()):
                raise ValueError("Unusable images must mark every target not_assessable")
            if supports:
                raise ValueError("Unusable images cannot support admitted findings")
            if set(values) - uncertain:
                raise ValueError("Unusable images require an uncertainty for each target")
        for field, state in values.items():
            if state in ("present", "absent") and field not in supports:
                raise ValueError("Assessable image states require support_descriptions")
            if state in ("uncertain", "not_assessable") and field not in uncertain:
                raise ValueError("Abstentions require machine-readable uncertainties")
            if state in ("present", "absent") and field in uncertain:
                raise ValueError("Assessable image states cannot also carry an uncertainty")
            if state in ("uncertain", "not_assessable") and field in supports:
                raise ValueError("Abstained image states cannot carry support descriptions")
        if len(supports) != len(self.support_descriptions):
            raise ValueError("Only one support description per target is allowed")
        if len(uncertain) != len(self.uncertainties):
            raise ValueError("Only one uncertainty per target is allowed")
        if all(state == "not_assessable" for state in values.values()) and self.image_quality != "unusable":
            raise ValueError("Images with no assessable target must be marked unusable")
        if self.image_quality == "limited" and not uncertain and any(
            state in ("uncertain", "not_assessable") for state in values.values()
        ):
            raise ValueError("Limited-image abstentions require uncertainty reasons")
        return self


def admission_warnings(extraction: ImageExtraction) -> list[str]:
    """Conservative local gates for otherwise schema-valid model output."""
    if extraction.visible_surface_damage != "present":
        return []
    support = next(
        item.description for item in extraction.support_descriptions
        if item.field == "visible_surface_damage"
    )
    if not _TRAVEL_SURFACE_RE.search(support):
        return ["surface_damage_travel_surface_not_explicit"]
    return []


class ImageMetadata(Contract):
    raw_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    stored_path: str = Field(min_length=1, max_length=1000)
    normalized_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    normalization_version: Literal["image-normalization-1"]
    width: int = Field(gt=0, le=12_000_000)
    height: int = Field(gt=0, le=12_000_000)
    format: Literal["JPEG", "PNG"]
    preserved_path: str | None = Field(default=None, max_length=1000)
    preserved_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    original_width: int | None = Field(default=None, gt=0, le=12_000_000)
    original_height: int | None = Field(default=None, gt=0, le=12_000_000)
    # dHash is a near-duplicate hint, never an exact identity or evidence.
    perceptual_hash: str = Field(pattern=r"^[a-f0-9]{16}$")

    @model_validator(mode="after")
    def pixel_bound(self):
        if self.width * self.height > 12_000_000:
            raise ValueError("Decoded image exceeds 12 megapixels")
        if self.original_width and self.original_height and self.original_width * self.original_height > 12_000_000:
            raise ValueError("Decoded image exceeds 12 megapixels")
        return self


def evidence_from(extraction: ImageExtraction, signal_id: str, revision: int, reviewed=False):
    """Map only admitted visual states into the existing evidence contract."""
    quality = {"usable": 0.7, "limited": 0.4, "unusable": 0}[extraction.image_quality]
    items = []
    for field, feature in (
        ("standing_water", "standing_water"),
        ("visible_surface_damage", "visible_road_damage"),
        ("passage_obstruction", "passage_obstruction"),
    ):
        state = getattr(extraction, field)
        if state not in ("present", "absent"):
            continue
        if field == "visible_surface_damage" and state == "present" and not reviewed and admission_warnings(extraction):
            # A model may correctly see chipped concrete while the image does
            # not establish that the relevant road/passage surface is damaged.
            # Preserve the extraction for review but do not admit the positive.
            continue
        support = next(item for item in extraction.support_descriptions if item.field == field)
        items.append(Evidence(
            evidence_id=f"{signal_id}-r{revision}-{field}", signal_id=signal_id,
            feature=feature, state="positive" if state == "present" else "negative",
            # The mapper deliberately keeps present water/obstruction ordinally
            # unknown.  Visible damage is an admitted but unknown-extent
            # category in the frozen architecture and therefore maps to 0.5.
            value=(0 if state == "absent" else
                   0.5 if field == "visible_surface_damage" else None),
            basis="visually_suggested",
            quality=quality, span=support.description, field_verified=False,
            quality_reason=("Human-reviewed visual observation; not field verification."
                            if reviewed else "Schema-validated AI visual observation; not field verification."),
        ))
    return items
