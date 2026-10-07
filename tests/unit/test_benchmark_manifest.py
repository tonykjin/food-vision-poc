"""Reference manifest, validation and splits (POC-12). All groups here are SYNTHETIC."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from foodvision.benchmark import validate as validate_module
from foodvision.benchmark.manifest import Group, Split, load_groups, reference_totals
from foodvision.benchmark.splits import assign_splits
from foodvision.benchmark.validate import Report, check_groups, check_location, progress
from foodvision.cli.main import main

EXAMPLES = Path(__file__).resolve().parents[2] / "benchmarks" / "examples"


def example(name: str) -> dict:
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def group(name="syn-plate-001", **changes) -> Group:
    data = copy.deepcopy(example(name))
    data.update(changes)
    return Group.model_validate(data)


def real(group_id: str, split=None, family=None, reviewers=1, sha="1", **changes) -> Group:
    data = copy.deepcopy(example("syn-plate-001"))
    data.update(group_id=group_id, family_id=family, is_synthetic=False, split=split, **changes)
    data["photos"] = [
        {
            **data["photos"][0],
            "photo_id": f"{group_id}-p",
            "sha256": hashlib.sha256(f"{group_id}{sha}".encode()).hexdigest(),
        }
    ]
    data["review"]["reviewers"] = data["review"]["reviewers"] * reviewers
    return Group.model_validate(data)


# --- reference arithmetic -------------------------------------------------------------------


def test_components_reference_is_calculated_from_grams_and_basis():
    totals = reference_totals(group())
    # 150 g x 100 kcal/100 g + 200 g x 100 kcal/100 g; protein 150x20/100 + 200x2/100
    assert totals.nutrients.energy_kcal == pytest.approx(350)
    assert totals.nutrients.protein_g == pytest.approx(34)
    assert totals.complete and totals.method.startswith("components")


def test_recipe_reference_scales_by_served_over_cooked_yield():
    totals = reference_totals(group("syn-stew-001"))
    # (400 g x 200 + 500 g x 80) / 100 = 1200 kcal for the pot; 250/1000 served
    assert totals.nutrients.energy_kcal == pytest.approx(300)
    assert totals.method.startswith("recipe")


def test_per_serving_label_and_unknown_nutrient_stays_unknown():
    totals = reference_totals(group("syn-bar-001"))
    assert totals.nutrients.energy_kcal == pytest.approx(190)  # 40 g of a 40 g serving
    assert totals.nutrients.fat_g is None  # unknown, never 0
    assert not totals.complete


def test_abstain_group_has_no_nutrient_reference():
    assert reference_totals(group("syn-label-only-001")) is None


def test_grams_against_ml_basis_without_density_is_an_error_not_a_guess():
    data = example("syn-bar-001")
    data["components"][0]["values"].update(serving_unit="ml")
    totals = reference_totals(Group.model_validate(data))
    assert totals.errors and "density" in totals.errors[0]
    assert totals.nutrients.energy_kcal is None


# --- schema ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("photos", 0, "rights"), "stock"),  # third-party/stock images are not allowed
        (("components", 0, "edible_grams"), 0),
        (("components", 0, "values", "energy", "unit"), "g"),
        (("components", 0, "values", "basis"), "per_serving"),  # no serving size given
        (("review", "reviewers"), []),  # reviewed without a reviewer
        (("split",), "holdout"),
        (("group_id",), "Bad ID!"),
    ],
)
def test_schema_rejects_bad_fields(path, value):
    data = example("syn-plate-001")
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        Group.model_validate(data)


def test_exactly_one_reference_method():
    data = example("syn-plate-001")
    data["recipe"] = example("syn-stew-001")["recipe"]
    with pytest.raises(ValidationError, match="exactly one"):
        Group.model_validate(data)


# --- cross-group validation -----------------------------------------------------------------


def errors_of(groups, data_dir=None) -> list[str]:
    report = Report()
    check_groups(groups, data_dir, report)
    return report.errors


def test_family_across_splits_is_leakage():
    groups = [
        real("g-one", split=Split.DEVELOPMENT, family="fam"),
        real("g-two", split=Split.TEST, family="fam"),
    ]
    assert any("family fam" in e and "leakage" in e for e in errors_of(groups))


def test_same_photo_in_two_groups_is_leakage():
    groups = [real("g-one", sha="same"), real("g-two", sha="same")]
    groups[1].photos[0].sha256 = groups[0].photos[0].sha256
    assert any("same image" in e for e in errors_of(groups))


def test_duplicate_group_id_is_rejected():
    assert any("defined 2 times" in e for e in errors_of([real("g-one"), real("g-one", sha="2")]))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"measurement": "estimated"}, "grade C only"),
        ({"measurement": "label_declared"}, "every component weighed"),
    ],
)
def test_grade_claims_must_match_evidence(change, message):
    g = real("g-one")
    g.components[0] = g.components[0].model_copy(update=change)
    assert any(message in e for e in errors_of([g]))


def test_label_values_cannot_claim_grade_a():
    g = group("syn-bar-001", quality_grade="A")
    assert any("grade B, not A" in e for e in errors_of([g]))


def test_photo_files_are_checked_against_their_hash(tmp_path):
    g = real("g-one")
    assert any("missing" in e for e in errors_of([g], tmp_path))
    (tmp_path / "photos").mkdir()
    (tmp_path / g.photos[0].file).write_bytes(b"different bytes")
    assert any("does not match its sha256" in e for e in errors_of([g], tmp_path))
    g.photos[0].file = "../outside.jpg"
    assert any("escapes" in e for e in errors_of([g], tmp_path))


def test_real_labels_inside_the_tracked_repo_are_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(validate_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(validate_module, "_git_ignored", lambda path: False)
    report = Report()
    check_location(tmp_path / "manifest", [real("g-one")], report)
    assert any("not git-ignored" in e for e in report.errors)
    report = Report()
    check_location(tmp_path / "manifest", [group()], report)  # synthetic only: allowed
    assert report.ok


# --- progress -------------------------------------------------------------------------------


def test_progress_never_counts_synthetic_and_flags_single_reviewers():
    groups = [group(), real("g-one", split=Split.DEVELOPMENT), real("g-two", reviewers=2)]
    report = Report()
    check_groups(groups, None, report)
    progress(groups, report)
    text = "\n".join(report.progress)
    assert "Real groups: 2 (2 reviewed with grade A/B); synthetic groups (never counted): 1" in text
    assert "Development milestone: 1/30" in text
    assert "Single-reviewer groups: 1 of 2" in text
    assert "No accuracy study is ready" in text
    assert any("g-one: single reviewer" in w for w in report.warnings)


def test_bundled_examples_are_valid_and_all_synthetic():
    groups, errors = load_groups(EXAMPLES)
    assert not errors and groups and all(g.is_synthetic for g in groups)
    assert not errors_of(groups)


# --- splits ---------------------------------------------------------------------------------


def test_families_stay_together_and_development_fills_first():
    groups = [real(f"g-{i:02d}", family=f"fam-{i // 2}", sha=str(i)) for i in range(40)]
    result = assign_splits(groups, development_target=10)
    by_family: dict[str, set] = {}
    for g in groups:
        by_family.setdefault(g.family_key, set()).add(result[g.group_id])
    assert all(len(splits) == 1 for splits in by_family.values())
    counts = {s: sum(1 for v in result.values() if v is s) for s in Split}
    assert counts[Split.DEVELOPMENT] == 10
    assert counts[Split.CALIBRATION] > 0 and counts[Split.TEST] > 0


def test_assignment_is_deterministic_and_never_moves_existing_splits():
    groups = [real(f"g-{i:02d}", sha=str(i)) for i in range(10)]
    assert assign_splits(groups, development_target=3) == assign_splits(
        groups, development_target=3
    )
    fixed = [real("g-fixed", split=Split.TEST, family="fam"), real("g-new", family="fam", sha="9")]
    assert assign_splits(fixed) == {"g-new": Split.TEST}  # joins its family's split


def test_family_already_spanning_splits_is_refused():
    groups = [
        real("g-one", split=Split.DEVELOPMENT, family="fam"),
        real("g-two", split=Split.TEST, family="fam", sha="2"),
    ]
    with pytest.raises(ValueError, match="spans several splits"):
        assign_splits(groups)


def test_cli_assign_splits_writes_group_files(tmp_path, capsys):
    for name in ("syn-plate-001", "syn-stew-001"):
        (tmp_path / f"{name}.json").write_text(json.dumps(example(name)), encoding="utf-8")
    assert main(["assign-splits", "--manifest", str(tmp_path)]) == 0
    written = json.loads((tmp_path / "syn-plate-001.json").read_text(encoding="utf-8"))
    assert written["split"] == "development"
    assert main(["validate-manifest", "--manifest", str(tmp_path)]) == 0
    assert "Result: valid" in capsys.readouterr().out


def test_third_party_smoke_photos_only_in_synthetic_groups():
    data = example("syn-plate-001")
    for photo in data["photos"]:
        photo["rights"] = "third_party_smoke_only"
    assert Group.model_validate(data).is_synthetic  # allowed: synthetic smoke test
    data["is_synthetic"] = False
    with pytest.raises(ValidationError, match="synthetic groups only"):
        Group.model_validate(data)
