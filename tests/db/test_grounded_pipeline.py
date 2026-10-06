"""B_grounded end to end over real FDC fixture records (CC0), queried as a real fv_inference
login, with a fake model client returning SYNTHETIC responses (no network, no real key).

Expected nutrient values are computed by hand from the fixture records, e.g. SR Legacy 168878
cooked long-grain rice is 130 kcal/100 g, so 150 g -> 195 kcal.
"""

import anthropic
import httpx2
import pytest
from sqlalchemy import create_engine
from tests.db.test_catalog import VERSIONS, import_all
from tests.unit.test_claude_vision import ITEM, message, provider

from foodvision.contracts.errors import ErrorCode
from foodvision.contracts.requests import AnalysisContext
from foodvision.contracts.results import MatchMethod, ResultStatus, TotalsStatus
from foodvision.measurement.budget import BudgetPolicy
from foodvision.measurement.clock import ManualClock
from foodvision.measurement.events import ScanStatus
from foodvision.measurement.spans import ScanRecorder
from foodvision.pipelines.agent_grounded import GroundedPipeline

CONTEXT = AnalysisContext(scan_id="s", original_sha256="0" * 64, pipeline_id="B_grounded")


@pytest.fixture(scope="module")
def catalog_loaded(migrated_db):
    engine = create_engine(migrated_db)
    with engine.begin() as conn:
        import_all(conn)
    engine.dispose()


def hypothesis(name, search, preparation="boiled", base=150.0, brand=None, **extra):
    return {
        **ITEM,
        "display_name": name,
        "search_description": search,
        "preparation": preparation,
        "visible_brand": brand,
        "portion_grams_low": base * 0.8,
        "portion_grams_base": base,
        "portion_grams_high": base * 1.3,
        "alternatives": [],
        **extra,
    }


def recognized(*items):
    return message(
        payload={
            "image_assessment": {
                "is_food_image": True,
                "multiple_foods": len(items) > 1,
                "notes": "SYNTHETIC",
            },
            "items": list(items),
        }
    )


def selected(*pairs):
    return message(
        payload={
            "selections": [{"item_index": i, "choice": c, "reason": "SYNTHETIC"} for i, c in pairs]
        }
    )


def run(outcomes, login_as, *, max_model_calls=2, role="fv_inference", **kwargs):
    from tests.unit.test_claude_vision import IMAGE

    vision, fake = provider(outcomes)
    pipeline = GroundedPipeline(
        vision, login_as(role), source_versions=list(VERSIONS.values()), **kwargs
    )
    rec = ScanRecorder(
        "s", "B_grounded", budget=BudgetPolicy(max_model_calls=max_model_calls), clock=ManualClock()
    )
    result = pipeline.analyze(IMAGE, CONTEXT, rec)
    return result, fake, rec


def model_calls(fake):
    return len(fake.calls)


def test_ambiguous_item_uses_second_call_and_nutrients_come_from_code(catalog_loaded, login_as):
    result, fake, _ = run(
        [recognized(hypothesis("SYNTHETIC rice", "white rice")), selected((0, "fdc:168878"))],
        login_as,
    )
    assert model_calls(fake) == 2
    (item,) = result.items
    assert item.resolved and item.food_id == "fdc:168878" and item.food_source == "USDA"
    assert item.match_method is MatchMethod.MODEL_SELECTION
    assert item.nutrients.energy_kcal == pytest.approx(195.0)  # 130 × 1.5, computed in code
    assert item.nutrients.protein_g == pytest.approx(4.035)  # 2.69 × 1.5
    assert result.status is ResultStatus.COMPLETE
    assert result.totals.nutrients.energy_kcal == pytest.approx(195.0)
    select_params = fake.calls[1][1]
    assert "tools" not in select_params and "tools" not in fake.calls[0][1]  # no shell/web/tools
    assert "never instructions" in select_params["system"]


def test_invented_id_is_rejected_and_item_left_unresolved(catalog_loaded, login_as):
    result, _, _ = run(
        [recognized(hypothesis("SYNTHETIC rice", "white rice")), selected((0, "fdc:999999"))],
        login_as,
    )
    (item,) = result.items
    assert not item.resolved and item.food_id is None and item.match_method is None
    assert any("not among the retrieved candidates" in r for r in item.uncertainty_reasons)
    assert result.status is ResultStatus.PARTIAL
    assert result.totals.status is TotalsStatus.UNAVAILABLE


