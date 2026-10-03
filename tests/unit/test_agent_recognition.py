"""Recognition-only pipeline: hypotheses become unresolved, labeled items (SYNTHETIC data)."""

import json

from tests.unit.test_claude_vision import GOOD, IMAGE, ITEM, message, provider

from foodvision.contracts.errors import ErrorCode
from foodvision.contracts.requests import AnalysisContext
from foodvision.contracts.results import ResultStatus, TotalsStatus
from foodvision.measurement.budget import BudgetPolicy
from foodvision.measurement.clock import ManualClock
from foodvision.measurement.spans import ScanRecorder
from foodvision.pipelines.agent_recognition import RECOGNITION_ONLY, RecognitionOnlyPipeline

CONTEXT = AnalysisContext(scan_id="s", original_sha256="0" * 64, pipeline_id="B_recognition_only")


def run(outcomes, **config):
    vision, _ = provider(outcomes, **config)
    rec = ScanRecorder("s", "B", budget=BudgetPolicy(max_model_calls=2), clock=ManualClock())
    return RecognitionOnlyPipeline(vision).analyze(IMAGE, CONTEXT, rec)


def test_hypotheses_are_unresolved_with_unknown_nutrients_and_labeled_assumptions():
    result = run([message()])
    assert result.status is ResultStatus.PARTIAL
    assert result.totals.status is TotalsStatus.UNAVAILABLE
    (item,) = result.items
    assert not item.resolved and item.nutrients.missing() == [
        "energy_kcal",
        "protein_g",
        "carbohydrate_g",
        "fat_g",
    ]
    assert item.portion_g == 150 and item.preparation == "grilled"
    assert (item.portion_scenarios.low_g, item.portion_scenarios.high_g) == (120, 200)
    assert "not a confidence interval" in item.portion_scenarios.label
    assert item.alternatives == ["SYNTHETIC alternative"]
    assert any("not yet matched" in r for r in item.uncertainty_reasons)
    assert RECOGNITION_ONLY in result.warnings
    assert result.confidence.probability is None  # no self-confidence turned into accuracy
    assert result.model_provenance.model_served == "claude-opus-5-5"


def test_unknown_preparation_is_not_guessed():
    payload = {**GOOD, "items": [{**ITEM, "preparation": "unknown"}]}
    (item,) = run([message(payload=payload)]).items
    assert item.preparation is None


def test_no_food_abstains():
    payload = {
        "image_assessment": {
            "is_food_image": False,
            "multiple_foods": False,
            "notes": "SYNTHETIC label only",
        },
        "items": [],
    }
    result = run([message(payload=payload)])
    assert result.status is ResultStatus.ABSTAINED and result.items == []
    assert result.error is None


def test_refusal_is_a_typed_failure_without_fabricated_items():
    result = run([message(stop_reason="refusal")])
    assert result.status is ResultStatus.FAILED and result.items == []
    assert result.error.code is ErrorCode.REFUSED


def test_fallback_served_is_warned():
    result = run([message(model="claude-sonnet-5-5", fallback=True)])
    assert any("fallback model claude-sonnet-5-5" in w for w in result.warnings)
    assert result.model_provenance.fallback_served


def test_composite_dish_reason():
    payload = {**GOOD, "items": [{**ITEM, "is_composite": True}]}
    (item,) = run([message(payload=payload)]).items
    assert item.uncertainty_reasons[0].startswith("composite dish")


def test_result_json_has_no_nutrient_numbers():
    body = json.loads(run([message()]).model_dump_json())
    assert all(v is None for v in body["items"][0]["nutrients"].values())
