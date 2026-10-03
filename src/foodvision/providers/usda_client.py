"""Instrumented FoodData Central API client (fallback for records not taken from downloads).

https://fdc.nal.usda.gov/api-guide/ (checked 2026-10-02): `POST /v1/foods` takes `fdcIds`;
the key is the `api_key` query parameter; default limit 1,000 requests/hour per IP (HTTP 429
when exceeded). Every attempt goes through the Measurement Kit retry engine. Errors carry
codes only: the request URL (which contains the key) is never logged or raised.
"""

from collections.abc import Sequence
from typing import Any

import httpx

from foodvision.measurement.events import AttemptOutcome, Stage
from foodvision.measurement.retry import AttemptError, CallResult, CallSpec, call_with_retries
from foodvision.measurement.spans import ScanRecorder

API_BASE = "https://api.nal.usda.gov/fdc/v1"
MAX_IDS_PER_REQUEST = 20


def _classify(response: httpx.Response) -> AttemptError | None:
    status = response.status_code
    if status < 400:
        return None
    if status == 429:
        retry_after = response.headers.get("Retry-After")
        seconds = float(retry_after) if retry_after and retry_after.isdigit() else None
        return AttemptError(AttemptOutcome.RATE_LIMITED, http_status=status, retry_after_s=seconds)
    if status in (401, 403):
        return AttemptError(AttemptOutcome.AUTH_ERROR, http_status=status)
    if status >= 500:
        return AttemptError(AttemptOutcome.SERVER_ERROR, http_status=status)
    return AttemptError(AttemptOutcome.CLIENT_ERROR, http_status=status)


class UsdaClient:
    def __init__(self, api_key: str, http: httpx.Client | None = None, timeout_s: float = 15.0):
        self._key = api_key
        self._http = http or httpx.Client()
        self._timeout_s = timeout_s

    def fetch_foods(self, fdc_ids: Sequence[int], recorder: ScanRecorder) -> list[dict[str, Any]]:
        foods: list[dict[str, Any]] = []
        for start in range(0, len(fdc_ids), MAX_IDS_PER_REQUEST):
            batch = [int(i) for i in fdc_ids[start : start + MAX_IDS_PER_REQUEST]]

            def send(timeout_s: float, batch=batch) -> CallResult:
                try:
                    response = self._http.post(
                        f"{API_BASE}/foods",
                        params={"api_key": self._key},
                        json={"fdcIds": batch, "format": "full"},
                        timeout=timeout_s,
                    )
                except httpx.TimeoutException:
                    raise TimeoutError from None  # drop the exception text (it has the URL)
                except httpx.TransportError:
                    raise AttemptError(AttemptOutcome.TRANSPORT_ERROR) from None
                failure = _classify(response)
                if failure is not None:
                    raise failure
                return CallResult(value=response.json(), http_status=response.status_code)

            spec = CallSpec(
                provider="usda_fdc",
                operation="foods",
                is_model_call=False,
                request_timeout_s=self._timeout_s,
                stage=Stage.LOOKUP,
            )
            foods.extend(call_with_retries(recorder, spec, send).value or [])
        return foods
