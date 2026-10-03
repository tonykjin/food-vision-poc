"""Nutrition arithmetic with independently computed expected values."""

import math

import pytest
from pydantic import ValidationError

from foodvision.contracts.results import FoodSource, Nutrients, TotalsStatus
from foodvision.nutrition.calculator import (
    BasisKind,
    FoodRecord,
    Portion,
    ReferenceBasis,
    SourceNutrient,
    calculate_item,
    sum_totals,
)
from foodvision.nutrition.display import format_nutrient
from foodvision.nutrition.units import (
    KJ_PER_KCAL,
    MissingPortionBasisError,
    QuantityUnit,
    UnsupportedUnitError,
    kj_to_kcal,
)

PER_100G = ReferenceBasis(kind=BasisKind.PER_100G, quantity=100, unit=QuantityUnit.G)


def record(basis=PER_100G, density=None, **nutrients):
    return FoodRecord(
        food_id="fdc:test",
        source=FoodSource.USDA,
        basis=basis,
        nutrients={k: SourceNutrient(amount=a, unit=u) for k, (a, u) in nutrients.items()},
        density_g_per_ml=density,
    )


# --- Required expected values ---------------------------------------------------------


def test_per_100g_200kcal_at_150g_is_300kcal():
    result = calculate_item(record(energy=(200, "kcal")), Portion(amount=150))
    assert result.energy_kcal == pytest.approx(300.0)


def test_per_serving_120kcal_per_40g_at_60g_is_180kcal():
    serving = ReferenceBasis(kind=BasisKind.PER_SERVING, quantity=40, unit=QuantityUnit.G)
    result = calculate_item(record(serving, energy=(120, "kcal")), Portion(amount=60))
    assert result.energy_kcal == pytest.approx(180.0)


def test_418_4_kj_is_100_kcal():
    assert KJ_PER_KCAL == 4.184
    assert kj_to_kcal(418.4) == pytest.approx(100.0)
    result = calculate_item(record(energy=(418.4, "kJ")), Portion(amount=100))
    assert result.energy_kcal == pytest.approx(100.0)


# --- Macros and units -----------------------------------------------------------------


def test_macros_scale_and_mg_converts_to_g():
    rec = record(protein=(500, "mg"), carbohydrate=(28, "g"), fat=(0.3, "g"))
    result = calculate_item(rec, Portion(amount=200))
    assert result.protein_g == pytest.approx(1.0)
    assert result.carbohydrate_g == pytest.approx(56.0)
    assert result.fat_g == pytest.approx(0.6)


def test_unknown_energy_unit_is_rejected():
    with pytest.raises(UnsupportedUnitError):
        calculate_item(record(energy=(100, "cal")), Portion(amount=100))


# --- Missing and boundary values ------------------------------------------------------


def test_missing_nutrients_stay_none_not_zero():
    result = calculate_item(record(energy=(200, "kcal"), protein=(None, "g")), Portion(amount=50))
    assert result.energy_kcal == pytest.approx(100.0)
    assert result.protein_g is None  # explicitly unknown in source
    assert result.fat_g is None  # absent from source
    assert result.missing() == ["protein_g", "carbohydrate_g", "fat_g"]


def test_true_zero_nutrient_is_zero_not_unknown():
    result = calculate_item(record(fat=(0, "g")), Portion(amount=150))
    assert result.fat_g == 0.0


@pytest.mark.parametrize("amount", [0, -1, math.nan, math.inf])
def test_invalid_portion_amounts_rejected(amount):
    with pytest.raises(ValidationError):
        Portion(amount=amount)


@pytest.mark.parametrize("amount", [-5, math.nan, math.inf])
def test_invalid_source_amounts_rejected(amount):
    with pytest.raises(ValidationError):
        SourceNutrient(amount=amount, unit="kcal")


