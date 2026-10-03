"""A_native normalization on SYNTHETIC protocol fixtures (shape only, not fatsecret output)."""

import json
from pathlib import Path

import pytest

from foodvision.contracts.errors import ErrorCode
from foodvision.contracts.requests import AnalysisContext
from foodvision.contracts.results import ResultStatus, TotalsStatus
from foodvision.pipelines.provider_native import normalize_response

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "fatsecret"
CONTEXT = AnalysisContext(scan_id="scan-1", original_sha256="0" * 64, pipeline_id="A_native")


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_eaten_totals_are_used_as_is_never_scaled_twice():
    result = normalize_response(load("two_items.json"), CONTEXT)
    a, b = result.items
    # Eaten total is 300 kcal for 150 g. The per-serving record says 150 kcal per serving
    # with 2 units suggested: scaling it again would give 600.
    assert a.nutrients.energy_kcal == 300.0 and a.nutrients.protein_g == 10.0
    assert a.portion_g == 150.0 and a.resolved
    assert (a.food_id, a.serving_id) == ("9000001", "8000001")


def test_blank_and_negative_values_become_unknown_and_totals_partial():
    result = normalize_response(load("two_items.json"), CONTEXT)
    b = result.items[1]
    assert b.nutrients.protein_g is None and b.nutrients.fat_g is None
    assert b.nutrients.energy_kcal == 120.0
    assert any("missing or invalid" in r for r in b.uncertainty_reasons)
    assert result.status is ResultStatus.PARTIAL
    assert result.totals.status is TotalsStatus.PARTIAL
    assert result.totals.nutrients.energy_kcal == 420.0  # 300 + 120
    assert result.totals.nutrients.protein_g is None  # unknown, not 10


def test_per_serving_record_scaled_exactly_once_when_totals_absent():
    (item,) = normalize_response(load("per_serving_only.json"), CONTEXT).items
    # 120 kcal per 1 serving of 40 g, 1.5 units suggested -> 180 kcal, 60 g.
    assert item.nutrients.energy_kcal == pytest.approx(180.0)
    assert item.nutrients.fat_g == pytest.approx(7.5)
    assert item.portion_g == pytest.approx(60.0)
    assert any("computed once" in r for r in item.uncertainty_reasons)


def test_ml_portion_has_no_grams_and_is_not_counted():
    result = normalize_response(load("ml_portion.json"), CONTEXT)
    (item,) = result.items
    assert not item.resolved and item.portion_g is None
    assert result.totals.status is TotalsStatus.UNAVAILABLE
    assert result.status is ResultStatus.PARTIAL


def test_complete_when_every_item_is_resolved_and_known():
    payload = load("two_items.json")
    payload["food_response"] = payload["food_response"][:1]
    result = normalize_response(payload, CONTEXT)
    assert result.status is ResultStatus.COMPLETE
    assert result.totals.nutrients.energy_kcal == 300.0


@pytest.mark.parametrize("fixture", ["empty.json", "error_211.json"])
def test_no_foods_and_label_only_rejection_are_typed(fixture):
    result = normalize_response(load(fixture), CONTEXT)
    assert result.status is ResultStatus.FAILED
    assert result.error.code is ErrorCode.EMPTY_RECOGNITION
    assert result.totals.status is TotalsStatus.UNAVAILABLE


def test_label_rejection_message_is_ours_not_the_providers():
    result = normalize_response(load("error_211.json"), CONTEXT)
    assert "211" in result.error.message and "label" in result.error.message


def test_missing_food_response_is_invalid_schema():
    result = normalize_response({"unexpected": True}, CONTEXT)
    assert result.error.code is ErrorCode.INVALID_SCHEMA


def test_every_result_carries_the_restricted_notice():
    for name in ("two_items.json", "empty.json"):
        assert any("not stored" in w for w in normalize_response(load(name), CONTEXT).warnings)
