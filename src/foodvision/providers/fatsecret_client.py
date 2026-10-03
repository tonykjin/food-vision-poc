"""fatsecret Platform API client: OAuth 2.0 client-credentials token and image recognition v2.

Docs checked 2026-10-02:
- https://platform.fatsecret.com/docs/guides/authentication/oauth2
  POST https://oauth.fatsecret.com/connect/token, HTTP Basic (client id/secret),
  form grant_type=client_credentials, scope=image-recognition; JSON {access_token,
  token_type, expires_in (86400)}. Tokens only from registered IP addresses.
- https://platform.fatsecret.com/docs/v2/image.recognition
  POST https://platform.fatsecret.com/rest/image-recognition/v2, Authorization: Bearer,
  JSON body (built and size-checked by fatsecret_limits).
- https://platform.fatsecret.com/docs/guides/error-codes
  Errors are JSON {"error": {"code", "message"}}; they may arrive with HTTP 200.

Credentials live only in memory (SecretStr) and are never logged. Provider error messages
are dropped; only numeric codes are kept. Every attempt is recorded by the Measurement Kit.
"""

import base64
import json
import threading
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import SecretStr

from foodvision.contracts.errors import ErrorCode
from foodvision.measurement.events import AttemptOutcome, CacheState, Stage
from foodvision.measurement.retry import AttemptError, CallResult, CallSpec, call_with_retries
from foodvision.measurement.spans import ScanRecorder

TOKEN_URL = "https://oauth.fatsecret.com/connect/token"
IMAGE_URL = "https://platform.fatsecret.com/rest/image-recognition/v2"
SCOPE = "image-recognition"
TOKEN_SAFETY_MARGIN_S = 300.0  # refresh 5 minutes before expiry
NO_FOOD_DETECTED = 211

# fatsecret error code -> (attempt outcome, our error code). Unlisted codes: client error.
_PROVIDER_CODES: dict[int, tuple[AttemptOutcome, ErrorCode]] = {
    1: (AttemptOutcome.CLIENT_ERROR, ErrorCode.PROVIDER_ERROR),  # unknown: don't re-bill
    11: (AttemptOutcome.CLIENT_ERROR, ErrorCode.QUOTA),  # application request limit
    12: (AttemptOutcome.RATE_LIMITED, ErrorCode.QUOTA),  # too many actions: transient
    13: (AttemptOutcome.AUTH_ERROR, ErrorCode.AUTHENTICATION),  # invalid token
    14: (AttemptOutcome.AUTH_ERROR, ErrorCode.AUTHENTICATION),  # missing scope
    20: (AttemptOutcome.SERVER_ERROR, ErrorCode.PROVIDER_ERROR),  # temporarily unavailable
    21: (AttemptOutcome.AUTH_ERROR, ErrorCode.AUTHENTICATION),  # invalid IP address
    24: (AttemptOutcome.TIMEOUT, ErrorCode.TIMEOUT),
}


