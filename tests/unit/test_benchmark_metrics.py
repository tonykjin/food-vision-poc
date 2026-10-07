"""Frozen benchmark metrics against hand-computed expectations (POC-13). SYNTHETIC data only."""

import pytest

from foodvision.benchmark.metrics import (
    Attempt,
    Reference,
    agreement,
    config_metrics,
    errors,
    group_bootstrap,
    is_useful,
    map_items,
    percentile,
    within_tolerance,
)
from foodvision.benchmark.report import UNAVAILABLE, build_report
from foodvision.contracts.errors import ErrorCode, ErrorDetail
from foodvision.contracts.results import (
    AnalysisResult,
    FoodSource,
    Nutrients,
    PortionMethod,
    ResultItem,
    ResultStatus,
)
from foodvision.measurement.storage_policy import Purpose, StoragePolicy
from foodvision.nutrition.calculator import sum_totals

REF = Reference(
    "g1",
    "separated_plate",
    "A",
    "estimate",
    Nutrients(energy_kcal=500, protein_g=30, carbohydrate_g=50, fat_g=20),
    (("chicken breast, grilled", "grilled", 150.0), ("rice, white, cooked", "boiled", 200.0)),
)
ZERO_FAT = Reference(
    "g0",
    "single_generic",
    "A",
    "estimate",
    Nutrients(energy_kcal=200, protein_g=2, carbohydrate_g=45, fat_g=0),
)
GRADE_C = Reference(
    "gc",
    "single_generic",
    "C",
    "estimate",
    Nutrients(energy_kcal=300, protein_g=10, carbohydrate_g=40, fat_g=10),
)
ABSTAIN = Reference("ga", "difficult_unsupported", "B", "abstain", None)
REFS = {r.group_id: r for r in (REF, ZERO_FAT, GRADE_C, ABSTAIN)}


def result(status="complete", energy=500.0, protein=30.0, carbs=50.0, fat=20.0, items=None):
    if status == "failed":
        return AnalysisResult(
            scan_id="s",
            pipeline_id="X",
            is_mock=False,
            status=ResultStatus.FAILED,
            error=ErrorDetail(code=ErrorCode.TIMEOUT, message="t"),
        )
    if status == "abstained":
        return AnalysisResult(scan_id="s", pipeline_id="X", is_mock=False, status=status)
    nutrients = Nutrients(energy_kcal=energy, protein_g=protein, carbohydrate_g=carbs, fat_g=fat)
    items = items or [
        ResultItem(
            name="SYNTHETIC grilled chicken breast",
            preparation="grilled",
            resolved=True,
            portion_g=160,
            portion_method=PortionMethod.IMAGE_ESTIMATED,
            food_source=FoodSource.USDA,
            food_id="fdc:1",
            nutrients=nutrients,
        )
    ]
    if status == "partial":
        items.append(ResultItem(name="SYNTHETIC unknown", resolved=False))
    totals = sum_totals([i.nutrients if i.resolved else None for i in items])
    return AnalysisResult(
        scan_id="s", pipeline_id="X", is_mock=False, status=status, items=items, totals=totals
    )


def attempt(
    group="g1",
    status="complete",
    config="X",
    sample=None,
    repeat=0,
    ms=100.0,
    cost=0.01,
    code=None,
    **values,
):
    res = result(status, **values) if status != "none" else None
    return Attempt(
        config=config,
        group_id=group,
        sample_id=sample or f"{group}:p",
        repeat=repeat,
        status=status,
        error_code=code or ("timeout" if status == "failed" else None),
        server_total_ms=ms,
        known_cost_usd=cost or 0.0,
        estimated_cost_usd=cost,
        result=res,
    )


# --- single formulas ------------------------------------------------------------------------


def test_errors_and_relative_only_above_the_floor():
    assert errors(540, 500, "energy_kcal") == (40, 40, pytest.approx(0.08))
    assert errors(460, 500, "energy_kcal")[1] == -40  # signed keeps the direction
    assert errors(2, 0, "fat_g") == (2, 2, None)  # zero target: no division
    assert errors(4, 2, "protein_g")[2] is None  # 2 g is below the 3 g floor
    assert errors(4, 3, "protein_g")[2] == pytest.approx(1 / 3)


