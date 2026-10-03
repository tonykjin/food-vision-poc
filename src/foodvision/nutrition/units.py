"""Explicit unit handling. No implicit conversions: ml↔g needs a supplied density."""

from enum import StrEnum

from foodvision.contracts.errors import ErrorCode

KJ_PER_KCAL = 4.184  # thermochemical calorie


class NutritionError(ValueError):
    code: ErrorCode = ErrorCode.UNSUPPORTED_UNIT


class UnsupportedUnitError(NutritionError):
    code = ErrorCode.UNSUPPORTED_UNIT


class MissingPortionBasisError(NutritionError):
    code = ErrorCode.MISSING_PORTION_BASIS


class QuantityUnit(StrEnum):
    G = "g"
    ML = "ml"


# Canonical output unit per nutrient, and the source units we know how to convert.
ENERGY_TO_KCAL: dict[str, float] = {"kcal": 1.0, "kj": 1.0 / KJ_PER_KCAL}
MASS_TO_G: dict[str, float] = {"g": 1.0, "mg": 1e-3, "ug": 1e-6, "µg": 1e-6}


def kj_to_kcal(kilojoules: float) -> float:
    return kilojoules / KJ_PER_KCAL


def to_canonical(amount: float, unit: str, *, energy: bool) -> float:
    """Convert a nutrient amount to kcal (energy) or grams (macros)."""
    table = ENERGY_TO_KCAL if energy else MASS_TO_G
    factor = table.get(unit.strip().lower())
    if factor is None:
        kind = "energy" if energy else "mass"
        raise UnsupportedUnitError(f"unsupported {kind} unit {unit!r}")
    return amount * factor


def convert_quantity(
    amount: float,
    from_unit: QuantityUnit,
    to_unit: QuantityUnit,
    density_g_per_ml: float | None = None,
) -> float:
    if from_unit is to_unit:
        return amount
    if density_g_per_ml is None:
        raise UnsupportedUnitError(
            f"cannot convert {from_unit} to {to_unit} without a supported density"
        )
    if from_unit is QuantityUnit.ML:
        return amount * density_g_per_ml
    return amount / density_g_per_ml
