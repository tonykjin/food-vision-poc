"""Foreign keys, uniqueness, checks and deletion behavior. All rows are SYNTHETIC test data."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError

from foodvision.data.models import (
    calibration_versions,
    food_nutrients,
    food_records,
    images,
    reference_nutrients,
    runs,
    samples,
    stage_events,
)

NOW = datetime(2026, 10, 2, tzinfo=UTC)


def food(conn, provider_food_id="synthetic-1", **overrides):
    values = (
        dict(
            provider="USDA",
            provider_food_id=provider_food_id,
            source_version="synthetic-test",
            name="SYNTHETIC test food",
            basis_kind="per_100g",
            basis_quantity=100,
            basis_unit="g",
            is_synthetic=True,
        )
        | overrides
    )
    return conn.execute(
        insert(food_records).values(**values).returning(food_records.c.food_id)
    ).scalar_one()


def image(conn):
    image_id = uuid.uuid4()
    conn.execute(
        insert(images).values(
            image_id=image_id,
            object_key=f"test/{image_id.hex}",
            original_sha256="0" * 64,
            consent_basis="synthetic test fixture",
            retention_until=NOW + timedelta(days=30),
            is_synthetic=True,
        )
    )
    return image_id


def run(conn, run_id, image_id=None):
    conn.execute(
        insert(runs).values(
            run_id=run_id,
            pipeline_id="B_mock",
            image_id=image_id,
            status="partial",
            is_mock=True,
            is_synthetic=True,
            started_at=NOW,
            finished_at=NOW,
            server_total_ms=1.0,
            logical_requests=0,
            attempts=0,
            model_calls=0,
            retries=0,
            timeouts=0,
            blocked_attempts=0,
            known_cost_usd=0,
        )
    )


def violates(conn, statement):
    with pytest.raises(IntegrityError), conn.begin_nested():
        conn.execute(statement)


def test_catalog_uniqueness_nulls_checks_and_cascade(owner):
    with owner.begin() as conn:
        food_id = food(conn)
        violates(
            conn,
            insert(food_records).values(
                provider="USDA",
                provider_food_id="synthetic-1",
                source_version="synthetic-test",
                name="dup",
                basis_kind="per_100g",
                basis_quantity=100,
                basis_unit="g",
            ),
        )
        # Unknown nutrient is NULL, never 0; negatives rejected; one row per nutrient.
        conn.execute(
            insert(food_nutrients).values(
                food_id=food_id, nutrient="protein", amount=None, unit="g"
            )
        )
        violates(
            conn,
            insert(food_nutrients).values(food_id=food_id, nutrient="fat", amount=-1, unit="g"),
        )
        violates(
            conn,
            insert(food_nutrients).values(food_id=food_id, nutrient="protein", amount=1, unit="g"),
        )
        violates(
            conn, insert(food_nutrients).values(food_id=999_999, nutrient="fat", amount=1, unit="g")
        )
        # Inconsistent basis rejected by the database too.
        violates(
            conn,
            insert(food_records).values(
                provider="USDA",
                provider_food_id="bad",
                source_version="v",
                name="x",
                basis_kind="per_100g",
                basis_quantity=40,
                basis_unit="g",
            ),
        )
        conn.execute(delete(food_records).where(food_records.c.food_id == food_id))
        remaining = conn.execute(
            select(func.count())
            .select_from(food_nutrients)
            .where(food_nutrients.c.food_id == food_id)
        ).scalar_one()
        assert remaining == 0
        conn.rollback()


def test_run_events_cascade_and_image_deletion_rules(owner):
    with owner.begin() as conn:
        image_id = image(conn)
        run(conn, "synthetic-run-1", image_id)
        conn.execute(
            insert(stage_events).values(
                run_id="synthetic-run-1",
                span_id="s1",
                stage="mock",
                started_at=NOW,
                duration_ms=1.0,
                status="ok",
                cache_state="not_applicable",
            )
        )
        violates(
            conn,
            insert(stage_events).values(
                run_id="synthetic-run-1",
                span_id="s1",
                stage="mock",
                started_at=NOW,
                duration_ms=1.0,
                status="ok",
                cache_state="not_applicable",
            ),
        )
        violates(
            conn,
            insert(runs).values(
                run_id="bad-status",
                pipeline_id="x",
                status="done",
                is_mock=True,
                started_at=NOW,
                finished_at=NOW,
                server_total_ms=1,
                logical_requests=0,
                attempts=0,
                model_calls=0,
                retries=0,
                timeouts=0,
                blocked_attempts=0,
                known_cost_usd=0,
            ),
        )
        # A benchmark sample pins its image: deleting the image row is refused.
        conn.execute(
            insert(samples).values(
                sample_id="synthetic-sample-1",
                image_id=image_id,
                group_id="g1",
                category="synthetic",
                split="development",
                reference_version="synthetic",
                is_synthetic=True,
            )
        )
        violates(conn, delete(images).where(images.c.image_id == image_id))
        conn.execute(delete(samples).where(samples.c.sample_id == "synthetic-sample-1"))
        # Without samples, deleting the image keeps the run but nulls its image link.
        conn.execute(delete(images).where(images.c.image_id == image_id))
        assert (
            conn.execute(
                select(runs.c.image_id).where(runs.c.run_id == "synthetic-run-1")
            ).scalar_one()
            is None
        )
        conn.execute(delete(runs).where(runs.c.run_id == "synthetic-run-1"))
        assert conn.execute(select(func.count()).select_from(stage_events)).scalar_one() == 0
        conn.rollback()


def test_benchmark_checks(owner):
    with owner.begin() as conn:
        image_id = image(conn)
        violates(
            conn,
            insert(samples).values(
                sample_id="s",
                image_id=image_id,
                group_id="g",
                category="c",
                split="train",
                reference_version="v",
            ),
        )
        conn.execute(
            insert(samples).values(
                sample_id="s2",
                image_id=image_id,
                group_id="g",
                category="c",
                split="test",
                reference_version="v",
                is_synthetic=True,
            )
        )
        violates(
            conn,
            insert(reference_nutrients).values(
                sample_id="s2",
                nutrient="energy",
                amount=1,
                unit="kcal",
                method="m",
                quality_grade="D",
            ),
        )
        violates(
            conn,
            insert(calibration_versions).values(
                version="c1",
                fitting_split="test",
                success_definition="x",
                bin_counts={},
                rates={},
            ),
        )
        conn.rollback()