def test_tolerance_uses_the_larger_of_floor_and_percentage():
    assert within_tolerance(549.9, 500, "energy_kcal")  # floor 50 < 15% (75)
    assert not within_tolerance(576, 500, "energy_kcal")
    assert within_tolerance(3, 0, "fat_g") and not within_tolerance(3.1, 0, "fat_g")


def test_useful_event_needs_complete_known_totals_within_tolerance():
    assert is_useful(attempt(energy=540, protein=33, carbs=55, fat=23), REF)
    assert not is_useful(attempt(energy=600), REF)  # energy off by 100 > 75
    assert not is_useful(attempt(fat=24.1), REF)  # 4.1 > max(3, 4)
    assert not is_useful(attempt(status="partial"), REF)  # partial is never whole-meal
    assert not is_useful(attempt(group="gc"), GRADE_C)  # grade C isn't scorable


def test_percentile_is_linear_type_7():
    assert percentile([100, 200, 300, 400], 0.5) == 250
    assert percentile([100, 200, 300, 400], 0.95) == pytest.approx(385)
    assert percentile([], 0.5) is None


def test_item_mapping_is_one_to_one_lexical():
    pred = [
        ("grilled chicken breast", "grilled", 160),
        ("white rice", "boiled", 180),
        ("broccoli", "steamed", 50),
    ]
    assert sorted(map_items(pred, REF.components)) == [(0, 0), (1, 1)]


# --- configuration metrics ------------------------------------------------------------------


def test_known_predictions_give_exact_metrics_with_failures_in_the_denominator():
    attempts = [
        attempt(energy=540, protein=33, carbs=55, fat=23, ms=100),  # useful
        attempt(energy=600, ms=200, repeat=1),  # complete but not useful
        attempt(status="failed", ms=300, repeat=2),
        attempt(status="partial", ms=400, sample="g1:q"),
        attempt(group="gc", ms=500),  # grade C: not in the useful denominator
    ]
    m = config_metrics("X", attempts, REFS)
    assert m.status_counts == {"complete": 3, "partial": 1, "abstained": 0, "failed": 1}
    assert m.useful["denominator_attempts"] == 4  # every g1 attempt, failure included
    assert m.useful["useful_attempts"] == 1
    assert m.useful["pass_rate"] == 0.25
    energy = m.scorable_error["energy_kcal"]
    assert energy["n_scorable"] == 2  # complete g1 results only
    assert energy["mean_abs"] == 70  # (40 + 100) / 2
    assert energy["mean_signed"] == 70
    assert energy["median_relative"] == pytest.approx(0.14)  # median(0.08, 0.20)
    assert m.latency_ms["p50_all"] == 300 and m.latency_ms["p95_all"] == pytest.approx(480)
    assert m.partial["partial_attempts"] == 1 and m.partial["mean_item_coverage"] == 0.5
    assert m.cost["known_cost_usd"] == pytest.approx(0.05)
    assert m.cost["per_useful_usd"] == pytest.approx(0.05)


def test_zero_target_is_scored_absolutely_without_relative_error():
    m = config_metrics("X", [attempt(group="g0", energy=200, protein=2, carbs=45, fat=2)], REFS)
    fat = m.scorable_error["fat_g"]
    assert fat["mean_abs"] == 2 and fat["n_relative"] == 0 and fat["median_relative"] is None
    assert m.useful["pass_rate"] == 1.0  # 2 g fat error is within the 3 g floor


def test_abstention_cases_are_reported_separately():
    attempts = [
        attempt(group="ga", status="abstained"),
        attempt(group="ga", status="failed", code=ErrorCode.EMPTY_RECOGNITION.value, repeat=1),
        attempt(group="ga", status="complete", repeat=2),
        attempt(status="abstained", repeat=3),  # abstained on a real meal
    ]
    m = config_metrics("X", attempts, REFS)
    assert m.abstention == {
        "abstain_expected_attempts": 3,
        "correct_abstentions": 2,
        "abstained_on_food": 1,
    }
    assert m.useful["denominator_attempts"] == 1 and m.useful["pass_rate"] == 0.0


