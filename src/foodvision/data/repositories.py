"""Telemetry and result writes. Every result write goes through the storage policy."""

from datetime import datetime

from sqlalchemy import Connection, insert

from foodvision.contracts.results import AnalysisResult
from foodvision.data.models import (
    attempt_events,
    evaluation_metrics,
    permitted_results,
    runs,
    stage_events,
)
from foodvision.measurement.events import ScanRecord
from foodvision.measurement.storage_policy import (
    DataSource,
    Purpose,
    StoragePolicy,
    export_scan_record,
    filter_result,
    require_metric_storage,
)


def save_scan_record(
    conn: Connection,
    record: ScanRecord,
    source: DataSource,
    policy: StoragePolicy,
    *,
    is_synthetic: bool = False,
    sample_id: str | None = None,
    batch_id: str | None = None,
) -> None:
    """Persist a payload-free ScanRecord with its spans and attempts."""
    data = export_scan_record(record, source, policy, Purpose.PERSIST)
    conn.execute(
        insert(runs).values(
            run_id=record.scan_id,
            pipeline_id=record.pipeline_id,
            config_id=None,
            batch_id=batch_id,
            sample_id=sample_id,
            status=data["status"],
            error_code=data["error_code"],
            is_mock=record.is_mock,
            is_synthetic=is_synthetic,
            started_at=record.started_at_utc,
            finished_at=record.finished_at_utc,
            server_total_ms=record.server_total_ms,
            logical_requests=record.logical_requests,
            attempts=record.attempts,
            model_calls=record.model_calls,
            retries=record.retries,
            timeouts=record.timeouts,
            blocked_attempts=record.blocked_attempts,
            known_cost_usd=record.known_cost_usd,
            estimated_cost_usd=record.estimated_cost_usd,
        )
    )
    if record.spans:
        conn.execute(
            insert(stage_events),
            [
                {
                    "run_id": record.scan_id,
                    "span_id": s.span_id,
                    "parent_span_id": s.parent_span_id,
                    "stage": s.stage.value,
                    "started_at": s.started_at_utc,
                    "duration_ms": s.duration_ms,
                    "status": s.status.value,
                    "error_code": s.error_code.value if s.error_code else None,
                    "cache_state": s.cache_state.value,
                }
                for s in record.spans
            ],
        )
    if record.attempt_records:
        conn.execute(
            insert(attempt_events),
            [
                {
                    "attempt_id": a.attempt_id,
                    "run_id": record.scan_id,
                    "span_id": a.span_id,
                    "logical_request_id": a.logical_request_id,
                    "attempt_number": a.attempt_number,
                    "provider": a.provider,
                    "operation": a.operation,
                    "is_model_call": a.is_model_call,
                    "started_at": a.started_at_utc,
                    "duration_ms": a.duration_ms,
                    "timeout_s": a.timeout_s,
                    "outcome": a.outcome.value,
                    "http_status_class": a.http_status_class,
                    "retry_reason": a.retry_reason.value if a.retry_reason else None,
                    "retry_after_s": a.retry_after_s,
                    "input_tokens": a.usage.input_tokens if a.usage else None,
                    "output_tokens": a.usage.output_tokens if a.usage else None,
                    "provider_model": a.provider_model,
                    "cost_usd": a.cost.amount_usd,
                    "cost_provenance": a.cost.provenance.value,
                    "price_table_version": a.cost.price_table_version,
                }
                for a in record.attempt_records
            ],
        )


def save_result(
    conn: Connection,
    result: AnalysisResult,
    source: DataSource,
    policy: StoragePolicy,
    *,
    expires_at: datetime | None = None,
) -> dict:
    """Persist only the fields the source's policy allows; returns what was stored."""
    filtered = filter_result(result, source, policy, Purpose.PERSIST)
    meta = filtered.pop("_policy")
    conn.execute(
        insert(permitted_results).values(
            run_id=result.scan_id,
            source=source.value,
            policy_version=policy.version,
            result=filtered,
            dropped_fields=meta["dropped"],
            expires_at=expires_at,
        )
    )
    return filtered


def save_metric(
    conn: Connection,
    *,
    run_id: str,
    reference_version: str,
    metric: str,
    value: float | None,
    unit: str | None,
    source: DataSource,
    policy: StoragePolicy,
) -> None:
    """Evaluator-side metric write; refused for sources whose rights don't allow it."""
    require_metric_storage(source, policy, Purpose.PERSIST)
    conn.execute(
        insert(evaluation_metrics).values(
            run_id=run_id,
            reference_version=reference_version,
            metric=metric,
            value=value,
            unit=unit,
            source=source.value,
            policy_version=policy.version,
        )
    )
