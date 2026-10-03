"""Typed, payload-free telemetry records (plan §10).

Records hold IDs, stages, codes, counts, timings and costs only. They never hold images,
prompts, provider response bodies, food names or nutrient values, and provider error
messages are reduced to codes, so every field is payload-free metadata (see storage_policy).
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from foodvision.contracts.errors import ErrorCode


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset().total_seconds() != 0:
        raise ValueError("event timestamps must be timezone-aware UTC")
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
NonNegativeMs = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Stage(StrEnum):
    """Stages from the plan §10 timing table, plus `mock` for synthetic runs."""

    IMAGE_PREPARE = "image_prepare"
    AUTH = "auth"
    RECOGNITION = "recognition"
    LOOKUP = "lookup"
    SELECTION = "selection"
    CALCULATION = "calculation"
    VALIDATION = "validation"
    STORAGE = "storage"
    EVALUATION = "evaluation"
    MOCK = "mock"


class SpanStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    BUDGET_EXCEEDED = "budget_exceeded"


class CacheState(StrEnum):
    """Application-level cache only; we never claim to know a vendor's internal cache."""

    HIT = "hit"
    MISS = "miss"
    DISABLED = "disabled"
    NOT_APPLICABLE = "not_applicable"


class AttemptOutcome(StrEnum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    TRANSPORT_ERROR = "transport_error"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    CLIENT_ERROR = "client_error"
    AUTH_ERROR = "auth_error"
    REFUSED = "refused"


class CostProvenance(StrEnum):
    PROVIDER_REPORTED = "provider_reported"
    PRICE_TABLE_ESTIMATE = "price_table_estimate"
    UNKNOWN = "unknown"


class ProviderUsage(Strict):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    images: int | None = Field(default=None, ge=0)


class CostEstimate(Strict):
    amount_usd: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    provenance: CostProvenance = CostProvenance.UNKNOWN
    price_table_version: str | None = None

    @classmethod
    def unknown(cls) -> "CostEstimate":
        return cls()


class SpanRecord(Strict):
    span_id: str
    parent_span_id: str | None
    scan_id: str
    stage: Stage
    started_at_utc: UtcDatetime
    duration_ms: NonNegativeMs
    status: SpanStatus
    error_code: ErrorCode | None = None
    cache_state: CacheState = CacheState.NOT_APPLICABLE


class AttemptRecord(Strict):
    attempt_id: str
    scan_id: str
    span_id: str | None
    logical_request_id: str
    attempt_number: int = Field(ge=1)
    provider: str
    operation: str
    is_model_call: bool
    started_at_utc: UtcDatetime
    duration_ms: NonNegativeMs
    timeout_s: Annotated[float, Field(gt=0)]
    outcome: AttemptOutcome
    http_status_class: str | None = Field(default=None, pattern=r"^[1-5]xx$")
    retry_reason: AttemptOutcome | None = None  # why this attempt is a retry
    retry_after_s: float | None = Field(default=None, ge=0)
    usage: ProviderUsage | None = None
    provider_model: str | None = None
    cost: CostEstimate = Field(default_factory=CostEstimate)


class BlockedAttempt(Strict):
    """An attempt the budget refused to start. Not a call, but never hidden."""

    scan_id: str
    logical_request_id: str
    provider: str
    operation: str
    reason: str
    at_utc: UtcDatetime


class ScanStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    ABSTAINED = "abstained"
    FAILED = "failed"


class ScanRecord(Strict):
    scan_id: str
    pipeline_id: str
    configuration_id: str | None
    is_mock: bool
    status: ScanStatus
    error_code: ErrorCode | None = None
    started_at_utc: UtcDatetime
    finished_at_utc: UtcDatetime
    server_total_ms: NonNegativeMs
    # Sum per stage; overlapping spans can make this exceed server_total_ms (wall time).
    stage_ms: dict[Stage, NonNegativeMs]
    # Measured in the browser only. A Python HTTP wait is not click-to-render latency.
    client_total_ms: None = None
    logical_requests: int = Field(ge=0)
    attempts: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    retries: int = Field(ge=0)
    timeouts: int = Field(ge=0)
    blocked_attempts: int = Field(ge=0)
    known_cost_usd: Annotated[float, Field(ge=0)]
    estimated_cost_usd: Annotated[float, Field(ge=0)] | None  # None if any attempt cost unknown
    spans: list[SpanRecord]
    attempt_records: list[AttemptRecord]
    blocked: list[BlockedAttempt]