def test_unknown_cost_is_not_treated_as_zero():
    m = config_metrics("X", [attempt(cost=None), attempt(repeat=1)], REFS)
    assert m.cost["attempts_with_unknown_cost"] == 1
    assert m.cost["per_attempt_usd"] is None and m.cost["per_useful_usd"] is None


def test_repeatability_and_items():
    attempts = [attempt(energy=500), attempt(energy=540, repeat=1), attempt(energy=520, repeat=2)]
    rep = config_metrics("X", attempts, REFS).repeatability
    assert rep["status_consistent_rate"] == 1.0
    assert rep["median_energy_sd_kcal"] == pytest.approx(20)  # sample SD of 500, 540, 520
    items = config_metrics("X", attempts[:1], REFS).items
    assert items["precision"] == 1.0 and items["recall"] == 0.5
    assert items["preparation_accuracy"] == 1.0 and items["portion_mean_abs_g"] == 10


def test_bootstrap_resamples_groups_not_repeats():
    one_group = [attempt(repeat=r, energy=500 + 10 * r) for r in range(9)]
    assert group_bootstrap(one_group, lambda s: 1.0) is None  # 9 repeats are still one group
    two = [attempt(), attempt(group="g0", energy=200, protein=2, carbs=45, fat=0)]
    first = group_bootstrap(two, lambda s: float(len(s)))
    assert first == group_bootstrap(two, lambda s: float(len(s)))  # seeded, reproducible


def test_agreement_is_labeled_and_not_accuracy():
    a = [attempt(config="A_native", energy=540)]
    b = [attempt(config="B_grounded", energy=600)]
    result_ = agreement(a, b)
    assert result_["label"].endswith("NOT accuracy")
    assert result_["median_abs_energy_difference_kcal"] == 60
    assert result_["energy_within_tolerance_rate"] == 1.0  # 60 <= 15% of 600


# --- storage rights on derived metrics ------------------------------------------------------


def report_for(purpose):
    attempts = [attempt(config="A_native"), attempt(config="B_grounded", energy=600)]
    return build_report(
        attempts, REFS, ["A_native", "B_grounded"], StoragePolicy(), purpose, {"split": "dev"}
    )


def test_saved_reports_hide_fatsecret_derived_metrics_but_keep_payload_free_stats():
    saved = report_for(Purpose.PERSIST)
    a, b = saved["configs"]["A_native"], saved["configs"]["B_grounded"]
    assert a["useful"] == UNAVAILABLE and a["scorable_error"] == UNAVAILABLE
    assert a["status_counts"]["complete"] == 1 and a["latency_ms"]["p50_all"] == 100
    assert b["useful"]["pass_rate"] == 0.0  # B (USDA + model output) is unrestricted
    assert saved["comparison"] == UNAVAILABLE  # agreement uses A's outputs


def test_transient_report_shows_everything():
    shown = report_for(Purpose.TRANSIENT_EVALUATION)
    assert shown["configs"]["A_native"]["useful"]["pass_rate"] == 1.0
    assert shown["comparison"]["agreement"]["paired_complete"] == 1


def test_incomplete_batches_are_flagged():
    report = build_report(
        [attempt(config="B_grounded")],
        REFS,
        ["B_grounded"],
        StoragePolicy(),
        Purpose.PERSIST,
        {},
        not_run=5,
    )
    assert report["complete_batch"] is False and report["notes"][0].startswith("INCOMPLETE")


def test_bootstrap_keeps_a_groups_repeats_together():
    # Group g1 has 10 attempts, g0 has one. Resampling whole groups draws "only g0" a quarter
    # of the time, so the lower bound is 0. Resampling single attempts would almost never.
    many = [attempt(repeat=r) for r in range(10)]
    one = [attempt(group="g0", energy=200, protein=2, carbs=45, fat=0)]
    low, high = group_bootstrap(many + one, lambda s: sum(a.group_id == "g1" for a in s) / len(s))
    assert low == 0.0 and high == 1.0