class FatsecretAttemptError(AttemptError):
    """AttemptError carrying the fatsecret numeric code (never the message text)."""

    def __init__(
        self,
        outcome: AttemptOutcome,
        *,
        code: ErrorCode | None = None,
        provider_code: int | None = None,
        http_status: int | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        super().__init__(outcome, http_status=http_status, retry_after_s=retry_after_s)
        self.provider_code = provider_code
        if code is not None:
            self.code = code


def _from_http(status: int, headers: httpx.Headers) -> FatsecretAttemptError | None:
    if status < 400:
        return None
    if status == 429:
        after = headers.get("Retry-After")
        return FatsecretAttemptError(
            AttemptOutcome.RATE_LIMITED,
            http_status=status,
            retry_after_s=float(after) if after and after.isdigit() else None,
        )
    if status in (401, 403):
        return FatsecretAttemptError(AttemptOutcome.AUTH_ERROR, http_status=status)
    if status >= 500:
        return FatsecretAttemptError(AttemptOutcome.SERVER_ERROR, http_status=status)
    return FatsecretAttemptError(AttemptOutcome.CLIENT_ERROR, http_status=status)


def _from_body(payload: Any, status: int) -> FatsecretAttemptError | None:
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return None
    try:
        provider_code = int(error.get("code"))
    except (TypeError, ValueError):
        provider_code = None
    if provider_code == NO_FOOD_DETECTED:
        return None  # a valid answer ("no food item detected"), handled by the pipeline
    outcome, code = _PROVIDER_CODES.get(
        provider_code, (AttemptOutcome.CLIENT_ERROR, ErrorCode.PROVIDER_ERROR)
    )
    return FatsecretAttemptError(
        outcome, code=code, provider_code=provider_code, http_status=status
    )


def _json_or_none(response: httpx.Response) -> Any:
    try:
        return response.json()
    except (json.JSONDecodeError, ValueError):
        return None


def _invalid_schema(status: int) -> FatsecretAttemptError:
    return FatsecretAttemptError(
        AttemptOutcome.CLIENT_ERROR, code=ErrorCode.INVALID_SCHEMA, http_status=status
    )


@dataclass
class _Token:
    value: str
    expires_at_ns: int


class FatsecretClient:
    def __init__(
        self,
        client_id: SecretStr,
        client_secret: SecretStr,
        *,
        http: httpx.Client | None = None,
        request_timeout_s: float = 20.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http or httpx.Client()
        self._timeout_s = request_timeout_s
        self._token: _Token | None = None
        self._lock = threading.Lock()

    def _fetch_token(self, recorder: ScanRecorder) -> _Token:
        basic = base64.b64encode(
            f"{self._client_id.get_secret_value()}:{self._client_secret.get_secret_value()}".encode()
        ).decode()

        def send(timeout_s: float) -> CallResult:
            try:
                response = self._http.post(
                    TOKEN_URL,
                    headers={"Authorization": f"Basic {basic}"},
                    data={"grant_type": "client_credentials", "scope": SCOPE},
                    timeout=timeout_s,
                )
            except httpx.TimeoutException:
                raise TimeoutError from None
            except httpx.TransportError:
                raise FatsecretAttemptError(AttemptOutcome.TRANSPORT_ERROR) from None
            failure = _from_http(response.status_code, response.headers)
            if failure is not None:
                raise failure
            payload = _json_or_none(response)
            if not isinstance(payload, dict):
                raise _invalid_schema(response.status_code)
            token, lifetime = payload.get("access_token"), payload.get("expires_in")
            if not isinstance(token, str) or not isinstance(lifetime, (int, float)):
                raise _invalid_schema(response.status_code)
            return CallResult(value=(token, float(lifetime)), http_status=response.status_code)

        spec = CallSpec("fatsecret", "oauth.token", False, self._timeout_s, Stage.AUTH)
        token, lifetime = call_with_retries(recorder, spec, send).value
        expires_at = recorder.clock.monotonic_ns() + int(
            max(0.0, lifetime - TOKEN_SAFETY_MARGIN_S) * 1e9
        )
        return _Token(token, expires_at)

    def token(self, recorder: ScanRecorder) -> str:
        """A usable token, reused until 5 minutes before expiry."""
        with self._lock:
            now = recorder.clock.monotonic_ns()
            if self._token is not None and now < self._token.expires_at_ns:
                with recorder.span(Stage.AUTH, cache_state=CacheState.HIT):
                    return self._token.value
            self._token = self._fetch_token(recorder)
            return self._token.value

    def invalidate_token(self) -> None:
        with self._lock:
            self._token = None

    def _recognize_once(self, body: bytes, recorder: ScanRecorder) -> Any:
        token = self.token(recorder)

        def send(timeout_s: float) -> CallResult:
            try:
                response = self._http.post(
                    IMAGE_URL,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    content=body,
                    timeout=timeout_s,
                )
            except httpx.TimeoutException:
                raise TimeoutError from None
            except httpx.TransportError:
                raise FatsecretAttemptError(AttemptOutcome.TRANSPORT_ERROR) from None
            payload = _json_or_none(response)
            failure = _from_body(payload, response.status_code) or _from_http(
                response.status_code, response.headers
            )
            if failure is not None:
                raise failure
            if not isinstance(payload, dict):
                raise _invalid_schema(response.status_code)
            return CallResult(value=payload, http_status=response.status_code)

        spec = CallSpec(
            "fatsecret", "image-recognition.v2", False, self._timeout_s, Stage.RECOGNITION
        )
        return call_with_retries(recorder, spec, send).value

    def recognize(self, body: bytes, recorder: ScanRecorder) -> Any:
        """POST an already size-checked JSON body. One token refresh on 'invalid token' (13)."""
        try:
            return self._recognize_once(body, recorder)
        except FatsecretAttemptError as exc:
            if exc.provider_code != 13:
                raise
            self.invalidate_token()
            return self._recognize_once(body, recorder)
