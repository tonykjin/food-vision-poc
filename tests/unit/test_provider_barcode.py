"""A_barcode normalization and confidence (#50). SYNTHETIC fixtures, no network."""

import copy
import json
from pathlib import Path

import pytest

from foodvision.contracts.errors import ErrorCode
from foodvision.contracts.requests import AnalysisContext
from foodvision.contracts.results import (
    ConfidenceLevel,
    FoodSource,
    NutritionBasis,
    PortionMethod,
    ResultStatus,
    TotalsStatus,
)
from foodvision.measurement.confidence import assess_confidence
from foodvision.pipelines.provider_barcode import (
    LABEL_SERVING_NOTICE,
    PIPELINE_ID,
    normalize_barcode_response,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "fatsecret"
FOUND = json.loads((FIXTURES / "barcode_found.json").read_text(encoding="utf-8"))
GTIN = "0027182729840"
CONTEXT = AnalysisContext(scan_id="s", original_sha256="0" * 64, pipeline_id=PIPELINE_ID)


def found(mutate=None):
    payload = copy.deepcopy(FOUND)
    if mutate:
        mutate(payload["food"])
    return payload


def test_default_serving_is_used_unscaled_and_labeled_as_one_serving():
    result = normalize_barcode_response(found(), GTIN, CONTEXT)
    assert result.status is ResultStatus.COMPLETE
    assert result.pipeline_id == "A_barcode"
    assert result.nutrition_basis is NutritionBasis.PER_LABEL_SERVING
    (item,) = result.items
    assert item.name == "SYNTHETIC Brand SYNTHETIC crispy strips"
    assert (item.food_id, item.serving_id) == ("9100001", "911")  # is_default=1, not the first
    assert item.portion_g == 84.0 and item.portion_method is PortionMethod.LABEL_SERVING
    assert item.food_source is FoodSource.FATSECRET
    n = item.nutrients
    assert (n.energy_kcal, n.protein_g, n.carbohydrate_g, n.fat_g) == (200, 13, 15, 10)
    assert result.totals.nutrients == n  # one serving, never scaled
    assert LABEL_SERVING_NOTICE in result.warnings
    assert "amount eaten unknown" in item.uncertainty_reasons
    assert f"identified by barcode {GTIN}" in item.uncertainty_reasons


def test_without_a_default_flag_the_first_serving_is_used():
    def drop_default(food):
        for s in food["servings"]["serving"]:
            s["is_default"] = "0"

    (item,) = normalize_barcode_response(found(drop_default), GTIN, CONTEXT).items
    assert item.serving_id == "910" and item.nutrients.energy_kcal == 400


def test_single_serving_object_is_accepted():
    def single(food):
        food["servings"]["serving"] = food["servings"]["serving"][1]

    assert normalize_barcode_response(found(single), GTIN, CONTEXT).items[0].serving_id == "911"


def test_ml_serving_stays_unresolved_without_a_density_assumption():
    def ml(food):
        for s in food["servings"]["serving"]:
            s["metric_serving_unit"] = "ml"

    result = normalize_barcode_response(found(ml), GTIN, CONTEXT)
    (item,) = result.items
    assert result.status is ResultStatus.PARTIAL and not item.resolved
    assert item.portion_g is None and item.portion_method is PortionMethod.UNKNOWN
    assert item.nutrients.energy_kcal == 200  # label facts still shown for the item
    assert result.totals.status is not TotalsStatus.COMPLETE
    assert "serving given in non-gram units; grams unknown" in item.uncertainty_reasons


def test_missing_nutrient_stays_unknown_and_result_is_partial():
    def no_fat(food):
        for s in food["servings"]["serving"]:
            s["fat"] = ""

    result = normalize_barcode_response(found(no_fat), GTIN, CONTEXT)
    assert result.status is ResultStatus.PARTIAL
    assert result.items[0].nutrients.fat_g is None  # unknown, never 0


@pytest.mark.parametrize(
    "payload",
    [
        {"error": {"code": "211", "message": "No food item detected"}},
        {"food_id": {"value": "0"}},  # v1-style "not found"
    ],
)
def test_unknown_barcode_is_a_typed_no_match(payload):
    result = normalize_barcode_response(payload, GTIN, CONTEXT)
    assert result.status is ResultStatus.FAILED and result.error.code is ErrorCode.NO_MATCH
    assert GTIN in result.error.message
    assert result.totals.status is TotalsStatus.UNAVAILABLE


def test_response_without_food_is_invalid_schema():
    result = normalize_barcode_response({"something": "else"}, GTIN, CONTEXT)
    assert result.error.code is ErrorCode.INVALID_SCHEMA


def test_confidence_marks_a_labeled_serving_low_and_not_image_estimated():
    confidence = assess_confidence(normalize_barcode_response(found(), GTIN, CONTEXT))
    assert confidence.portion is ConfidenceLevel.LOW
    assert confidence.label is ConfidenceLevel.LOW
    assert any("one labeled serving; amount eaten unknown" in r for r in confidence.reasons)
    assert not any("image-only estimate" in r for r in confidence.reasons)
    assert confidence.probability is None
