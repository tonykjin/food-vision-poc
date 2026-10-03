"""Migrations run from an empty database, round-trip, and match the models."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from tests.db.helpers import alembic_config

from foodvision.data.models import SCHEMAS, metadata

EXPECTED_TABLES = {
    "food_catalog": {"food_records", "food_nutrients", "food_portions"},
    "telemetry": {
        "images",
        "configurations",
        "runs",
        "stage_events",
        "attempt_events",
        "permitted_results",
        "corrections",
    },
    "benchmark": {
        "samples",
        "reference_items",
        "reference_nutrients",
        "evaluation_metrics",
        "calibration_versions",
    },
}


def tables(engine) -> dict[str, set[str]]:
    inspector = inspect(engine)
    names = set(inspector.get_schema_names())
    return {s: set(inspector.get_table_names(schema=s)) for s in SCHEMAS if s in names}


def test_upgrade_from_empty_downgrade_and_upgrade_again(empty_db):
    config = alembic_config(empty_db)
    engine = create_engine(empty_db)
    assert tables(engine) == {}

    command.upgrade(config, "head")
    assert tables(engine) == EXPECTED_TABLES

    command.downgrade(config, "base")
    assert tables(engine) == {}

    command.upgrade(config, "head")
    assert tables(engine) == EXPECTED_TABLES
    engine.dispose()


def test_migration_matches_models(migrated_db):
    engine = create_engine(migrated_db)
    with engine.connect() as conn:
        context = MigrationContext.configure(
            conn,
            opts={
                "include_schemas": True,
                "include_name": lambda name, type_, _: type_ != "schema" or name in SCHEMAS,
            },
        )
        assert compare_metadata(context, metadata) == []
    engine.dispose()


def test_no_image_bytes_columns(owner):
    with owner.connect() as conn:
        binary = conn.execute(
            text(
                "SELECT table_schema, table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = ANY(:schemas) AND data_type = 'bytea'"
            ),
            {"schemas": list(SCHEMAS)},
        ).all()
    assert binary == []
