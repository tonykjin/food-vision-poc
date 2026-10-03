"""Deterministic, source-aware nutrient arithmetic (plan §7 Nutrition rules).

nutrient_for_portion = amount_per_basis × portion_in_basis_unit / basis_quantity.
No rounding here; round only for display (`foodvision.nutrition.display`).
"""

from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from foodvision.contracts.results import (
    NUTRIENT_KEYS,
    FoodSource,
    NonNegative,
    Nutrients,
    Positive,
    Totals,
    TotalsStatus,
)
from foodvision.nutrition.units import (
    MissingPortionBasisError,
    QuantityUnit,
    convert_quantity,
    to_canonical,
)

# Source nutrient name -> (result field, is energy)
SOURCE_NUTRIENTS: dict[str, tuple[str, bool]] = {
    "energy": ("energy_kcal", True),
    "protein": ("protein_g", False),
    "carbohydrate": ("carbohydrate_g", False),
    "fat": ("fat_g", False),
}
assert {field for field, _ in SOURCE_NUTRIENTS.values()} == set(NUTRIENT_KEYS)


class BasisKind(StrEnum):
    PER_100G = "per_100g"
    PER_100ML = "per_100ml"
    PER_SERVING = "per_serving"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReferenceBasis(Strict):
    kind: BasisKind
    quantity: Positive
    unit: QuantityUnit

    @model_validator(mode="after")
    def _kind_matches_quantity(self) -> Self:
        expected = {
            BasisKind.PER_100G: (100.0, QuantityUnit.G),
            BasisKind.PER_100ML: (100.0, QuantityUnit.ML),
        }.get(self.kind)
        if expected and (self.quantity, self.unit) != expected:
            raise ValueError(
                f"inconsistent basis: {self.kind} must be {expected[0]:g} {expected[1]}, "
                f"got {self.quantity:g} {self.unit}"
            )
        return self


class SourceNutrient(Strict):
    amount: NonNegative | None
    unit: str = Field(min_length=1)


class FoodRecord(Strict):
    food_id: str = Field(min_length=1)
    source: FoodSource
    basis: ReferenceBasis
    nutrients: dict[str, SourceNutrient]
    density_g_per_ml: Positive | None = None

    @model_validator(mode="after")
    def _known_nutrient_names(self) -> Self:
        unknown = set(self.nutrients) - set(SOURCE_NUTRIENTS)
        if unknown:
            raise ValueError(f"unknown nutrient names: {sorted(unknown)}")
        return self


class Portion(Strict):
    amount: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    unit: QuantityUnit = QuantityUnit.G


def scale_factor(record: FoodRecord, portion: Portion) -> float:
    in_basis_unit = convert_quantity(
        portion.amount, portion.unit, record.basis.unit, record.density_g_per_ml
    )
    return in_basis_unit / record.basis.quantity


def calculate_item(record: FoodRecord, portion: Portion | None) -> Nutrients:
    """Nutrients for one portion of one record. Missing source values stay None."""
    if portion is None:
        raise MissingPortionBasisError(f"no portion for food {record.food_id}")
    factor = scale_factor(record, portion)
    values: dict[str, float | None] = dict.fromkeys(NUTRIENT_KEYS)
    for name, source in record.nutrients.items():
        field, is_energy = SOURCE_NUTRIENTS[name]
        if source.amount is None:
            continue
        values[field] = to_canonical(source.amount, source.unit, energy=is_energy) * factor
    return Nutrients(**values)


def sum_totals(items: Sequence[Nutrients | None]) -> Totals:
    """Sum resolved items. None marks an unresolved item, which is excluded (not zero).

    A nutrient total is None if any included item lacks it. Totals are complete only when
    every item is resolved and every nutrient is known.
    """
    resolved = [item for item in items if item is not None]
    excluded = len(items) - len(resolved)
    if not resolved:
        return Totals(status=TotalsStatus.UNAVAILABLE, excluded_items=excluded)

    sums: dict[str, float | None] = {}
    for key in NUTRIENT_KEYS:
        amounts = [getattr(item, key) for item in resolved]
        sums[key] = None if any(a is None for a in amounts) else sum(amounts)
    nutrients = Nutrients(**sums)

    if not excluded and not nutrients.missing():
        status = TotalsStatus.COMPLETE
    elif len(nutrients.missing()) == len(NUTRIENT_KEYS):
        status = TotalsStatus.UNAVAILABLE
    else:
        status = TotalsStatus.PARTIAL
    return Totals(
        status=status, nutrients=nutrients, included_items=len(resolved), excluded_items=excluded
    )
