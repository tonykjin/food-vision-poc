"""B_direct output: recognition hypotheses plus the model's own nutrient estimates (plan §9 B5).

Diagnostic only, never the production path. The nutrients are model estimates with no
database grounding, so results are labeled that way everywhere. Unknown estimates stay None.
Same image, item and text limits as recognition, so B_direct and B_grounded see the same
input and constraints; the prompt states every limit (structured outputs can't enforce them).
"""

import copy
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from foodvision.recognition.hypotheses import (
    MAX_ITEMS,
    OUTPUT_SCHEMA,
    FoodHypothesis,
    ImageAssessment,
)

DIRECT_PROMPT_VERSION = "estimate-nutrition-direct-v1"
MAX_ITEM_ENERGY_KCAL = 5000.0
MAX_ITEM_MACRO_G = 500.0

Energy = Annotated[float, Field(ge=0, le=MAX_ITEM_ENERGY_KCAL, allow_inf_nan=False)]
Macro = Annotated[float, Field(ge=0, le=MAX_ITEM_MACRO_G, allow_inf_nan=False)]


class EstimatedNutrients(BaseModel):
    """The model's estimate for the item's base portion. None means it gave no estimate."""

    model_config = ConfigDict(extra="forbid")

    energy_kcal: Energy | None
    protein_g: Macro | None
    carbohydrate_g: Macro | None
    fat_g: Macro | None


class DirectItem(FoodHypothesis):
    estimated_nutrients: EstimatedNutrients


class DirectOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_assessment: ImageAssessment
    items: list[DirectItem] = Field(max_length=MAX_ITEMS)

    @model_validator(mode="after")
    def _no_items_without_food(self) -> Self:
        if not self.image_assessment.is_food_image and self.items:
            raise ValueError("items listed for an image assessed as containing no food")
        return self


def _nullable_number() -> dict:
    return {"anyOf": [{"type": "number"}, {"type": "null"}]}


DIRECT_SCHEMA: dict = copy.deepcopy(OUTPUT_SCHEMA)
_item = DIRECT_SCHEMA["properties"]["items"]["items"]
_item["properties"]["estimated_nutrients"] = {
    "type": "object",
    "properties": {
        key: _nullable_number() for key in ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g")
    },
    "required": ["energy_kcal", "protein_g", "carbohydrate_g", "fat_g"],
    "additionalProperties": False,
}
_item["required"] = list(_item["properties"])
