"""Instrumented external calls with bounded retries (plan §10).

- One transient retry at most per logical request (configurable via the budget).
- Retry only rate limits, server errors, transport errors and timeouts. Never auth,
  client errors or refusals.
- Respect Retry-After, but never wait past the scan deadline.
- Each attempt's timeout is capped by the remaining deadline.
- Every attempt is recorded, including failures. Provider error text is never stored.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from foodvision.contracts.errors import ErrorCode
from foodvision.measurement.costs import PriceTable
from foodvision.measurement.events import (
    AttemptOutcome,
    AttemptRecord,
    CostEstimate,
    ProviderUsage,
    Stage,
)
from foodvision.measurement.spans import ScanRecorder

TRANSIENT = frozenset(
    {
        AttemptOutcome.TIMEOUT,
        AttemptOutcome.TRANSPORT_ERROR,
        AttemptOutcome.RATE_LIMITED,
        AttemptOutcome.SERVER_ERROR,
    }
)
ERROR_CODES = {
    AttemptOutcome.TIMEOUT: ErrorCode.TIMEOUT,
    AttemptOutcome.TRANSPORT_ERROR: ErrorCode.PROVIDER_ERROR,
    AttemptOutcome.RATE_LIMITED: ErrorCode.QUOTA,
    AttemptOutcome.SERVER_ERROR: ErrorCode.PROVIDER_ERROR,
    AttemptOutcome.CLIENT_ERROR: ErrorCode.PROVIDER_ERROR,
    AttemptOutcome.AUTH_ERROR: ErrorCode.AUTHENTICATION,
    AttemptOutcome.REFUSED: ErrorCode.REFUSED,
}
DEFAULT_BACKOFF_S = 0.5


@dataclass
class CallResult:
    value: Any
    http_status: int | None = None
    usage: ProviderUsage | None = None
    provider_model: str | None = None
    reported_cost: CostEstimate | None = None


class AttemptError(Exception):
    """Raised by a transport adapter. Carries codes only, never response bodies."""

    def __init__(
        self,
        outcome: AttemptOutcome,
        *,
        http_status: int | None = None,
        retry_after_s: float | None = None,
        usage: ProviderUsage | None = None,
        provider_model: str | None = None,
    ) -> None:
        super().__init__(outcome.value)
        self.outcome = outcome
        self.http_status = http_status
        self.retry_after_s = retry_after_s
        self.code = ERROR_CODES[outcome]
        # Set when the provider billed the attempt anyway (e.g. a refusal or truncation).
        self.usage = usage
        self.provider_model = provider_model


@dataclass
class CallSpec:
    provider: str
    operation: str
    is_model_call: bool
    request_timeout_s: float
    stage: Stage
    model: str | None = None
    expected_cost: CostEstimate = field(default_factory=CostEstimate.unknown)


def _status_class(status: int | None) -> str | None:
    return f"{status // 100}xx" if status is not None and 100 <= status < 600 else None


def _attempt_cost(
    spec: CallSpec,
    result: CallResult | None,
    error: "AttemptError | None",
    prices: PriceTable | None,
) -> CostEstimate:
    if result is not None and result.reported_cost is not None:
        return result.reported_cost
    usage = result.usage if result is not None else (error.usage if error else None)
    model = result.provider_model if result else (error.provider_model if error else None)
    if prices is not None and usage is not None:
        return prices.estimate(spec.provider, model or spec.model, usage)
    return CostEstimate.unknown()  # no usage reported, or unpriced: unknown, not zero


def call_with_retries(
    recorder: ScanRecorder,
    spec: CallSpec,
    send: Callable[[float], CallResult],
    *,
    prices: PriceTable | None = None,
) -> CallResult:
    """Run `send(timeout_s)` with budget checks and at most N transient retries."""
    logical_request_id = uuid.uuid4().hex
    max_attempts = 1 + recorder.budget.max_retries_per_request
    retry_reason: AttemptOutcome | None = None
    retry_after: float | None = None

    with recorder.span(spec.stage) as span:
        for attempt_number in range(1, max_attempts + 1):
            recorder.authorize_attempt(
                logical_request_id=logical_request_id,
                provider=spec.provider,
                operation=spec.operation,
                is_model_call=spec.is_model_call,
                expected_cost=spec.expected_cost,
            )
            timeout_s = max(1e-3, min(spec.request_timeout_s, recorder.remaining_s()))
            started_at, start_ns = recorder.clock.utc_now(), recorder.clock.monotonic_ns()

            result: CallResult | None = None
            error: AttemptError | None = None
            try:
                result = send(timeout_s)
            except TimeoutError:
                error = AttemptError(AttemptOutcome.TIMEOUT)
            except AttemptError as exc:
                error = exc

            outcome = AttemptOutcome.SUCCESS if error is None else error.outcome
            http_status = result.http_status if result is not None else error.http_status
            recorder.record_attempt(
                AttemptRecord(
                    attempt_id=uuid.uuid4().hex,
                    scan_id=recorder.scan_id,
                    span_id=span.span_id,
                    logical_request_id=logical_request_id,
                    attempt_number=attempt_number,
                    provider=spec.provider,
                    operation=spec.operation,
                    is_model_call=spec.is_model_call,
                    started_at_utc=started_at,
                    duration_ms=(recorder.clock.monotonic_ns() - start_ns) / 1e6,
                    timeout_s=timeout_s,
                    outcome=outcome,
                    http_status_class=_status_class(http_status),
                    retry_reason=retry_reason,
                    retry_after_s=retry_after,
                    usage=result.usage if result is not None else (error.usage if error else None),
                    provider_model=(
                        (result.provider_model if result else None)
                        or (error.provider_model if error else None)
                        or spec.model
                    ),
                    cost=_attempt_cost(spec, result, error, prices),
                )
            )
            if error is None:
                return result

            if error.outcome not in TRANSIENT or attempt_number == max_attempts:
                raise error
            wait = error.retry_after_s if error.retry_after_s is not None else DEFAULT_BACKOFF_S
            if wait >= recorder.remaining_s():
                raise error  # waiting would pass the deadline; the failed attempt is recorded
            recorder.clock.sleep(wait)
            retry_reason, retry_after = error.outcome, error.retry_after_s
    raise AssertionError("unreachable")
