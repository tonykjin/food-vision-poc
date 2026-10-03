"""USDA API client: instrumented retries, no key leakage. Uses httpx.MockTransport (no network)."""

import httpx
import pytest

from foodvision.measurement.budget import BudgetPolicy
from foodvision.measurement.clock import ManualClock
from foodvision.measurement.events import AttemptOutcome, ScanStatus
from foodvision.measurement.retry import AttemptError
from foodvision.measurement.spans import ScanRecorder
from foodvision.providers.usda_client import MAX_IDS_PER_REQUEST, UsdaClient

KEY = "SENTINEL-USDA-KEY-123"


def client(responses):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return UsdaClient(KEY, http=httpx.Client(transport=httpx.MockTransport(handler))), calls


def recorder():
    return ScanRecorder(
        "s", "catalog_import", budget=BudgetPolicy(max_model_calls=0), clock=ManualClock()
    )


def test_batches_ids_and_records_attempts():
    ids = list(range(1, MAX_IDS_PER_REQUEST + 3))
    usda, calls = client(
        [httpx.Response(200, json=[{"fdcId": 1}]), httpx.Response(200, json=[{"fdcId": 2}])]
    )
    rec = recorder()
    foods = usda.fetch_foods(ids, rec)
    assert [f["fdcId"] for f in foods] == [1, 2]
    assert len(calls) == 2 and calls[0].url.params["api_key"] == KEY
    assert rec.finish(ScanStatus.COMPLETE).attempts == 2


def test_rate_limit_is_retried_with_retry_after():
    usda, _ = client(
        [httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(200, json=[])]
    )
    rec = recorder()
    usda.fetch_foods([1], rec)
    first, second = rec.attempts
    assert first.outcome is AttemptOutcome.RATE_LIMITED and first.http_status_class == "4xx"
    assert second.outcome is AttemptOutcome.SUCCESS
    assert second.retry_reason is AttemptOutcome.RATE_LIMITED and second.retry_after_s == 3.0
    assert rec.clock.sleeps == [3.0]


def test_auth_failure_not_retried_and_key_never_leaks():
    usda, calls = client([httpx.Response(403, text=f"bad key {KEY}")])
    rec = recorder()
    with pytest.raises(AttemptError) as info:
        usda.fetch_foods([1], rec)
    assert info.value.outcome is AttemptOutcome.AUTH_ERROR and len(calls) == 1
    record = rec.finish(ScanStatus.FAILED, info.value.code)
    assert KEY not in str(info.value) and KEY not in record.model_dump_json()


def test_timeout_and_transport_errors_hide_the_url():
    usda, _ = client(
        [
            httpx.ReadTimeout("timed out at https://x?api_key=" + KEY),
            httpx.ConnectError("refused https://x?api_key=" + KEY),
        ]
    )
    rec = recorder()
    with pytest.raises(AttemptError) as info:
        usda.fetch_foods([1], rec)
    assert [a.outcome for a in rec.attempts] == [
        AttemptOutcome.TIMEOUT,
        AttemptOutcome.TRANSPORT_ERROR,
    ]
    assert KEY not in repr(info.value) and info.value.__cause__ is None
