"""Measurement Kit: spans, attempts, retries, budgets and costs with controlled clocks."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from foodvision.contracts.errors import ErrorCode
from foodvision.measurement.budget import BudgetExceeded, BudgetPolicy
from foodvision.measurement.clock import ManualClock
from foodvision.measurement.costs import Price, PriceTable
from foodvision.measurement.events import (
    AttemptOutcome,
    CacheState,
    CostEstimate,
    CostProvenance,
    ProviderUsage,
    ScanStatus,
    SpanRecord,
    SpanStatus,
    Stage,
)
from foodvision.measurement.retry import AttemptError, CallResult, CallSpec, call_with_retries
from foodvision.measurement.sinks import InMemorySink
from foodvision.measurement.spans import ScanRecorder

PRICES = PriceTable(
    version="synthetic-test-prices",
    source_url="test-only",
    prices={"anthropic/test-model": Price(input_usd_per_mtok=2.0, output_usd_per_mtok=10.0)},
)


def recorder(clock, **budget):
    return ScanRecorder(
        "scan-1", "B_test", budget=BudgetPolicy(**budget), clock=clock, sink=InMemorySink()
    )


class FakeTransport:
    """Scripted responses. Each step advances the clock by its duration first."""

    def __init__(self, clock: ManualClock, steps):
        self.clock, self.steps, self.timeouts = clock, list(steps), []

    def __call__(self, timeout_s: float) -> CallResult:
        self.timeouts.append(timeout_s)
        seconds, outcome = self.steps.pop(0)
        self.clock.advance(min(seconds, timeout_s))
        if isinstance(outcome, Exception):
            raise outcome
        if seconds > timeout_s:
            raise TimeoutError
        return outcome


def ok(input_tokens=1000, output_tokens=200):
    return CallResult(
        value="parsed",
        http_status=200,
        usage=ProviderUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        provider_model="test-model",
    )


def spec(**overrides):
    fields = dict(
        provider="anthropic",
        operation="recognize",
        is_model_call=True,
        request_timeout_s=20.0,
        stage=Stage.RECOGNITION,
        model="test-model",
    )
    return CallSpec(**(fields | overrides))


# --- Clocks and spans -----------------------------------------------------------------


def test_spans_use_monotonic_durations_and_utc_timestamps():
    clock = ManualClock()
    rec = recorder(clock)
    with rec.span(Stage.IMAGE_PREPARE):
        clock.advance(0.120)
    with rec.span(Stage.RECOGNITION) as outer:
        clock.advance(1.0)
        with rec.span(Stage.VALIDATION):
            clock.advance(0.010)
    record = rec.finish(ScanStatus.PARTIAL)
    prep, validation, recognition = record.spans
    assert prep.duration_ms == pytest.approx(120.0)
    assert recognition.duration_ms == pytest.approx(1010.0)
    assert validation.parent_span_id == outer.span_id
    assert prep.parent_span_id is None
    assert all(s.started_at_utc.tzinfo is not None for s in record.spans)
    assert record.server_total_ms == pytest.approx(1130.0)


def test_naive_or_non_utc_timestamps_rejected():
    fields = dict(
        span_id="s",
        parent_span_id=None,
        scan_id="x",
        stage=Stage.AUTH,
        duration_ms=1,
        status=SpanStatus.OK,
    )
    with pytest.raises(ValidationError, match="UTC"):
        SpanRecord(started_at_utc=datetime(2026, 1, 1), **fields)
    with pytest.raises(ValidationError, match="UTC"):
        SpanRecord(
            started_at_utc=datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=-7))), **fields
        )
    assert SpanRecord(started_at_utc=datetime(2026, 1, 1, tzinfo=UTC), **fields)


def test_overlapping_spans_are_not_added_into_wall_time():
    clock = ManualClock()
    rec = recorder(clock)
    with rec.span(Stage.LOOKUP) as parent:
        # Two lookups run concurrently: each takes 2 s, the wall clock moves 2 s.
        first = rec.span(Stage.LOOKUP, parent_span_id=parent.span_id)
        second = rec.span(Stage.LOOKUP, parent_span_id=parent.span_id)
        first.__enter__(), second.__enter__()
        clock.advance(2.0)
        second.__exit__(None, None, None), first.__exit__(None, None, None)
    record = rec.finish(ScanStatus.COMPLETE)
    assert record.server_total_ms == pytest.approx(2000.0)
    assert record.stage_ms[Stage.LOOKUP] == pytest.approx(6000.0)  # 2 s parent + 2 × 2 s
    assert record.stage_ms[Stage.LOOKUP] > record.server_total_ms


def test_span_records_errors_and_cache_state():
    clock = ManualClock()
    rec = recorder(clock)
    with pytest.raises(ValueError), rec.span(Stage.LOOKUP, cache_state=CacheState.MISS):
        raise ValueError("boom")
    assert rec.spans[0].status is SpanStatus.ERROR
    assert rec.spans[0].cache_state is CacheState.MISS


def test_failed_scans_are_recorded_and_emitted():
    rec = recorder(ManualClock())
    record = rec.finish(ScanStatus.FAILED, ErrorCode.INVALID_IMAGE)
    assert rec.sink.records[-1] is record
    assert record.status is ScanStatus.FAILED
    assert record.client_total_ms is None  # browser timing not implemented
    assert rec.finish(ScanStatus.COMPLETE) is record  # finishing twice cannot overwrite


# --- Attempts and retries -------------------------------------------------------------


def test_successful_call_records_one_attempt_with_usage_and_cost():
    clock = ManualClock()
    rec = recorder(clock)
    result = call_with_retries(rec, spec(), FakeTransport(clock, [(3.0, ok())]), prices=PRICES)
    assert result.value == "parsed"
    (attempt,) = rec.attempts
    assert attempt.outcome is AttemptOutcome.SUCCESS
    assert attempt.duration_ms == pytest.approx(3000.0)
    assert attempt.http_status_class == "2xx"
    # 1000 × $2/M + 200 × $10/M = $0.004
    assert attempt.cost.amount_usd == pytest.approx(0.004)
    assert attempt.cost.provenance is CostProvenance.PRICE_TABLE_ESTIMATE
    assert attempt.cost.price_table_version == "synthetic-test-prices"
    record = rec.finish(ScanStatus.COMPLETE)
    assert (record.attempts, record.model_calls, record.retries) == (1, 1, 0)
    assert record.estimated_cost_usd == pytest.approx(0.004)


def test_rate_limit_retries_once_honoring_retry_after():
    clock = ManualClock()
    rec = recorder(clock)
    transport = FakeTransport(
        clock,
        [
            (0.2, AttemptError(AttemptOutcome.RATE_LIMITED, http_status=429, retry_after_s=2.0)),
            (1.0, ok()),
        ],
    )
    call_with_retries(rec, spec(), transport, prices=PRICES)
    assert clock.sleeps == [2.0]
    first, second = rec.attempts
    assert first.outcome is AttemptOutcome.RATE_LIMITED and first.http_status_class == "4xx"
    assert first.cost.amount_usd is None  # failed attempt: unknown, not zero
    assert second.attempt_number == 2 and second.retry_reason is AttemptOutcome.RATE_LIMITED
    assert second.retry_after_s == 2.0
    assert first.logical_request_id == second.logical_request_id
    record = rec.finish(ScanStatus.COMPLETE)
    assert (record.logical_requests, record.attempts, record.retries) == (1, 2, 1)
    assert record.estimated_cost_usd is None  # one attempt's cost is unknown
    assert record.known_cost_usd == pytest.approx(0.004)


def test_only_one_retry_per_logical_request():
    clock = ManualClock()
    rec = recorder(clock)
    error = AttemptError(AttemptOutcome.SERVER_ERROR, http_status=503)
    transport = FakeTransport(clock, [(0.1, error), (0.1, error), (0.1, ok())])
    with pytest.raises(AttemptError):
        call_with_retries(rec, spec(), transport)
    assert len(rec.attempts) == 2
    assert len(transport.steps) == 1  # third attempt never made


@pytest.mark.parametrize(
    "outcome", [AttemptOutcome.AUTH_ERROR, AttemptOutcome.CLIENT_ERROR, AttemptOutcome.REFUSED]
)
def test_non_transient_failures_are_not_retried(outcome):
    clock = ManualClock()
    rec = recorder(clock)
    with pytest.raises(AttemptError) as info:
        call_with_retries(rec, spec(), FakeTransport(clock, [(0.1, AttemptError(outcome))]))
    assert len(rec.attempts) == 1
    assert clock.sleeps == []
    assert rec.spans[-1].status is SpanStatus.ERROR
    assert rec.spans[-1].error_code is info.value.code


def test_timeout_is_recorded_and_retried():
    clock = ManualClock()
    rec = recorder(clock)
    transport = FakeTransport(clock, [(25.0, ok()), (1.0, ok())])  # first exceeds 20 s timeout
    call_with_retries(rec, spec(), transport)
    first, second = rec.attempts
    assert first.outcome is AttemptOutcome.TIMEOUT
    assert first.duration_ms == pytest.approx(20000.0)
    assert second.outcome is AttemptOutcome.SUCCESS
    assert rec.finish(ScanStatus.COMPLETE).timeouts == 1


def test_attempt_timeout_is_capped_by_remaining_deadline():
    clock = ManualClock()
    rec = recorder(clock, deadline_s=10.0)
    clock.advance(7.0)
    transport = FakeTransport(clock, [(0.5, ok())])
    call_with_retries(rec, spec(request_timeout_s=20.0), transport)
    assert transport.timeouts == [pytest.approx(3.0)]


def test_retry_not_attempted_when_retry_after_passes_deadline():
    clock = ManualClock()
    rec = recorder(clock, deadline_s=5.0)
    transport = FakeTransport(
        clock, [(1.0, AttemptError(AttemptOutcome.RATE_LIMITED, retry_after_s=30.0)), (1.0, ok())]
    )
    with pytest.raises(AttemptError):
        call_with_retries(rec, spec(), transport)
    assert clock.sleeps == [] and len(rec.attempts) == 1


def test_provider_error_text_is_never_stored():
    clock = ManualClock()
    rec = recorder(clock)
    secret_body = "provider said: grilled salmon SENTINEL-BODY-7731 kcal"
    error = AttemptError(AttemptOutcome.CLIENT_ERROR, http_status=400)
    error.provider_body = secret_body  # even if an adapter attached it
    with pytest.raises(AttemptError):
        call_with_retries(rec, spec(), FakeTransport(clock, [(0.1, error)]))
    dumped = rec.finish(ScanStatus.FAILED, ErrorCode.PROVIDER_ERROR).model_dump_json()
    assert "salmon" not in dumped and "SENTINEL-BODY-7731" not in dumped


# --- Budgets --------------------------------------------------------------------------


def test_model_call_budget_enforced_and_blocked_attempt_recorded():
    clock = ManualClock()
    rec = recorder(clock, max_model_calls=2)
    for _ in range(2):
        call_with_retries(rec, spec(), FakeTransport(clock, [(0.1, ok())]))
    transport = FakeTransport(clock, [(0.1, ok())])
    with pytest.raises(BudgetExceeded, match="max_model_calls"):
        call_with_retries(rec, spec(), transport)
    assert transport.timeouts == []  # never called
    record = rec.finish(ScanStatus.PARTIAL)
    assert record.model_calls == 2 and record.blocked_attempts == 1
    assert record.blocked[0].reason == "max_model_calls"
    assert record.spans[-1].status is SpanStatus.BUDGET_EXCEEDED


def test_provider_app_allows_zero_model_calls():
    clock = ManualClock()
    rec = recorder(clock, max_model_calls=0)
    with pytest.raises(BudgetExceeded, match="max_model_calls"):
        call_with_retries(rec, spec(), FakeTransport(clock, [(0.1, ok())]))
    call_with_retries(rec, spec(is_model_call=False), FakeTransport(clock, [(0.1, ok())]))


def test_total_attempt_budget_counts_retries():
    clock = ManualClock()
    rec = recorder(clock, max_attempts=3)
    error = AttemptError(AttemptOutcome.SERVER_ERROR, http_status=500)
    with pytest.raises(AttemptError):
        call_with_retries(rec, spec(is_model_call=False), FakeTransport(clock, [(0.1, error)] * 2))
    call_with_retries(rec, spec(is_model_call=False), FakeTransport(clock, [(0.1, ok())]))
    with pytest.raises(BudgetExceeded, match="max_attempts"):
        call_with_retries(rec, spec(is_model_call=False), FakeTransport(clock, [(0.1, ok())]))


def test_deadline_budget_enforced():
    clock = ManualClock()
    rec = recorder(clock, deadline_s=45.0)
    clock.advance(45.0)
    with pytest.raises(BudgetExceeded, match="deadline") as info:
        call_with_retries(rec, spec(), FakeTransport(clock, [(0.1, ok())]))
    assert info.value.code is ErrorCode.TIMEOUT


def test_cost_budget_uses_known_costs_and_refuses_unknown_under_cap():
    clock = ManualClock()
    rec = recorder(clock, max_cost_usd=0.005)
    priced = spec(expected_cost=CostEstimate(amount_usd=0.004))
    call_with_retries(rec, priced, FakeTransport(clock, [(0.1, ok())]), prices=PRICES)
    with pytest.raises(BudgetExceeded, match="max_cost"):
        call_with_retries(rec, priced, FakeTransport(clock, [(0.1, ok())]), prices=PRICES)
    with pytest.raises(BudgetExceeded, match="cost_unknown_under_cap"):
        call_with_retries(rec, spec(), FakeTransport(clock, [(0.1, ok())]))


def test_no_dollar_cap_allows_unknown_costs():
    clock = ManualClock()
    rec = recorder(clock)  # max_cost_usd=None (user decision: no dollar cap)
    call_with_retries(rec, spec(), FakeTransport(clock, [(0.1, ok())]))
    assert rec.finish(ScanStatus.COMPLETE).estimated_cost_usd is None


# --- Costs ----------------------------------------------------------------------------


def test_unknown_model_or_missing_usage_stays_unknown():
    assert (
        PRICES.estimate("anthropic", "other-model", ProviderUsage(input_tokens=1)).amount_usd
        is None
    )
    assert PRICES.estimate("anthropic", "test-model", None).amount_usd is None
    assert (
        PRICES.estimate("anthropic", "test-model", ProviderUsage(input_tokens=5)).amount_usd is None
    )


def test_provider_reported_cost_wins_over_estimate():
    clock = ManualClock()
    rec = recorder(clock)
    reported = CostEstimate(amount_usd=0.01, provenance=CostProvenance.PROVIDER_REPORTED)
    result = ok()
    result.reported_cost = reported
    call_with_retries(rec, spec(), FakeTransport(clock, [(0.1, result)]), prices=PRICES)
    assert rec.attempts[0].cost == reported
