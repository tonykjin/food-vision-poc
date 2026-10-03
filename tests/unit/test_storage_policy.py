"""Storage policy: pending fatsecret rights keep restricted content and derived metrics out."""

import json

import pytest

from foodvision.contracts.errors import ErrorCode, ErrorDetail
from foodvision.contracts.results import (
    AnalysisResult,
    Confidence,
    ConfidenceType,
    FoodSource,
    Nutrients,
    PortionMethod,
    ResultItem,
    Totals,
    TotalsStatus,
)
from foodvision.measurement.budget import BudgetPolicy
from foodvision.measurement.clock import ManualClock
from foodvision.measurement.events import ScanStatus
from foodvision.measurement.spans import ScanRecorder
from foodvision.measurement.storage_policy import (
    FATSECRET_GRANTS,
    DataClass,
    DataSource,
    PolicyViolation,
    Purpose,
    StoragePolicy,
    export_scan_record,
    filter_result,
    policy_from_settings,
    require_metric_storage,
)

PENDING = StoragePolicy()
DURABLE = [Purpose.PERSIST, Purpose.EXPORT, Purpose.LOG, Purpose.ERROR_REPORT, Purpose.FIXTURE]


def fatsecret_result(status="partial", error=None) -> AnalysisResult:
    item = ResultItem(
        name="Grilled Salmon",
        preparation="grilled",
        resolved=True,
        portion_g=154,
        portion_method=PortionMethod.PROVIDER_SUGGESTED,
        food_source=FoodSource.FATSECRET,
        food_id="fs-food-123",
        serving_id="fs-serving-456",
        nutrients=Nutrients(energy_kcal=412, protein_g=39),
        uncertainty_reasons=["provider portion"],
    )
    totals = Totals(
        status=TotalsStatus.PARTIAL, nutrients=Nutrients(energy_kcal=412), included_items=1
    )
    if status == "failed":
        item, totals = None, Totals(status=TotalsStatus.UNAVAILABLE)
    return AnalysisResult(
        scan_id="scan-9",
        pipeline_id="A_native",
        is_mock=False,
        status=status,
        items=[item] if item else [],
        totals=totals,
        confidence=Confidence(type=ConfidenceType.HEURISTIC_UNCALIBRATED, label="medium"),
        warnings=["fatsecret: salmon matched"],
        error=error,
    )


@pytest.mark.parametrize("purpose", DURABLE)
def test_pending_fatsecret_denies_restricted_content_and_metrics(purpose):
    assert not PENDING.allows(DataSource.FATSECRET, DataClass.RESTRICTED_CONTENT, purpose)
    assert not PENDING.allows(DataSource.FATSECRET, DataClass.DERIVED_METRIC, purpose)
    assert PENDING.allows(DataSource.FATSECRET, DataClass.PAYLOAD_FREE_METADATA, purpose)


def test_pending_fatsecret_ids_are_storable_but_not_fixtures():
    for purpose in (Purpose.PERSIST, Purpose.EXPORT, Purpose.LOG):
        assert PENDING.allows(DataSource.FATSECRET, DataClass.PERMITTED_ID, purpose)
    assert not PENDING.allows(DataSource.FATSECRET, DataClass.PERMITTED_ID, Purpose.FIXTURE)


def test_transient_evaluation_in_memory_is_allowed():
    for data_class in DataClass:
        assert PENDING.allows(DataSource.FATSECRET, data_class, Purpose.TRANSIENT_EVALUATION)


@pytest.mark.parametrize("source", [DataSource.USDA, DataSource.VISION_MODEL, DataSource.MOCK])
def test_unrestricted_sources(source):
    for data_class in DataClass:
        assert PENDING.allows(source, data_class, Purpose.PERSIST)


def test_filtered_fatsecret_result_keeps_ids_and_metadata_only():
    out = filter_result(fatsecret_result(), DataSource.FATSECRET, PENDING, Purpose.PERSIST)
    text = json.dumps(out)
    for restricted in ("Salmon", "salmon", "412", "grilled", "154", "medium"):
        assert restricted not in text
    item = out["items"][0]
    assert item == {
        "resolved": True,
        "portion_method": "provider_suggested",
        "food_source": "fatsecret",
        "food_id": "fs-food-123",
        "serving_id": "fs-serving-456",
    }
    assert out["totals"] == {"status": "partial", "included_items": 1, "excluded_items": 0}
    assert out["scan_id"] == "scan-9" and out["status"] == "partial"
    assert {"items[0].name", "items[0].nutrients", "warnings", "confidence"} <= set(
        out["_policy"]["dropped"]
    )


def test_error_payloads_are_dropped_from_fatsecret_error_reports():
    error = ErrorDetail(code=ErrorCode.PROVIDER_ERROR, message="body: salmon 412 kcal")
    out = filter_result(
        fatsecret_result("failed", error), DataSource.FATSECRET, PENDING, Purpose.ERROR_REPORT
    )
    assert out["error"] == {"code": "provider_error", "retryable": False}
    assert "salmon" not in json.dumps(out)


def test_usda_result_passes_through_unfiltered():
    out = filter_result(fatsecret_result(), DataSource.USDA, PENDING, Purpose.EXPORT)
    assert out["items"][0]["name"] == "Grilled Salmon"
    assert out["_policy"]["dropped"] == []


def test_derived_metrics_cannot_be_persisted_while_pending():
    with pytest.raises(PolicyViolation):
        require_metric_storage(DataSource.FATSECRET, PENDING, Purpose.PERSIST)
    require_metric_storage(DataSource.FATSECRET, PENDING, Purpose.TRANSIENT_EVALUATION)
    require_metric_storage(DataSource.USDA, PENDING, Purpose.PERSIST)


def test_scan_records_are_exportable_payload_free_metadata():
    rec = ScanRecorder("s", "A_native", budget=BudgetPolicy(), clock=ManualClock())
    exported = export_scan_record(
        rec.finish(ScanStatus.FAILED, ErrorCode.TIMEOUT),
        DataSource.FATSECRET,
        PENDING,
        Purpose.PERSIST,
    )
    assert exported["status"] == "failed" and exported["error_code"] == "timeout"


def test_settings_cannot_enable_persistence_without_a_recorded_grant():
    assert policy_from_settings(False, "pending").fatsecret_pending
    assert policy_from_settings(True, "pending").fatsecret_pending  # version still pending
    assert FATSECRET_GRANTS == {}  # no written grant recorded yet
    with pytest.raises(ValueError, match="no written grant"):
        policy_from_settings(True, "fatsecret-2026-11")
