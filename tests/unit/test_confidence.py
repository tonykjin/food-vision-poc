"""Heuristic confidence rules (POC-11). All results are SYNTHETIC; no values are real foods."""

import pytest

from foodvision.contracts.errors import ErrorCode, ErrorDetail
from foodvision.contracts.results import (
    AnalysisResult,
    Confidence,
    ConfidenceLevel,
    ConfidenceType,
    FoodSource,
    MatchMethod,
    Nutrients,
    PortionMethod,
    PortionScenarios,
    ResultItem,
    ResultStatus,
)
from foodvision.measurement.confidence import RULES_VERSION, assess_confidence
from foodvision.nutrition.calculator import sum_totals

FULL = Nutrients(energy_kcal=100, protein_g=1, carbohydrate_g=2, fat_g=3)
LOW, MEDIUM, HIGH = ConfidenceLevel.LOW, ConfidenceLevel.MEDIUM, ConfidenceLevel.HIGH


def item(**overrides) -> ResultItem:
    fields = dict(
        name="SYNTHETIC food",
        preparation="boiled",
        resolved=True,
        portion_g=150,
        portion_method=PortionMethod.IMAGE_ESTIMATED,
        food_source=FoodSource.USDA,
        food_id="fdc:1",
        match_method=MatchMethod.DETERMINISTIC_RANKING,
        nutrients=FULL,
        portion_scenarios=PortionScenarios(low_g=120, base_g=150, high_g=180),
    )
    fields.update(overrides)
    return ResultItem(**fields)


def result(*items: ResultItem, **overrides) -> AnalysisResult:
    totals = sum_totals([i.nutrients if i.resolved else None for i in items])
    status = ResultStatus.COMPLETE if totals.status == "complete" else ResultStatus.PARTIAL
    fields = dict(
        scan_id="s",
        pipeline_id="X",
        is_mock=False,
        status=status,
        items=list(items),
        totals=totals,
    )
    fields.update(overrides)
    return AnalysisResult(**fields)


def test_clean_grounded_item_is_capped_at_medium_by_image_only_portion():
    c = assess_confidence(result(item()))
    assert c.type is ConfidenceType.HEURISTIC_UNCALIBRATED
    assert (c.identity, c.portion, c.nutrition_match, c.label) == (HIGH, MEDIUM, HIGH, MEDIUM)
    assert c.probability is None and c.calibration_version is None
    assert c.rules_version == RULES_VERSION
    assert any("image-only estimate" in r for r in c.reasons)


def test_only_measured_weight_allows_high_portion():
    measured = item(portion_method=PortionMethod.MEASURED_WEIGHT, portion_scenarios=None)
    assert assess_confidence(result(measured)).portion is HIGH


@pytest.mark.parametrize(
    ("overrides", "dimension", "expected"),
    [
        ({"alternatives": ["other food"]}, "identity", MEDIUM),
        ({"preparation": None}, "identity", MEDIUM),
        (
            {"portion_scenarios": PortionScenarios(low_g=50, base_g=150, high_g=300)},
            "portion",
            LOW,
        ),
        (
            {
                "resolved": False,
                "food_source": FoodSource.NONE,
                "food_id": None,
                "match_method": None,
                "nutrients": Nutrients(),
            },
            "nutrition_match",
            LOW,
        ),
        ({"nutrients": Nutrients(energy_kcal=100, protein_g=1, fat_g=3)}, "nutrition_match", LOW),
        ({"match_method": MatchMethod.FALLBACK_TOP_CANDIDATE}, "nutrition_match", LOW),
        ({"match_method": MatchMethod.MODEL_SELECTION}, "nutrition_match", MEDIUM),
        (
            {"food_source": FoodSource.FATSECRET, "match_method": MatchMethod.PROVIDER},
            "nutrition_match",
            MEDIUM,
        ),
    ],
)
def test_each_rule_lowers_its_dimension_with_a_reason(overrides, dimension, expected):
    c = assess_confidence(result(item(**overrides)))
    assert getattr(c, dimension) is expected
    assert any(r.startswith(dimension.replace("_", " ")) for r in c.reasons)


def test_unknown_portion_is_low():
    unknown = item(
        resolved=False,
        portion_g=None,
        portion_method=PortionMethod.UNKNOWN,
        portion_scenarios=None,
        food_source=FoodSource.NONE,
        food_id=None,
        match_method=None,
        nutrients=Nutrients(),
    )
    assert assess_confidence(result(unknown)).portion is LOW


def test_scan_takes_the_worst_item_and_label_is_the_lowest_dimension():
    c = assess_confidence(result(item(), item(match_method=MatchMethod.FALLBACK_TOP_CANDIDATE)))
    assert c.nutrition_match is LOW and c.label is LOW


def test_many_items_cap_identity_at_medium():
    c = assess_confidence(result(*[item(name=f"SYNTHETIC {i}") for i in range(4)]))
    assert c.identity is MEDIUM
    assert any("4 items in one image" in r for r in c.reasons)


@pytest.mark.parametrize(
    "outcome",
    [
        dict(status=ResultStatus.FAILED, error=ErrorDetail(code=ErrorCode.TIMEOUT, message="x")),
        dict(status=ResultStatus.ABSTAINED),
    ],
)
def test_failed_and_abstained_are_not_assessed(outcome):
    r = AnalysisResult(scan_id="s", pipeline_id="X", is_mock=False, **outcome)
    c = assess_confidence(r)
    assert c.type is ConfidenceType.UNAVAILABLE and c.label is None and c.reasons


def test_mock_is_never_assessed():
    mock = item(
        resolved=False,
        food_source=FoodSource.MOCK,
        food_id=None,
        match_method=None,
        nutrients=Nutrients(),
    )
    c = assess_confidence(result(mock, is_mock=True))
    assert c.type is ConfidenceType.UNAVAILABLE and c.identity is None


def test_rules_ignore_model_self_ratings_and_free_text():
    # Reasons/evidence text claiming certainty must not raise any level.
    claimy = item(
        alternatives=["other"],
        evidence="model is 99% certain",
        uncertainty_reasons=["confidence: very high"],
    )
    assert assess_confidence(result(claimy)).identity is MEDIUM


def test_unavailable_confidence_cannot_carry_levels():
    with pytest.raises(ValueError, match="must not carry levels"):
        Confidence(type=ConfidenceType.UNAVAILABLE, label=LOW)