@pytest.mark.parametrize("quantity", [0, -40, math.nan])
def test_invalid_basis_quantity_rejected(quantity):
    with pytest.raises(ValidationError):
        ReferenceBasis(kind=BasisKind.PER_SERVING, quantity=quantity, unit=QuantityUnit.G)


def test_missing_portion_is_typed_error():
    with pytest.raises(MissingPortionBasisError):
        calculate_item(record(energy=(100, "kcal")), None)


# --- Inconsistent bases and ml without density ----------------------------------------


@pytest.mark.parametrize(
    ("kind", "quantity", "unit"),
    [
        (BasisKind.PER_100G, 40, QuantityUnit.G),
        (BasisKind.PER_100G, 100, QuantityUnit.ML),
        (BasisKind.PER_100ML, 100, QuantityUnit.G),
    ],
)
def test_inconsistent_basis_rejected(kind, quantity, unit):
    with pytest.raises(ValidationError, match="inconsistent basis"):
        ReferenceBasis(kind=kind, quantity=quantity, unit=unit)


def test_ml_portion_on_gram_basis_without_density_rejected():
    with pytest.raises(UnsupportedUnitError, match="density"):
        calculate_item(record(energy=(64, "kcal")), Portion(amount=250, unit=QuantityUnit.ML))


def test_gram_portion_on_ml_basis_without_density_rejected():
    per_100ml = ReferenceBasis(kind=BasisKind.PER_100ML, quantity=100, unit=QuantityUnit.ML)
    with pytest.raises(UnsupportedUnitError):
        calculate_item(record(per_100ml, energy=(42, "kcal")), Portion(amount=200))


def test_ml_portion_with_supplied_density():
    # 250 ml × 1.03 g/ml = 257.5 g; 64 kcal/100 g → 164.8 kcal
    rec = record(density=1.03, energy=(64, "kcal"))
    result = calculate_item(rec, Portion(amount=250, unit=QuantityUnit.ML))
    assert result.energy_kcal == pytest.approx(164.8)


def test_unknown_nutrient_name_rejected():
    with pytest.raises(ValidationError, match="unknown nutrient"):
        record(sugar=(5, "g"))


# --- Totals ---------------------------------------------------------------------------


def full(kcal):
    return Nutrients(energy_kcal=kcal, protein_g=1.0, carbohydrate_g=2.0, fat_g=3.0)


def test_all_resolved_and_known_is_complete():
    totals = sum_totals([full(300.0), full(180.0)])
    assert totals.status is TotalsStatus.COMPLETE
    assert totals.nutrients.energy_kcal == pytest.approx(480.0)
    assert totals.nutrients.fat_g == pytest.approx(6.0)


def test_unresolved_item_makes_totals_partial_not_complete():
    totals = sum_totals([full(300.0), None])
    assert totals.status is TotalsStatus.PARTIAL
    assert totals.included_items == 1 and totals.excluded_items == 1
    assert totals.nutrients.energy_kcal == pytest.approx(300.0)


def test_unknown_nutrient_in_any_item_makes_that_total_unknown():
    totals = sum_totals([full(300.0), Nutrients(energy_kcal=100.0)])
    assert totals.status is TotalsStatus.PARTIAL
    assert totals.nutrients.energy_kcal == pytest.approx(400.0)
    assert totals.nutrients.protein_g is None


def test_no_resolved_items_is_unavailable():
    totals = sum_totals([None, None])
    assert totals.status is TotalsStatus.UNAVAILABLE
    assert totals.nutrients.missing() == ["energy_kcal", "protein_g", "carbohydrate_g", "fat_g"]


def test_calculation_does_not_round_but_display_does():
    rec = record(energy=(333.3, "kcal"), protein=(12.34, "g"))
    result = calculate_item(rec, Portion(amount=90))
    assert result.energy_kcal == pytest.approx(299.97)
    assert format_nutrient("energy_kcal", result.energy_kcal) == "300 kcal"
    assert format_nutrient("protein_g", result.protein_g) == "11.1 g"
    assert format_nutrient("fat_g", None) == "unknown"
