"""fatsecret client against a fake HTTP layer (httpx.MockTransport). No network, no real keys."""

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from foodvision.contracts.errors import ErrorCode
from foodvision.measurement.budget import BudgetPolicy
from foodvision.measurement.clock import ManualClock
from foodvision.measurement.events import AttemptOutcome, CacheState, ScanStatus, Stage
from foodvision.measurement.spans import ScanRecorder
from foodvision.providers.fatsecret_client import (
    IMAGE_URL,
    TOKEN_URL,
    FatsecretAttemptError,
    FatsecretClient,
)

ID, SECRET = "SENTINEL-CLIENT-ID", "SENTINEL-CLIENT-SECRET"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "fatsecret"
OK_BODY = json.loads((FIXTURES / "two_items.json").read_text(encoding="utf-8"))


def token_response(n=1, lifetime=86400):
    return httpx.Response(
        200,
        json={
            "access_token": f"SENTINEL-TOKEN-{n}",
            "token_type": "Bearer",
            "expires_in": lifetime,
        },
    )


def provider_error(code, message="SENTINEL provider detail"):
    return httpx.Response(200, json={"error": {"code": str(code), "message": message}})


class FakeFatsecret:
    def __init__(self, images, tokens=None):
        self.images, self.tokens = list(images), list(tokens or [token_response(1)])
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        queue = self.tokens if str(request.url) == TOKEN_URL else self.images
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def calls(self, url):
        return [r for r in self.requests if str(r.url) == url]


def make(images, tokens=None, clock=None):
    fake = FakeFatsecret(images, tokens)
    client = FatsecretClient(
        SecretStr(ID), SecretStr(SECRET), http=httpx.Client(transport=httpx.MockTransport(fake))
    )
    return client, fake, clock or ManualClock()


def recorder(clock):
    return ScanRecorder("scan", "A_native", budget=BudgetPolicy(max_model_calls=0), clock=clock)


def test_token_request_shape_and_image_request_shape():
    client, fake, clock = make([httpx.Response(200, json=OK_BODY)])
    assert client.recognize(b'{"image_b64":"x"}', recorder(clock)) == OK_BODY
    (token_req,) = fake.calls(TOKEN_URL)
    assert token_req.headers["Authorization"].startswith("Basic ")
    form = parse_qs(token_req.content.decode())
    assert form == {"grant_type": ["client_credentials"], "scope": ["image-recognition"]}
    (image_req,) = fake.calls(IMAGE_URL)
    assert image_req.headers["Authorization"] == "Bearer SENTINEL-TOKEN-1"
    assert image_req.headers["Content-Type"] == "application/json"


def test_token_is_reused_until_safety_margin_then_refreshed():
    ok = httpx.Response(200, json=OK_BODY)
    client, fake, clock = make([ok, ok, ok], tokens=[token_response(1), token_response(2)])
    client.recognize(b"{}", first := recorder(clock))
    client.recognize(b"{}", second := recorder(clock))
    assert len(fake.calls(TOKEN_URL)) == 1
    auth_span = next(s for s in second.spans if s.stage is Stage.AUTH)
    assert auth_span.cache_state is CacheState.HIT
    assert [a.operation for a in second.attempts] == ["image-recognition.v2"]
    clock.advance(86400 - 300)  # reaches the 5-minute safety margin
    client.recognize(b"{}", recorder(clock))
    assert len(fake.calls(TOKEN_URL)) == 2
    assert [a.operation for a in first.attempts] == ["oauth.token", "image-recognition.v2"]


def test_invalid_token_refreshes_once_and_resends():
    client, fake, clock = make(
        [provider_error(13), httpx.Response(200, json=OK_BODY)],
        tokens=[token_response(1), token_response(2)],
    )
    assert client.recognize(b"{}", recorder(clock)) == OK_BODY
    assert len(fake.calls(TOKEN_URL)) == 2
    assert fake.calls(IMAGE_URL)[-1].headers["Authorization"] == "Bearer SENTINEL-TOKEN-2"


