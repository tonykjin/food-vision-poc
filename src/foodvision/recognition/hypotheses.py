"""Food hypotheses returned by a vision model, and the wire schema requested from it.

The JSON schema sent to the provider stays within structured-output limits (no numeric or
length constraints). Every response is validated again here, server-side: valid JSON does
not make quantities true, and provider schema guarantees don't replace our checks.
Hypotheses carry no confidence percentage: model self-assessment is not measured accuracy.
"""

import hashlib
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from foodvision.catalog.preparation import PreparationState

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
PROMPT_VERSION = "recognize-food-v2"  # v2 states every limit below; v1 kept for provenance
MAX_ITEMS = 8
MAX_ALTERNATIVES = 3
MAX_PORTION_G = 3000.0
MAX_UNCERTAINTY = 6
MAX_TEXT_CHARS = 200
MAX_BRAND_CHARS = 100
MAX_NOTES_CHARS = 300

ShortText = Annotated[str, Field(min_length=1, max_length=MAX_TEXT_CHARS)]


class Preparation(StrEnum):
    RAW = "raw"
    COOKED = "cooked"
    FRIED = "fried"
    BAKED = "baked"
    GRILLED = "grilled"
    ROASTED = "roasted"
    BOILED = "boiled"
    STEAMED = "steamed"
    SAUTEED = "sauteed"
    UNKNOWN = "unknown"

    def catalog_state(self) -> PreparationState | None:
        """Preparation filter for USDA retrieval; unknown means no filter."""
        if self is Preparation.UNKNOWN:
            return None
        return PreparationState.UNCOOKED if self is Preparation.RAW else PreparationState.COOKED


class FoodHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: ShortText
    search_description: ShortText
    preparation: Preparation
    visible_brand: Annotated[str, Field(max_length=MAX_BRAND_CHARS)] | None
    portion_grams_low: Annotated[float, Field(gt=0, le=MAX_PORTION_G, allow_inf_nan=False)]
    portion_grams_base: Annotated[float, Field(gt=0, le=MAX_PORTION_G, allow_inf_nan=False)]
    portion_grams_high: Annotated[float, Field(gt=0, le=MAX_PORTION_G, allow_inf_nan=False)]
    portion_assumptions: ShortText
    alternatives: list[ShortText] = Field(max_length=MAX_ALTERNATIVES)
    evidence: ShortText
    uncertainty: list[ShortText] = Field(max_length=MAX_UNCERTAINTY)
    is_composite: bool

    @model_validator(mode="after")
    def _ordered_scenarios(self) -> Self:
        if not self.portion_grams_low <= self.portion_grams_base <= self.portion_grams_high:
            raise ValueError("portion grams must satisfy low <= base <= high")
        return self


class ImageAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_food_image: bool
    multiple_foods: bool
    notes: Annotated[str, Field(max_length=MAX_NOTES_CHARS)]


class RecognitionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_assessment: ImageAssessment
    items: list[FoodHypothesis] = Field(max_length=MAX_ITEMS)

    @model_validator(mode="after")
    def _no_items_without_food(self) -> Self:
        if not self.image_assessment.is_food_image and self.items:
            raise ValueError("items listed for an image assessed as containing no food")
        return self


def _string() -> dict:
    return {"type": "string"}


_HYPOTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "display_name": _string(),
        "search_description": _string(),
        "preparation": {"type": "string", "enum": [p.value for p in Preparation]},
        "visible_brand": {"anyOf": [_string(), {"type": "null"}]},
        "portion_grams_low": {"type": "number"},
        "portion_grams_base": {"type": "number"},
        "portion_grams_high": {"type": "number"},
        "portion_assumptions": _string(),
        "alternatives": {"type": "array", "items": _string()},
        "evidence": _string(),
        "uncertainty": {"type": "array", "items": _string()},
        "is_composite": {"type": "boolean"},
    },
    "additionalProperties": False,
}
_HYPOTHESIS_SCHEMA["required"] = list(_HYPOTHESIS_SCHEMA["properties"])

OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "image_assessment": {
            "type": "object",
            "properties": {
                "is_food_image": {"type": "boolean"},
                "multiple_foods": {"type": "boolean"},
                "notes": _string(),
            },
            "required": ["is_food_image", "multiple_foods", "notes"],
            "additionalProperties": False,
        },
        "items": {"type": "array", "items": _HYPOTHESIS_SCHEMA},
    },
    "required": ["image_assessment", "items"],
    "additionalProperties": False,
}


def load_prompt(version: str = PROMPT_VERSION) -> tuple[str, str]:
    """Return (prompt text, SHA-256 of the text with normalized line endings)."""
    text = (PROMPTS_DIR / f"{version}.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()
