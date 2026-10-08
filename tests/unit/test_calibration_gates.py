"""Freeze, calibration and decision gates (POC-15). SYNTHETIC data only; no provider calls."""

import hashlib
import json
from pathlib import Path

import pytest
from tests.conftest import synthetic_image
from tests.unit.test_benchmark_metrics import REF, REFS, attempt
from tests.unit.test_benchmark_runner import FakePipeline

from foodvision.benchmark import freeze as freeze_module
from foodvision.benchmark.calibration import MIN_GROUPS, calibrate
from foodvision.benchmark.freeze import (
    FreezeViolation,
    RunState,
    build_spec,
    check_matches,
    load_spec,
)
from foodvision.benchmark.gates import (
    GO,
    INCONCLUSIVE,
    NO_GO,
    _verdict_at_least,
    _verdict_at_most,
    evaluate_gates,
    typed_within_deadline,
)
from foodvision.benchmark.metrics import Reference
from foodvision.cli import benchmark_run
from foodvision.cli.main import main
from foodvision.contracts.results import Confidence, ConfidenceType
from foodvision.measurement.budget import BudgetPolicy

EXAMPLES = Path(__file__).resolve().parents[2] / "benchmarks" / "examples"
CONFIGS = {
    "B_grounded": {
        "pipeline_id": "B_grounded",
        "configuration_id": "B-x",
        "catalog_source_versions": None,
    }
}


def labeled(label, group, useful=True, **kw):
    a = attempt(group=group, sample=f"{group}:p", **({} if useful else {"energy": 900}), **kw)
    a.result.confidence = Confidence(
        type=ConfidenceType.HEURISTIC_UNCALIBRATED,
        label=label,
        identity=label,
        portion=label,
        nutrition_match=label,
    )
    return a


def many_groups(n):
    refs = {
        f"g{i}": Reference(
            f"g{i}", "separated_plate", "A", "estimate", REF.nutrients, REF.components
        )
        for i in range(n)
    }
    return refs


# --- calibration ----------------------------------------------------------------------------


def test_calibration_never_fits_on_another_split():
    with pytest.raises(ValueError, match="calibration split only"):
        calibrate([], REFS, "v", "test")


def test_buckets_below_30_groups_stay_uncalibrated_even_with_many_repeats():
    attempts = [labeled("medium", "g1", repeat=r) for r in range(40)]  # 40 attempts, 1 group
    record = calibrate(attempts, REFS, "v", "calibration")
    assert record["bin_counts"]["medium"] == {"attempts": 40, "groups": 1, "useful": 40}
    assert record["rates"]["medium"] is None
    assert record["status"]["medium"].startswith("insufficient data (1 < 30 groups)")


def test_bucket_with_enough_groups_gets_a_rate_interval_and_false_high_review():
    refs = many_groups(MIN_GROUPS)
    attempts = [labeled("high", f"g{i}", useful=i % 3 != 0) for i in range(MIN_GROUPS)]
    record = calibrate(attempts, refs, "v", "calibration")
    assert record["status"]["high"] == "calibrated"
    assert record["rates"]["high"] == pytest.approx(20 / 30)
    low, high = record["uncertainty"]["high"]
    assert low < record["rates"]["high"] < high
    assert len(record["false_high_confidence_for_review"]) == 10
    assert record["status"]["low"].startswith("insufficient data (0")
    assert "useful-v1" in record["success_definition"]


# --- gates ----------------------------------------------------------------------------------


def test_verdicts_use_the_whole_interval():
    assert _verdict_at_least((0.96, 0.99), 0.95) == GO
    assert _verdict_at_least((0.80, 0.94), 0.95) == NO_GO
    assert _verdict_at_least((0.90, 0.99), 0.95) == INCONCLUSIVE
    assert _verdict_at_most((9_000, 14_000), 15_000) == GO
    assert _verdict_at_most((16_000, 20_000), 15_000) == NO_GO
    assert _verdict_at_least(None, 0.95) == INCONCLUSIVE  # too few groups for an interval


def test_typed_result_within_deadline():
    assert typed_within_deadline(attempt(ms=1000), 45_000)
    assert not typed_within_deadline(attempt(ms=50_000), 45_000)  # past the deadline
    assert not typed_within_deadline(attempt(status="failed"), 45_000)  # timeout failure
    assert typed_within_deadline(attempt(status="failed", code="empty_recognition"), 45_000)


def test_gates_overall_go_no_go_and_human_items():
    refs = many_groups(40)
    good_a = [attempt(config="A_native", group=f"g{i}", sample=f"g{i}:p") for i in range(40)]
    good_b = [attempt(config="B_grounded", group=f"g{i}", sample=f"g{i}:p") for i in range(40)]
    result = evaluate_gates(
        {"A_native": good_a, "B_grounded": good_b}, refs, 45_000, True, "A_native", "B_grounded"
    )
    assert result["overall"] == "GO (provisional)"
    assert result["gates"]["cost_materiality"]["verdict"] == "NEEDS HUMAN DECISION"
    bad_b = [
        attempt(config="B_grounded", group=f"g{i}", sample=f"g{i}:p", energy=900) for i in range(40)
    ]
    worse = evaluate_gates(
        {"A_native": good_a, "B_grounded": bad_b}, refs, 45_000, True, "A_native", "B_grounded"
    )
    assert worse["gates"]["useful_rate_B_minus_A"]["verdict"] == NO_GO
    assert worse["overall"].startswith(NO_GO)
    incomplete = evaluate_gates({"A_native": good_a}, refs, 45_000, False, None, None)
    assert incomplete["gates"]["no_hidden_exclusions"]["verdict"] == NO_GO