@pytest.mark.parametrize(
    ("code", "error_code", "attempts"),
    [
        (14, ErrorCode.AUTHENTICATION, 1),  # missing scope
        (21, ErrorCode.AUTHENTICATION, 1),  # invalid IP address
        (11, ErrorCode.QUOTA, 1),  # application request limit: not retried
        (22, ErrorCode.PROVIDER_ERROR, 1),  # invalid request
        (12, ErrorCode.QUOTA, 2),  # too many actions: one transient retry
        (20, ErrorCode.PROVIDER_ERROR, 2),  # temporarily unavailable: one retry
    ],
)
def test_provider_error_codes_are_typed(code, error_code, attempts):
    client, fake, clock = make([provider_error(code), provider_error(code)])
    rec = recorder(clock)
    with pytest.raises(FatsecretAttemptError) as info:
        client.recognize(b"{}", rec)
    assert info.value.code is error_code and info.value.provider_code == code
    assert len(fake.calls(IMAGE_URL)) == attempts


def test_label_only_211_is_returned_as_an_answer_not_raised():
    body = {"error": {"code": "211", "message": "No food item detected"}}
    client, _, clock = make([httpx.Response(200, json=body)])
    assert client.recognize(b"{}", recorder(clock)) == body


@pytest.mark.parametrize(
    ("responses", "outcomes"),
    [
        (
            [httpx.Response(503), httpx.Response(200, json=OK_BODY)],
            [AttemptOutcome.SERVER_ERROR, AttemptOutcome.SUCCESS],
        ),
        (
            [httpx.ConnectError("x"), httpx.Response(200, json=OK_BODY)],
            [AttemptOutcome.TRANSPORT_ERROR, AttemptOutcome.SUCCESS],
        ),
        (
            [httpx.ReadTimeout("x"), httpx.Response(200, json=OK_BODY)],
            [AttemptOutcome.TIMEOUT, AttemptOutcome.SUCCESS],
        ),
        (
            [httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200, json=OK_BODY)],
            [AttemptOutcome.RATE_LIMITED, AttemptOutcome.SUCCESS],
        ),
    ],
)
def test_transient_failures_retry_once_and_are_recorded(responses, outcomes):
    client, _, clock = make(responses)
    rec = recorder(clock)
    client.recognize(b"{}", rec)
    image_attempts = [a for a in rec.attempts if a.operation == "image-recognition.v2"]
    assert [a.outcome for a in image_attempts] == outcomes


def test_non_json_success_is_invalid_schema():
    client, _, clock = make([httpx.Response(200, text="<html>")])
    with pytest.raises(FatsecretAttemptError) as info:
        client.recognize(b"{}", recorder(clock))
    assert info.value.code is ErrorCode.INVALID_SCHEMA


@pytest.mark.parametrize(
    ("response", "oauth_error"),
    [
        (httpx.Response(400, json={"error": "invalid_client"}), "invalid_client"),
        (httpx.Response(400, json={"error": "invalid_scope"}), "invalid_scope"),
        (httpx.Response(401, json={"error": "SENTINEL free text"}), None),  # not in RFC set
        (httpx.Response(403, text="<html>SENTINEL</html>"), None),
    ],
)
def test_token_endpoint_rejection_is_authentication_with_standard_code(response, oauth_error):
    client, fake, clock = make([], tokens=[response])
    rec = recorder(clock)
    with pytest.raises(FatsecretAttemptError) as info:
        client.recognize(b"{}", rec)
    assert info.value.outcome is AttemptOutcome.AUTH_ERROR
    assert info.value.code is ErrorCode.AUTHENTICATION
    assert info.value.oauth_error == oauth_error
    assert "SENTINEL" not in info.value.detail()
    assert fake.calls(IMAGE_URL) == [] and len(rec.attempts) == 1  # auth is never retried


def test_secrets_tokens_and_provider_text_never_reach_records_or_errors():
    client, _, clock = make([provider_error(21)])
    rec = recorder(clock)
    with pytest.raises(FatsecretAttemptError) as info:
        client.recognize(b"{}", rec)
    dumped = rec.finish(ScanStatus.FAILED, info.value.code).model_dump_json() + repr(info.value)
    for secret in (ID, SECRET, "SENTINEL-TOKEN", "SENTINEL provider detail"):
        assert secret not in dumped
