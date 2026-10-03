"""Writes through real roles and the storage policy. All data is SYNTHETIC test data."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from foodvision.contracts.errors import ErrorCode
from foodvision.contracts.results import (
    AnalysisResult,
    FoodSource,
    Nutrients,
    PortionMethod,
    ResultItem,
    Totals,
    TotalsStatus,
)
from foodvision.data.models import images, permitted_results, runs, stage_events
from foodvision.data.object_store import LocalObjectStore, delete_image, purge_expired, store_image
from foodvision.data.repositories import save_metric, save_result, save_scan_record
from foodvision.measurement.budget import BudgetPolicy
from foodvision.measurement.clock import ManualClock
from foodvision.measurement.events import ScanStatus, Stage
from foodvision.measurement.spans import ScanRecorder
from foodvision.measurement.storage_policy import DataSource, PolicyViolation, StoragePolicy

NOW = datetime(2026, 10, 2, tzinfo=UTC)
PENDING = StoragePolicy()


def scan_record(scan_id):
    clock = ManualClock()
    recorder = ScanRecorder(scan_id, "A_native", budget=BudgetPolicy(), clock=clock)
    with recorder.span(Stage.IMAGE_PREPARE):
        clock.advance(0.05)
    return recorder.finish(ScanStatus.PARTIAL)


def fatsecret_result(scan_id):
    return AnalysisResult(
        scan_id=scan_id,
        pipeline_id="A_native",
        is_mock=False,
        status="partial",
        items=[
            ResultItem(
                name="SYNTHETIC grilled salmon",
                resolved=True,
                portion_g=150,
                portion_method=PortionMethod.PROVIDER_SUGGESTED,
                food_source=FoodSource.FATSECRET,
                food_id="synthetic-fs-1",
                serving_id="synthetic-sv-1",
                nutrients=Nutrients(energy_kcal=999),
            )
        ],
        totals=Totals(
            status=TotalsStatus.PARTIAL, nutrients=Nutrients(energy_kcal=999), included_items=1
        ),
        warnings=["SYNTHETIC provider text"],
    )


def test_inference_role_persists_scan_and_policy_filtered_result(login_as):
    inference = login_as("fv_inference")
    with inference.begin() as conn:
        save_scan_record(
            conn, scan_record("synthetic-scan-1"), DataSource.FATSECRET, PENDING, is_synthetic=True
        )
        stored = save_result(
            conn, fatsecret_result("synthetic-scan-1"), DataSource.FATSECRET, PENDING
        )
    with inference.connect() as conn:
        row = conn.execute(
            select(permitted_results).where(permitted_results.c.run_id == "synthetic-scan-1")
        ).one()
        assert conn.execute(
            select(runs.c.is_synthetic).where(runs.c.run_id == "synthetic-scan-1")
        ).scalar_one()
        assert (
            conn.execute(
                select(stage_events.c.stage).where(stage_events.c.run_id == "synthetic-scan-1")
            ).scalar_one()
            == "image_prepare"
        )
    assert row.result == stored
    text_dump = str(row.result)
    assert "salmon" not in text_dump and "999" not in text_dump and "provider text" not in text_dump
    assert row.result["items"][0]["food_id"] == "synthetic-fs-1"
    assert "items[0].name" in row.dropped_fields
    assert row.policy_version == "pending"


def test_fatsecret_derived_metrics_refused_usda_allowed(login_as, owner):
    with owner.begin() as conn:
        save_scan_record(
            conn, scan_record("synthetic-scan-2"), DataSource.USDA, PENDING, is_synthetic=True
        )
    evaluator = login_as("fv_evaluator")
    with evaluator.begin() as conn:
        with pytest.raises(PolicyViolation):
            save_metric(
                conn,
                run_id="synthetic-scan-2",
                reference_version="synthetic",
                metric="abs_error_kcal",
                value=10.0,
                unit="kcal",
                source=DataSource.FATSECRET,
                policy=PENDING,
            )
        save_metric(
            conn,
            run_id="synthetic-scan-2",
            reference_version="synthetic",
            metric="abs_error_kcal",
            value=10.0,
            unit="kcal",
            source=DataSource.USDA,
            policy=PENDING,
        )
        stored = (
            conn.execute(
                text(
                    "SELECT source FROM benchmark.evaluation_metrics "
                    "WHERE run_id = 'synthetic-scan-2'"
                )
            )
            .scalars()
            .all()
        )
    assert stored == ["USDA"]


def test_object_store_keeps_bytes_out_of_postgres_and_deletes(login_as, tmp_path):
    store = LocalObjectStore(tmp_path / "images")
    inference = login_as("fv_inference")
    payload = b"SYNTHETIC image bytes"
    with inference.begin() as conn:
        kept = store_image(
            conn,
            store,
            payload,
            consent_basis="synthetic test fixture",
            retention_days=30,
            now=NOW,
            is_synthetic=True,
        )
        short = store_image(
            conn,
            store,
            b"SYNTHETIC short-lived",
            consent_basis="synthetic",
            retention_days=1,
            now=NOW,
            is_synthetic=True,
        )
    assert store.read(kept.object_key) == payload
    with inference.begin() as conn:
        row = conn.execute(select(images).where(images.c.image_id == kept.image_id)).one()
        assert row.original_sha256 == kept.original_sha256 and "SYNTHETIC" not in str(tuple(row))
        assert purge_expired(conn, store, NOW + timedelta(days=2)) == 1
        assert not store.exists(short.object_key) and store.exists(kept.object_key)
        assert delete_image(conn, store, kept.image_id, NOW) is True
        assert delete_image(conn, store, kept.image_id, NOW) is False
        tombstone = conn.execute(
            select(images.c.deleted_at).where(images.c.image_id == kept.image_id)
        ).scalar_one()
    assert tombstone == NOW and not store.exists(kept.object_key)


def test_failed_scan_is_persisted(owner):
    recorder = ScanRecorder(
        "synthetic-failed", "B_mock", budget=BudgetPolicy(), clock=ManualClock()
    )
    with owner.begin() as conn:
        save_scan_record(
            conn,
            recorder.finish(ScanStatus.FAILED, ErrorCode.INVALID_IMAGE),
            DataSource.MOCK,
            PENDING,
            is_synthetic=True,
        )
        status, code = conn.execute(
            select(runs.c.status, runs.c.error_code).where(runs.c.run_id == "synthetic-failed")
        ).one()
    assert (status, code) == ("failed", "invalid_image")