# --- freeze ---------------------------------------------------------------------------------


@pytest.fixture
def clean_tree(monkeypatch):
    head = freeze_module.code_version()["git_commit"]
    clean = {"git_commit": head, "dirty": False}
    monkeypatch.setattr(freeze_module, "code_version", lambda: clean)
    monkeypatch.setattr(benchmark_run, "code_version", lambda: clean)
    return head


def test_spec_refuses_a_dirty_tree_and_detects_tampering(monkeypatch, tmp_path, clean_tree):
    spec = build_spec("t", CONFIGS, "a" * 64)
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    assert load_spec(path)["git_commit"] == clean_tree
    spec["useful_tolerance"]["relative"]["energy_kcal"] = 0.5  # loosen after the fact
    path.write_text(json.dumps(spec))
    with pytest.raises(FreezeViolation, match="not a valid, unmodified"):
        load_spec(path)
    monkeypatch.setattr(freeze_module, "code_version", lambda: {"git_commit": "x", "dirty": True})
    with pytest.raises(FreezeViolation, match="dirty"):
        build_spec("t", CONFIGS, "a" * 64)


def test_run_must_match_the_spec(clean_tree):
    spec = build_spec("t", CONFIGS, "a" * 64)
    check_matches(spec, RunState(CONFIGS, "a" * 64, dirty=False))  # identical: fine
    changed = {"B_grounded": {**CONFIGS["B_grounded"], "configuration_id": "B-other-prompt"}}
    with pytest.raises(FreezeViolation) as info:
        check_matches(spec, RunState(changed, "b" * 64, dirty=True))
    message = str(info.value)
    for expected in ("uncommitted", "manifest changed", "configuration differs"):
        assert expected in message


# --- end to end: freeze -> calibration batch -> calibrate -> test batch once ----------------


@pytest.fixture
def two_split_manifest(tmp_path):
    groups_dir, data = tmp_path / "groups", tmp_path / "data"
    groups_dir.mkdir()
    (data / "photos").mkdir(parents=True)
    base = json.loads((EXAMPLES / "syn-plate-001.json").read_text(encoding="utf-8"))
    for i, split in enumerate(("calibration", "test")):
        group = json.loads(json.dumps(base))
        group.update(group_id=f"syn-{split}-001", split=split)
        group["photos"] = group["photos"][:1]
        image = synthetic_image(size=(70 + i, 50))
        group["photos"][0].update(
            photo_id=f"syn-{split}-p",
            file=f"photos/{split}.jpg",
            sha256=hashlib.sha256(image).hexdigest(),
        )
        (data / f"photos/{split}.jpg").write_bytes(image)
        (groups_dir / f"{group['group_id']}.json").write_text(json.dumps(group))
    return groups_dir, data


def test_frozen_calibration_and_single_test_run(
    monkeypatch, tmp_path, clean_tree, two_split_manifest, capsys
):
    groups_dir, data = two_split_manifest
    monkeypatch.setattr(freeze_module, "FROZEN_DIR", tmp_path / "frozen")
    fake = FakePipeline("B_grounded")

    class Settings:
        region, language = "US", "en"

    monkeypatch.setattr(benchmark_run, "_pipeline", lambda c: (fake, BudgetPolicy(), Settings()))
    out = tmp_path / "work"

    def bench(split, *extra):
        return main(
            [
                "benchmark",
                "--manifest",
                str(groups_dir),
                "--split",
                split,
                "--configs",
                "B_grounded",
                "--repeats",
                "3",
                "--output",
                str(out),
                "--data-dir",
                str(data),
                "--confirm-paid-run",
                "--max-total-cost-usd",
                "1",
                "--max-scans",
                "50",
                *extra,
            ]
        )

    assert bench("calibration") == 2  # no frozen spec: refused
    assert "frozen spec" in capsys.readouterr().out
    assert (
        main(["freeze", "--manifest", str(groups_dir), "--configs", "B_grounded", "--name", "t1"])
        == 0
    )
    spec = str(tmp_path / "frozen" / "t1.json")
    assert bench("calibration", "--frozen", spec) == 0
    (batch,) = [
        p
        for p in out.iterdir()
        if json.loads((p / "batch.json").read_text())["split"] == "calibration"
    ]
    capsys.readouterr()
    assert (
        main(
            [
                "calibrate",
                "--batch",
                str(batch),
                "--config",
                "B_grounded",
                "--version",
                "cal-1",
                "--output",
                str(tmp_path / "cal"),
            ]
        )
        == 0
    )
    record = json.loads((tmp_path / "cal" / "calibration-B_grounded.json").read_text())
    assert record["fitting_split"] == "calibration"
    assert all(rate is None for rate in record["rates"].values())  # 1 group: insufficient
    assert record["bin_counts"]["medium"]["groups"] == 1

    assert bench("test", "--frozen", spec) == 2  # test split still needs explicit consent
    assert bench("test", "--frozen", spec, "--allow-test-split") == 0
    assert bench("test", "--frozen", spec, "--allow-test-split") == 2  # never twice
    assert "already ran for this frozen spec" in capsys.readouterr().out
