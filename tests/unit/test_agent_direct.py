"""B_direct diagnostic pipeline against a fake SDK client (POC-14). SYNTHETIC responses only."""

import copy

import pytest
from pydantic import SecretStr
from tests.unit.test_claude_vision import GOOD, IMAGE, ITEM, message, provider, recorder

from foodvision.cli import benchmark_run
from foodvision.config import AgentSettings, AppKind
from foodvision.contracts.requests import AnalysisContext
from foodvision.contracts.results import ConfidenceLevel, FoodSource, ResultStatus
from foodvision.measurement.confidence import assess_confidence
from foodvision.pipelines.agent_direct import DIRECT_LABEL, DirectPipeline
from foodvision.recognition.direct import DIRECT_PROMPT_VERSION, DIRECT_SCHEMA
from foodvision.recognition.hypotheses import load_prompt
from foodvision.ui.result_view import source_text

ESTIMATE = {"energy_kcal": 250.0, "protein_g": 30.0, "carbohydrate_g": 0.0, "fat_g": 12.0}


def direct_payload(*estimates):
    items = []
    for i, est in enumerate(estimates):
        item = copy.deepcopy(ITEM)
        item["display_name"] = f"SYNTHETIC item {i}"
        item["estimated_nutrients"] = est
        items.append(item)
    return {**GOOD, "items": items}


CONTEXT = AnalysisContext(
    scan_id="s",
    original_sha256=IMAGE.original_sha256,
    processed_sha256=IMAGE.processed_sha256,
    preprocessing_version=IMAGE.transform_version,
    pipeline_id="B_direct",
)


def run(payload):
    vision, fake = provider([message(payload=payload)])
    result = DirectPipeline(vision).analyze(IMAGE, CONTEXT, recorder())
    return result, fake


def test_one_call_with_the_direct_prompt_and_schema():
    result, fake = run(direct_payload(ESTIMATE))
    ((_, params),) = fake.calls
    assert params["system"] == load_prompt(DIRECT_PROMPT_VERSION)[0]
    assert params["output_config"]["format"]["schema"] == DIRECT_SCHEMA
    assert "tools" not in params
    assert result.model_provenance.prompt_version == DIRECT_PROMPT_VERSION


def test_items_are_labeled_model_estimates_and_totals_are_summed_in_code():
    result, _ = run(direct_payload(ESTIMATE, {**ESTIMATE, "energy_kcal": 100.0}))
    assert result.pipeline_id == "B_direct" and result.status is ResultStatus.COMPLETE
    assert result.configuration_id.startswith("B_direct:anthropic:claude-opus-5-5:")
    assert DIRECT_PROMPT_VERSION in result.configuration_id
    assert DIRECT_LABEL in result.warnings
    assert all(
        i.food_source is FoodSource.MODEL_ESTIMATE and i.food_id is None for i in result.items
    )
    assert result.totals.nutrients.energy_kcal == 350.0
    assert source_text(result.items[0]) == "model estimate (no database grounding)"


def test_missing_estimate_stays_unknown_and_makes_totals_partial():
    result, _ = run(direct_payload(ESTIMATE, {**ESTIMATE, "fat_g": None}))
    assert result.status is ResultStatus.PARTIAL
    assert result.totals.nutrients.fat_g is None  # unknown, never 0
    assert result.totals.nutrients.energy_kcal == 500.0


def test_model_estimates_are_low_nutrition_match_confidence():
    result, _ = run(direct_payload(ESTIMATE))
    confidence = assess_confidence(result)
    assert confidence.nutrition_match is ConfidenceLevel.LOW
    assert any("estimated by the model" in r for r in confidence.reasons)


def test_no_food_abstains_and_out_of_range_estimate_fails_typed():
    no_food = {
        "image_assessment": {**GOOD["image_assessment"], "is_food_image": False},
        "items": [],
    }
    assert run(no_food)[0].status is ResultStatus.ABSTAINED
    failed, _ = run(direct_payload({**ESTIMATE, "energy_kcal": 6000.0}))
    assert failed.status is ResultStatus.FAILED and failed.error.code == "invalid_schema"
    assert "items.0.estimated_nutrients.energy_kcal" in failed.error.message


def test_direct_mode_is_selected_by_pipeline_mode_and_health_reports_it():
    from fastapi.testclient import TestClient

    from foodvision.api.factory import create_app

    settings = AgentSettings(
        _env_file=None, anthropic_api_key=SecretStr("SENTINEL"), pipeline_mode="direct"
    )
    health = TestClient(create_app(AppKind.AGENT, settings)).get("/health").json()
    assert health["pipeline_id"] == "B_direct" and health["ready"]


@pytest.mark.parametrize(
    ("config", "pipeline_id"), [("B_direct", "B_direct"), ("B_grounded", "B_grounded")]
)
def test_benchmark_builds_each_b_mode_from_one_agent_config(monkeypatch, config, pipeline_id):
    base = AgentSettings(
        _env_file=None,
        anthropic_api_key=SecretStr("SENTINEL"),
        database_url=SecretStr("postgresql+psycopg://x:y@127.0.0.1:1/none"),
    )
    monkeypatch.setattr(benchmark_run, "load_settings", lambda kind: base)
    pipeline, _, _ = benchmark_run._pipeline(config)
    assert pipeline.pipeline_id == pipeline_id
