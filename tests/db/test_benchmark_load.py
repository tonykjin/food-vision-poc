"""Evaluator-only loading of reference groups (POC-12). SYNTHETIC groups and images only."""

import copy
import hashlib
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from tests.conftest import synthetic_image

from foodvision.benchmark.load import EvaluatorAuthorizationError, load_groups
from foodvision.benchmark.manifest import Group
from foodvision.data.object_store import LocalObjectStore

EXAMPLES = Path(__file__).resolve().parents[2] / "benchmarks" / "examples"
NOW = datetime(2026, 10, 7, tzinfo=UTC)


@pytest.fixture
def data_dir(tmp_path):
    """Synthetic photo files plus groups whose hashes match them."""
    (tmp_path / "photos").mkdir()
    groups = []
    for index, name in enumerate(("syn-plate-001", "syn-stew-001", "syn-label-only-001")):
        data = json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))
        data["split"] = "development"
        for p, photo in enumerate(data["photos"]):
            image = synthetic_image(size=(64 + index, 48 + p))
            (tmp_path / photo["file"]).write_bytes(image)
            photo["sha256"] = hashlib.sha256(image).hexdigest()
        groups.append(Group.model_validate(data))
    return tmp_path, groups


def load(engine, data_dir, groups, version):
    with engine.begin() as conn:
        return load_groups(
            conn, LocalObjectStore(data_dir / "objects"), groups, data_dir, version, NOW
        )


def count(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def test_evaluator_loads_samples_references_and_photos(login_as, data_dir):
    root, groups = data_dir
    evaluator = login_as("fv_evaluator")
    version = f"test-{secrets.token_hex(4)}"
    summary = load(evaluator, root, groups, version)
    assert (summary.groups, summary.samples) == (3, 4)  # the plate has two photos
    q = "SELECT count(*) FROM benchmark.samples WHERE reference_version = :v"
    assert count(evaluator, q, v=version) == 4
    nutrient = (
        "SELECT amount FROM benchmark.reference_nutrients n JOIN benchmark.samples s "
        "USING (sample_id) WHERE s.reference_version = :v AND s.group_id = 'syn-plate-001' "
        "AND n.nutrient = 'energy_kcal'"
    )
    with evaluator.connect() as conn:
        amounts = conn.execute(text(nutrient), {"v": version}).scalars().all()
    assert [float(a) for a in amounts] == [350.0, 350.0]  # calculated, one row per photo
    abstain = (
        "SELECT expected_outcome FROM benchmark.samples "
        "WHERE reference_version = :v AND group_id = 'syn-label-only-001'"
    )
    assert count(evaluator, abstain, v=version) == "abstain"
    # Photo bytes live in the private store; the database only has metadata.
    assert any((root / "objects").rglob("*"))


def test_reload_replaces_instead_of_duplicating(login_as, data_dir):
    root, groups = data_dir
    evaluator = login_as("fv_evaluator")
    version = f"test-{secrets.token_hex(4)}"
    load(evaluator, root, groups, version)
    again = load(evaluator, root, groups, version)
    assert again.new_images == 0  # photos already registered are reused
    q = "SELECT count(*) FROM benchmark.samples WHERE reference_version = :v"
    assert count(evaluator, q, v=version) == 4


def test_drafts_and_unassigned_groups_are_skipped(login_as, data_dir):
    root, groups = data_dir
    draft = Group.model_validate(
        {**copy.deepcopy(groups[0].model_dump(mode="json")), "review": {"status": "draft"}}
    )
    unassigned = groups[1].model_copy(update={"split": None})
    summary = load(login_as("fv_evaluator"), root, [draft, unassigned], f"t-{secrets.token_hex(4)}")
    assert summary.groups == 0 and summary.skipped == [draft.group_id, unassigned.group_id]


def test_inference_login_cannot_load(login_as, data_dir):
    root, groups = data_dir
    inference = login_as("fv_inference")
    with pytest.raises(EvaluatorAuthorizationError, match="not an fv_evaluator login"):
        load(inference, root, groups, "never")


def test_superuser_owner_is_refused(owner, data_dir):
    root, groups = data_dir
    with pytest.raises(EvaluatorAuthorizationError, match="superuser"):
        load(owner, root, groups, "never")


def test_a_new_reference_version_keeps_the_old_one(login_as, data_dir):
    root, groups = data_dir
    evaluator = login_as("fv_evaluator")
    old, new = f"test-{secrets.token_hex(4)}", f"test-{secrets.token_hex(4)}"
    load(evaluator, root, groups, old)
    load(evaluator, root, groups, new)
    q = "SELECT count(*) FROM benchmark.samples WHERE reference_version = :v"
    assert count(evaluator, q, v=old) == count(evaluator, q, v=new) == 4


def test_calibration_version_is_saved_by_evaluator_and_never_fits_on_test(login_as):
    from sqlalchemy.exc import IntegrityError

    from foodvision.benchmark.calibration import save_calibration

    evaluator = login_as("fv_evaluator")
    record = {
        "version": f"cal-{secrets.token_hex(4)}",
        "fitting_split": "calibration",
        "success_definition": "useful-v1 (synthetic test)",
        "bin_counts": {"high": {"attempts": 3, "groups": 1, "useful": 3}},
        "rates": {"high": None},
        "uncertainty": {"high": None},
        "status": {"high": "insufficient data (1 < 30 groups)"},
    }
    with evaluator.begin() as conn:
        save_calibration(conn, record)
    q = "SELECT fitting_split FROM benchmark.calibration_versions WHERE version = :v"
    assert count(evaluator, q, v=record["version"]) == "calibration"
    with pytest.raises(IntegrityError), evaluator.begin() as conn:
        save_calibration(
            conn, {**record, "version": record["version"] + "-t", "fitting_split": "test"}
        )
    with pytest.raises(EvaluatorAuthorizationError), login_as("fv_inference").begin() as conn:
        save_calibration(conn, {**record, "version": record["version"] + "-i"})
