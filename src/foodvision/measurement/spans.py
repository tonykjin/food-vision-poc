"""Per-scan recorder: monotonic spans with parents, attempts, budgets, and a final record.

Every scan ends in exactly one ScanRecord, including failed scans. Parent spans default to
the innermost open span; pass `parent_span_id` explicitly for work run concurrently.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from foodvision.contracts.errors import ErrorCode
from foodvision.measurement.budget import BudgetExceeded, BudgetPolicy
from foodvision.measurement.clock import Clock, SystemClock
from foodvision.measurement.costs import total_cost
from foodvision.measurement.events import (
    AttemptRecord,
    BlockedAttempt,
    CacheState,
    CostEstimate,
    ScanRecord,
    ScanStatus,
    SpanRecord,
    SpanStatus,
    Stage,
)
from foodvision.measurement.sinks import EventSink


def _ms(ns: int) -> float:
    return ns / 1_000_000


@dataclass
class SpanHandle:
    span_id: str
    cache_state: CacheState = CacheState.NOT_APPLICABLE


class ScanRecorder:
    def __init__(
        self,
        scan_id: str,
        pipeline_id: str,
        *,
        budget: BudgetPolicy,
        configuration_id: str | None = None,
        is_mock: bool = False,
        clock: Clock | None = None,
        sink: EventSink | None = None,
    ) -> None:
        self.scan_id = scan_id
        self.pipeline_id = pipeline_id
        self.configuration_id = configuration_id
        self.is_mock = is_mock
        self.budget = budget
        self.clock = clock or SystemClock()
        self.sink = sink
        self._start_ns = self.clock.monotonic_ns()
        self._started_at = self.clock.utc_now()
        self._stack: list[str] = []
        self.spans: list[SpanRecord] = []
        self.attempts: list[AttemptRecord] = []
        self.blocked: list[BlockedAttempt] = []
        self._logical: set[str] = set()
        self._finished: ScanRecord | None = None

    # --- time ---------------------------------------------------------------------

    def elapsed_s(self) -> float:
        return (self.clock.monotonic_ns() - self._start_ns) / 1e9

    def remaining_s(self) -> float:
        return self.budget.deadline_s - self.elapsed_s()

    @contextmanager
    def span(
        self,
        stage: Stage,
        *,
        parent_span_id: str | None = None,
        cache_state: CacheState = CacheState.NOT_APPLICABLE,
    ) -> Iterator[SpanHandle]:
        handle = SpanHandle(span_id=uuid.uuid4().hex, cache_state=cache_state)
        parent = (
            parent_span_id
            if parent_span_id is not None
            else (self._stack[-1] if self._stack else None)
        )
        started_at, start_ns = self.clock.utc_now(), self.clock.monotonic_ns()
        status, error_code = SpanStatus.OK, None
        self._stack.append(handle.span_id)
        try:
            yield handle
        except BudgetExceeded as exc:
            status, error_code = SpanStatus.BUDGET_EXCEEDED, exc.code
            raise
        except TimeoutError:
            status, error_code = SpanStatus.TIMEOUT, ErrorCode.TIMEOUT
            raise
        except Exception as exc:
            status, error_code = SpanStatus.ERROR, getattr(exc, "code", None)
            raise
        finally:
            self._stack.remove(handle.span_id)
            self.spans.append(
                SpanRecord(
                    span_id=handle.span_id,
                    parent_span_id=parent,
                    scan_id=self.scan_id,
                    stage=stage,
                    started_at_utc=started_at,
                    duration_ms=_ms(self.clock.monotonic_ns() - start_ns),
                    status=status,
                    error_code=error_code if isinstance(error_code, ErrorCode) else None,
                    cache_state=handle.cache_state,
                )
            )

    def current_span_id(self) -> str | None:
        return self._stack[-1] if self._stack else None

    # --- budgets and attempts -----------------------------------------------------

    def _spent(self) -> float:
        return sum(a.cost.amount_usd or 0.0 for a in self.attempts)

    def authorize_attempt(
        self,
        *,
        logical_request_id: str,
        provider: str,
        operation: str,
        is_model_call: bool,
        expected_cost: CostEstimate,
    ) -> None:
        """Raise BudgetExceeded (and record the refusal) if this attempt may not start."""
        reason = None
        if self.remaining_s() <= 0:
            reason = "deadline"
        elif len(self.attempts) >= self.budget.max_attempts:
            reason = "max_attempts"
        elif is_model_call and self.model_calls >= self.budget.max_model_calls:
            reason = "max_model_calls"
        elif self.budget.max_cost_usd is not None:
            if expected_cost.amount_usd is None:
                if self.budget.refuse_unknown_cost_under_cap:
                    reason = "cost_unknown_under_cap"
            elif self._spent() + expected_cost.amount_usd > self.budget.max_cost_usd:
                reason = "max_cost"
        if reason is not None:
            self.blocked.append(
                BlockedAttempt(
                    scan_id=self.scan_id,
                    logical_request_id=logical_request_id,
                    provider=provider,
                    operation=operation,
                    reason=reason,
                    at_utc=self.clock.utc_now(),
                )
            )
            raise BudgetExceeded(reason)
        self._logical.add(logical_request_id)

    def record_attempt(self, record: AttemptRecord) -> None:
        self.attempts.append(record)

    @property
    def model_calls(self) -> int:
        return sum(1 for a in self.attempts if a.is_model_call)

    # --- completion ---------------------------------------------------------------

    def finish(self, status: ScanStatus, error_code: ErrorCode | None = None) -> ScanRecord:
        if self._finished is not None:
            return self._finished
        stage_ms: dict[Stage, float] = {}
        for span in self.spans:
            stage_ms[span.stage] = stage_ms.get(span.stage, 0.0) + span.duration_ms
        known, total = total_cost([a.cost for a in self.attempts])
        self._finished = ScanRecord(
            scan_id=self.scan_id,
            pipeline_id=self.pipeline_id,
            configuration_id=self.configuration_id,
            is_mock=self.is_mock,
            status=status,
            error_code=error_code,
            started_at_utc=self._started_at,
            finished_at_utc=self.clock.utc_now(),
            server_total_ms=_ms(self.clock.monotonic_ns() - self._start_ns),
            stage_ms=stage_ms,
            logical_requests=len(self._logical),
            attempts=len(self.attempts),
            model_calls=self.model_calls,
            retries=sum(1 for a in self.attempts if a.attempt_number > 1),
            timeouts=sum(1 for a in self.attempts if a.outcome == "timeout"),
            blocked_attempts=len(self.blocked),
            known_cost_usd=known,
            estimated_cost_usd=total,
            spans=list(self.spans),
            attempt_records=list(self.attempts),
            blocked=list(self.blocked),
        )
        if self.sink is not None:
            self.sink.emit(self._finished)
        return self._finished
