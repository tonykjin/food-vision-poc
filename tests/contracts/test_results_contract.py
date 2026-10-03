"""Schema-level rules for the shared result contract (plan §7)."""

import math

import pytest
from pydantic import ValidationError

from foodvision.contracts.errors import ErrorCode, ErrorDetail
from foodvision.contracts.requests import AnalysisContext, InputMode
from foodvision.contracts.results import (
    AnalysisResult,
    Confidence,
    ConfidenceType,
    FoodSource,
    Nutrients,
    PortionMethod,
    ResultItem,
    ResultStatus,
    Totals,
    TotalsStatus,
)

SHA = "0" * 64


def resolved_item(**overrides):
    fields = dict(
        name="cooked white rice",
        preparation="cooked",
        resolved=True,
        portion_g=180,
        portion_method=PortionMethod.IMAGE_ESTIMATED,
        food_source=FoodSource.USDA,
        food_id="fdc:test-id",
        nutrients=Nutrients(energy_kcal=1, protein_g=1, carbohydrate_g=1, fat_g=1),
    )
    return ResultItem(**(fields | overrides))


def complete_totals():
    nutrients = Nutrients(energy_kcal=1, protein_g=1, carbohydrate_g=1, fat_g=1)
    return Totals(status=TotalsStatus.COMPLETE, nutrients=nutrients, included_items=1)


def result(**overrides):
    fields = dict(scan_id="s", pipeline_id="B_grounded", is_mock=False, status="partial")
    return AnalysisResult(**(fields | overrides))


def test_plan_section_7_shape_validates():
    unresolved = ResultItem(
        name="cooked white rice",
        preparation="cooked",
        resolved=False,
        portion_g=180,
        portion_method=PortionMethod.IMAGE_ESTIMATED,
        uncertainty_reasons=["portion not measured"],
    )
    out = result(
        items=[unresolved],
        confidence=Confidence(type=ConfidenceType.HEURISTIC_UNCALIBRATED, label="medium"),
        warnings=["Example schema only; not a calculated result"],
    )
    assert out.schema_version == "1.0"
    assert out.totals.status is TotalsStatus.UNAVAILABLE
    assert out.confidence.probability is None


def test_complete_result_with_resolved_items_validates():
    out = result(status="complete", items=[resolved_item()], totals=complete_totals())
    assert out.status is ResultStatus.COMPLETE


@pytest.mark.parametrize("status", ["done", "COMPLETE", "ok"])
def test_unsupported_status_rejected(status):
    with pytest.raises(ValidationError):
        result(status=status)


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        result(accuracy_percent=95)


@pytest.mark.parametrize("portion", [-1, 0, math.nan, math.inf])
def test_bad_portion_rejected(portion):
    with pytest.raises(ValidationError):
        resolved_item(portion_g=portion)


@pytest.mark.parametrize("value", [-0.1, math.nan, math.inf])
def test_bad_nutrient_rejected(value):
    with pytest.raises(ValidationError):
        Nutrients(energy_kcal=value)


def test_resolved_grounded_item_needs_food_id():
    with pytest.raises(ValidationError, match="food_id"):
        resolved_item(food_id=None)


def test_resolved_item_needs_known_portion_method():
    with pytest.raises(ValidationError, match="portion"):
        resolved_item(portion_method=PortionMethod.UNKNOWN)


def test_complete_with_unresolved_item_rejected():
    items = [resolved_item(), ResultItem(name="sauce", resolved=False)]
    with pytest.raises(ValidationError, match="complete"):
        result(status="complete", items=items, totals=complete_totals())


def test_partial_result_cannot_claim_complete_totals():
    with pytest.raises(ValidationError):
        result(status="partial", items=[resolved_item()], totals=complete_totals())


def test_complete_totals_cannot_have_unknown_nutrients():
    with pytest.raises(ValidationError):
        Totals(status=TotalsStatus.COMPLETE, nutrients=Nutrients(energy_kcal=100))


def test_mock_result_can_never_be_complete():
    with pytest.raises(ValidationError, match="MOCK"):
        result(status="complete", is_mock=True, items=[resolved_item()], totals=complete_totals())


def test_failed_needs_error_and_others_cannot_have_one():
    with pytest.raises(ValidationError):
        result(status="failed")
    error = ErrorDetail(code=ErrorCode.TIMEOUT, message="deadline", retryable=True)
    assert result(status="failed", error=error).error.code is ErrorCode.TIMEOUT
    with pytest.raises(ValidationError):
        result(status="partial", error=error)


def test_abstained_must_have_unavailable_totals():
    partial = Totals(status=TotalsStatus.PARTIAL, nutrients=Nutrients(energy_kcal=5))
    with pytest.raises(ValidationError):
        result(status="abstained", totals=partial)


def test_probability_requires_calibration():
    with pytest.raises(ValidationError, match="calibration"):
        Confidence(type=ConfidenceType.HEURISTIC_UNCALIBRATED, probability=0.8)
    calibrated = Confidence(
        type=ConfidenceType.EMPIRICAL_CALIBRATED, probability=0.8, calibration_version="cal-v1"
    )
    assert calibrated.probability == 0.8


def test_unsupported_error_code_rejected():
    with pytest.raises(ValidationError):
        ErrorDetail(code="unknown_failure", message="x")


def test_known_weight_only_in_diagnostic_mode():
    with pytest.raises(ValidationError, match="diagnostic"):
        AnalysisContext(scan_id="s", original_sha256=SHA, pipeline_id="B", known_weight_g=150)
    ctx = AnalysisContext(
        scan_id="s",
        original_sha256=SHA,
        pipeline_id="B",
        input_mode=InputMode.KNOWN_WEIGHT_DIAGNOSTIC,
        known_weight_g=150,
    )
    assert ctx.known_weight_g == 150


def test_context_rejects_malformed_hash():
    with pytest.raises(ValidationError):
        AnalysisContext(scan_id="s", original_sha256="abc", pipeline_id="B")
