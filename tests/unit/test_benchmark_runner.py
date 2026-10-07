"""Benchmark runner and CLI with fake pipelines (POC-13). No provider is called; SYNTHETIC."""

import hashlib
import json
from pathlib import Path

import pytest
from tests.conftest import synthetic_image

from foodvision.benchmark.manifest import Group, Split
from foodvision.benchmark.runner import (
    BatchCaps,
    Sample,
    plan_runs,
    prepare_samples,
    run_batch,
    select_groups,
)
from foodvision.cli import benchmark_run
from foodvision.cli.main import main
from foodvision.contracts.results import (
    AnalysisResult,
    FoodSource,
    Nutrients,
    PortionMethod,
    ResultItem,
)
from foodvision.imaging.prepare import prepare_image
from foodvision.measurement.budget import BudgetPolicy
from foodvision.nutrition.calculator import sum_totals

EXAMPLES = Path(__file__).resolve().parents[2] / "benchmarks" / "examples"


class FakePipeline:
    """Returns a fixed complete result and records every image it was given."""

    is_mock = False

    def __init__(self, pipeline_id, source=FoodSource.USDA, energy=350.0, fail=False):
        self.pipeline_id = pipeline_id
        self.configuration_id = f"{pipeline_id}-fake"
        self.source, self.energy, self.fail = source, energy, fail
        self.seen: list[str] = []

    def analyze(self, image, context, recorder):
        self.seen.append(image.processed_sha256)
        if self.fail:
            raise RuntimeError("SENTINEL provider message")
        nutrients = Nutrients(energy_kcal=self.energy, protein_g=34, carbohydrate_g=40, fat_g=5)
        item = ResultItem(
            name="SYNTHETIC grilled chicken",
            preparation="grilled",
            resolved=True,
            portion_g=150,
            portion_method=PortionMethod.IMAGE_ESTIMATED,
            food_source=self.source,
            food_id="SYNTHETIC-1",
            nutrients=nutrients,
        )
        return AnalysisResult(
            scan_id=context.scan_id,
            pipeline_id=self.pipeline_id,
            is_mock=False,
            status="complete",
            items=[item],
            totals=sum_totals([nutrients]),
        )


def samples(n=2):
    return [
        Sample(f"g{i}:p", f"g{i}", prepare_image(synthetic_image(size=(80 + i, 60))))
        for i in range(n)
    ]


def test_order_rotates_by_photo_and_repeat():
    plan = plan_runs(samples(2), ["A_native", "B_grounded"], repeats=2)
    firsts = [(r.sample.sample_id, r.repeat, r.config) for r in plan if r.position == 0]
    assert firsts == [
        ("g0:p", 0, "A_native"),
        ("g1:p", 0, "B_grounded"),
        ("g0:p", 1, "B_grounded"),
        ("g1:p", 1, "A_native"),
    ]
    assert len(plan) == 8  # 2 photos x 2 configs x 2 repeats


def test_both_configs_get_identical_processed_bytes_and_failures_are_kept():
    a, b = FakePipeline("A_native", FoodSource.FATSECRET), FakePipeline("B_grounded", fail=True)
    plan = plan_runs(samples(1), ["A_native", "B_grounded"], repeats=3)
    batch = run_batch(
        plan,
        {"A_native": a, "B_grounded": b},
        dict.fromkeys(("A_native", "B_grounded"), BudgetPolicy()),
        BatchCaps(),
    )
    assert a.seen == b.seen and len(set(a.seen)) == 1
    failed = [r for r in batch.run_records if r["config"] == "B_grounded"]
    assert len(failed) == 3 and all(r["status"] == "failed" for r in failed)
    assert all(r["exception"] == "RuntimeError" for r in failed)  # type only, no message
    assert "SENTINEL" not in json.dumps(batch.run_records)


def test_batch_cap_stops_and_lists_runs_not_run():
    plan = plan_runs(samples(2), ["B_grounded"], repeats=3)
    batch = run_batch(
        plan,
        {"B_grounded": FakePipeline("B_grounded")},
        {"B_grounded": BudgetPolicy()},
        BatchCaps(max_scans=4),
    )
    assert len(batch.attempts) == 4 and len(batch.not_run) == 2
    assert batch.stop_reason == "max_scans 4 reached"


def test_test_split_needs_explicit_permission():
    with pytest.raises(PermissionError, match="locked final evaluation"):
        select_groups([], Split.TEST, allow_test=False)
    assert select_groups([], Split.TEST, allow_test=True) == []


# --- end to end through the CLI with fake pipelines -----------------------------------------