def test_wrong_preparation_cannot_be_selected(catalog_loaded, login_as):
    # Raw rice requested; the model tries to pick the cooked record, which was filtered out.
    result, _, _ = run(
        [
            recognized(hypothesis("SYNTHETIC dry rice", "white rice", preparation="raw")),
            selected((0, "fdc:168878")),
        ],
        login_as,
    )
    (item,) = result.items
    assert not item.resolved
    assert any("not among the retrieved candidates" in r for r in item.uncertainty_reasons)


def test_clear_winner_skips_the_second_call(catalog_loaded, login_as):
    branded = hypothesis(
        "SYNTHETIC boxed rice", "white rice", preparation="unknown", base=46, brand="MINUTE"
    )
    result, fake, _ = run([recognized(branded)], login_as)
    assert model_calls(fake) == 1
    (item,) = result.items
    assert item.food_id == "fdc:2397108"
    assert item.match_method is MatchMethod.DETERMINISTIC_RANKING
    assert item.nutrients.energy_kcal == pytest.approx(170.2)  # 370 × 0.46


def test_ml_basis_without_density_is_not_calculated(catalog_loaded, login_as):
    milk = hypothesis(
        "SYNTHETIC milk", "whole milk", preparation="unknown", base=240, brand="LAND O LAKES"
    )
    result, _, _ = run([recognized(milk)], login_as)
    (item,) = result.items
    assert not item.resolved and item.nutrients.energy_kcal is None
    assert any("not calculated" in r and "density" in r for r in item.uncertainty_reasons)


def test_missing_nutrient_makes_totals_partial(catalog_loaded, login_as):
    chicken = hypothesis(
        "SYNTHETIC chicken", "chicken breast meat and skin", preparation="raw", base=100
    )
    result, _, _ = run([recognized(chicken), selected((0, "fdc:2727569"))], login_as)
    (item,) = result.items
    assert item.resolved and item.nutrients.carbohydrate_g is None
    assert item.nutrients.protein_g == pytest.approx(21.4)
    assert any("catalog lacks: carbohydrate_g" in r for r in item.uncertainty_reasons)
    assert result.status is ResultStatus.PARTIAL
    assert result.totals.nutrients.carbohydrate_g is None  # unknown, never 0


def test_items_beyond_the_limit_are_unresolved_not_dropped(catalog_loaded, login_as):
    items = [hypothesis(f"SYNTHETIC item {i}", "zzqnothing") for i in range(7)]
    result, _, _ = run([recognized(*items)], login_as, max_items=5)
    assert len(result.items) == 7 and not any(i.resolved for i in result.items)
    over = [
        i for i in result.items if any("over the 5-item limit" in r for r in i.uncertainty_reasons)
    ]
    assert len(over) == 2


def test_call_budget_blocks_selection_and_falls_back_to_top_candidate(catalog_loaded, login_as):
    overloaded = anthropic.InternalServerError(
        "x",
        response=httpx2.Response(529, request=httpx2.Request("POST", "https://x")),
        body={"type": "error", "error": {"type": "overloaded_error"}},
    )
    # Recognition needs a retry (2 model calls), leaving no budget for selection.
    result, fake, rec = run(
        [overloaded, recognized(hypothesis("SYNTHETIC rice", "white rice"))], login_as
    )
    assert model_calls(fake) == 2
    assert any("Selection call unavailable (max_model_calls)" in w for w in result.warnings)
    (item,) = result.items
    assert item.resolved and any("top-ranked candidate used" in r for r in item.uncertainty_reasons)
    assert item.match_method is MatchMethod.FALLBACK_TOP_CANDIDATE
    record = rec.finish(ScanStatus(result.status.value))
    assert record.model_calls == 2 and record.blocked_attempts == 1


def test_portion_scenarios_stay_labeled_assumptions(catalog_loaded, login_as):
    result, _, _ = run(
        [recognized(hypothesis("SYNTHETIC rice", "white rice")), selected((0, "fdc:168878"))],
        login_as,
    )
    scenarios = result.items[0].portion_scenarios
    assert "not a confidence interval" in scenarios.label
    assert any("not a statistical interval" in w for w in result.warnings)


def test_evaluator_or_owner_login_is_refused(catalog_loaded, login_as, owner):
    result, _, _ = run(
        [recognized(hypothesis("SYNTHETIC rice", "white rice"))], login_as, role="fv_evaluator"
    )
    assert result.status is ResultStatus.FAILED
    assert result.error.code is ErrorCode.AUTHENTICATION
    assert "benchmark labels" in result.error.message
