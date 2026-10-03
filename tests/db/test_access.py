"""Real role-based access: an inference login cannot read hidden benchmark labels."""

import pytest
from psycopg.errors import InsufficientPrivilege
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from foodvision.data.access import InferenceIsolationError, assert_inference_isolation

HIDDEN_QUERIES = [
    "SELECT count(*) FROM benchmark.reference_items",
    "SELECT count(*) FROM benchmark.reference_nutrients",
    "SELECT count(*) FROM benchmark.samples",
    "SELECT count(*) FROM benchmark.evaluation_metrics",
]


def denied(engine, sql):
    with pytest.raises(ProgrammingError) as info, engine.connect() as conn:
        conn.execute(text(sql))
    assert isinstance(info.value.orig, InsufficientPrivilege)


@pytest.mark.parametrize("sql", HIDDEN_QUERIES)
def test_inference_login_is_denied_hidden_labels(login_as, sql):
    denied(login_as("fv_inference"), sql)


def test_inference_cannot_escalate_or_write_catalog(login_as):
    inference = login_as("fv_inference")
    denied(inference, "SET ROLE fv_evaluator")
    denied(
        inference,
        "INSERT INTO food_catalog.food_records (provider, provider_food_id, "
        "source_version, name, basis_kind, basis_quantity, basis_unit) "
        "VALUES ('x','x','x','x','per_100g',100,'g')",
    )
    denied(inference, "DELETE FROM telemetry.images")
    denied(inference, "CREATE TABLE benchmark.leak (x int)")


def test_inference_can_do_its_job(login_as):
    inference = login_as("fv_inference")
    with inference.connect() as conn:
        assert (
            conn.execute(text("SELECT count(*) FROM food_catalog.food_records")).scalar_one() >= 0
        )
        assert conn.execute(text("SELECT count(*) FROM telemetry.runs")).scalar_one() >= 0
        assert_inference_isolation(conn)


def test_evaluator_can_read_labels_and_fails_isolation_check(login_as):
    evaluator = login_as("fv_evaluator")
    with evaluator.connect() as conn:
        assert conn.execute(text(HIDDEN_QUERIES[0])).scalar_one() >= 0
        with pytest.raises(InferenceIsolationError, match="benchmark"):
            assert_inference_isolation(conn)


def test_superuser_fails_isolation_check(owner):
    with owner.connect() as conn:
        is_super = conn.execute(
            text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        ).scalar_one()
        if not is_super:
            pytest.skip("admin connection is not a superuser")
        with pytest.raises(InferenceIsolationError, match="superuser"):
            assert_inference_isolation(conn)