@pytest.fixture
def private_manifest(tmp_path):
    groups_dir, data = tmp_path / "groups", tmp_path / "data"
    groups_dir.mkdir()
    (data / "photos").mkdir(parents=True)
    for index, name in enumerate(("syn-plate-001", "syn-label-only-001")):
        group = json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))
        group["split"] = "development"
        for p, photo in enumerate(group["photos"]):
            image = synthetic_image(size=(64 + index, 48 + p))
            (data / photo["file"]).write_bytes(image)
            photo["sha256"] = hashlib.sha256(image).hexdigest()
        Group.model_validate(group)
        (groups_dir / f"{name}.json").write_text(json.dumps(group), encoding="utf-8")
    return groups_dir, data


def run_cli(monkeypatch, groups_dir, data, out, *extra):
    fakes = {
        "A_native": FakePipeline("A_native", FoodSource.FATSECRET, energy=360),
        "B_grounded": FakePipeline("B_grounded"),
    }

    class Settings:
        region, language = "US", "en"

    monkeypatch.setattr(
        benchmark_run, "_pipeline", lambda c: (fakes[c], BudgetPolicy(), Settings())
    )
    return main(
        [
            "benchmark",
            "--manifest",
            str(groups_dir),
            "--split",
            "development",
            "--configs",
            "A_native,B_grounded",
            "--repeats",
            "3",
            "--output",
            str(out),
            "--data-dir",
            str(data),
            *extra,
        ]
    )


def test_paid_run_needs_confirmation_and_caps(monkeypatch, private_manifest, tmp_path, capsys):
    groups_dir, data = private_manifest
    assert run_cli(monkeypatch, groups_dir, data, tmp_path / "out") == 2
    assert "Refusing a paid run" in capsys.readouterr().out


def test_saved_outputs_respect_fatsecret_rights(monkeypatch, private_manifest, tmp_path, capsys):
    groups_dir, data = private_manifest
    code = run_cli(
        monkeypatch,
        groups_dir,
        data,
        tmp_path / "out",
        "--confirm-paid-run",
        "--max-total-cost-usd",
        "1",
        "--max-scans",
        "100",
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "TRANSIENT REPORT" in printed
    (batch,) = (tmp_path / "out").iterdir()
    runs = [json.loads(line) for line in (batch / "runs.jsonl").read_text().splitlines()]
    assert len(runs) == 18  # 3 photos x 2 configs x 3 repeats
    a_saved = [r for r in runs if r["config"] == "A_native"]
    assert all("SYNTHETIC grilled chicken" not in json.dumps(r) for r in a_saved)
    assert all(r["result"]["_policy"]["dropped"] for r in a_saved)  # restricted content gone
    b_saved = [r for r in runs if r["config"] == "B_grounded"]
    assert all(not r["result"]["_policy"]["dropped"] for r in b_saved)
    saved = json.loads((batch / "report.json").read_text())
    assert saved["configs"]["A_native"]["useful"].startswith("UNAVAILABLE")
    assert saved["configs"]["A_native"]["status_counts"]["complete"] == 9
    assert saved["configs"]["B_grounded"]["useful"]["denominator_attempts"] == 6
    meta = json.loads((batch / "batch.json").read_text())
    assert meta["configs"]["A_native"]["configuration_id"] == "A_native-fake"
    assert meta["code"]["git_commit"] and meta["cache_notes"]

    # The report command rebuilds the saved report; A stays unavailable.
    assert main(["report", "--batch", str(batch), "--output", str(tmp_path / "rep")]) == 0
    rebuilt = json.loads((tmp_path / "rep" / "report.json").read_text())
    assert rebuilt["configs"]["B_grounded"]["useful"] == saved["configs"]["B_grounded"]["useful"]
    assert rebuilt["configs"]["A_native"]["useful"].startswith("UNAVAILABLE")


def test_output_inside_tracked_repo_is_refused(monkeypatch, private_manifest, capsys):
    groups_dir, data = private_manifest
    tracked = Path(__file__).resolve().parents[2] / "docs" / "should-not-exist"
    code = run_cli(
        monkeypatch,
        groups_dir,
        data,
        tracked,
        "--confirm-paid-run",
        "--max-total-cost-usd",
        "1",
        "--max-scans",
        "1",
    )
    assert code == 2 and "tracked path" in capsys.readouterr().out
    assert not tracked.exists()


def test_prepare_samples_rejects_changed_photo(private_manifest):
    groups_dir, data = private_manifest
    group = Group.model_validate_json((groups_dir / "syn-plate-001.json").read_text())
    (data / group.photos[0].file).write_bytes(synthetic_image(size=(10, 10)))
    with pytest.raises(ValueError, match="does not match"):
        prepare_samples([group], data)
