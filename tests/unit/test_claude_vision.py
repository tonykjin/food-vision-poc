"""Claude vision adapter against a fake SDK client (no network, no real key).

Responses are SYNTHETIC: they mimic the SDK's response shape so request building, stop-reason
handling, validation, error mapping and telemetry can be tested. They are not model output.
"""

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from pydantic import SecretStr
from tests.conftest import synthetic_image

from foodvision.contracts.errors import ErrorCode
from foodvision.imaging.prepare import prepare_image
from foodvision.measurement.budget import BudgetPolicy
from foodvision.measurement.clock import ManualClock
from foodvision.measurement.events import AttemptOutcome, CostProvenance, ScanStatus
from foodvision.measurement.retry import AttemptError
from foodvision.measurement.spans import ScanRecorder
from foodvision.providers.claude_vision import (
    FALLBACK_BETA,
    ClaudeVisionProvider,
    VisionAttemptError,
    VisionConfig,
)
from foodvision.recognition.hypotheses import OUTPUT_SCHEMA, load_prompt

IMAGE = prepare_image(synthetic_image(size=(800, 600)))
REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")

ITEM = {
    "display_name": "SYNTHETIC grilled item",
    "search_description": "synthetic item",
    "preparation": "grilled",
    "visible_brand": None,
    "portion_grams_low": 120,
    "portion_grams_base": 150,
    "portion_grams_high": 200,
    "portion_assumptions": "SYNTHETIC: standard dinner plate",
    "alternatives": ["SYNTHETIC alternative"],
    "evidence": "SYNTHETIC grill marks",
    "uncertainty": ["SYNTHETIC: depth not visible"],
    "is_composite": False,
}
GOOD = {
    "image_assessment": {"is_food_image": True, "multiple_foods": False, "notes": "SYNTHETIC"},
    "items": [ITEM],
}


def message(
    payload=GOOD,
    stop_reason="end_turn",
    model="claude-opus-5-5",
    fallback=False,
    text=None,
    category=None,
):
    iterations = [SimpleNamespace(type="fallback_message")] if fallback else None
    return SimpleNamespace(
        model=model,
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category=category) if stop_reason == "refusal" else None,
        content=[
            SimpleNamespace(type="text", text=text if text is not None else json.dumps(payload))
        ],
        usage=SimpleNamespace(input_tokens=1000, output_tokens=500, iterations=iterations),
        _request_id="req_SYNTHETIC",
    )


def status_error(cls, status, error_type="error", headers=None):
    response = httpx2.Response(status, headers=headers or {}, request=REQUEST)
    body = {"type": "error", "error": {"type": error_type, "message": "SENTINEL provider text"}}
    return cls("SENTINEL provider text", response=response, body=body)


class FakeClient:
    """Mimics anthropic.Anthropic: with_options(), messages.create(), beta.messages.create()."""

    def __init__(self, outcomes):
        self.outcomes, self.calls, self.options = list(outcomes), [], []
        self.messages = SimpleNamespace(create=self._create("messages"))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create("beta")))

    def with_options(self, **options):
        self.options.append(options)
        return self

    def _create(self, path):
        def create(**params):
            self.calls.append((path, params))
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return create


def provider(outcomes, **config):
    fake = FakeClient(outcomes)
    cfg = VisionConfig(model="claude-opus-5-5", **config)
    return ClaudeVisionProvider(SecretStr("SENTINEL-KEY"), cfg, client=fake), fake


def recorder():
    return ScanRecorder("scan", "B", budget=BudgetPolicy(max_model_calls=2), clock=ManualClock())


def test_request_shape_image_first_schema_effort_and_fallback():
    vision, fake = provider([message()])
    vision.recognize(IMAGE, recorder())
    ((path, params),) = fake.calls
    assert (
        path == "beta" and params["betas"] == [FALLBACK_BETA] and params["fallbacks"] == "default"
    )
    assert params["model"] == "claude-opus-5-5" and params["max_tokens"] == 16000
    assert params["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
    }
    assert "thinking" not in params and "temperature" not in params
    image_block, text_block = params["messages"][0]["content"]
    assert image_block["type"] == "image" and image_block["source"]["media_type"] == "image/jpeg"
    assert text_block["type"] == "text"
    assert params["system"] == load_prompt()[0]
    assert fake.options[-1]["max_retries"] == 0  # attempts are counted by the Measurement Kit


def test_fallback_can_be_disabled():
    vision, fake = provider([message()], refusal_fallback=False)
    vision.recognize(IMAGE, recorder())
    path, params = fake.calls[0]
    assert path == "messages" and "fallbacks" not in params and "betas" not in params


def test_valid_output_is_parsed_and_provenance_recorded():
    vision, _ = provider([message()])
    rec = recorder()
    response = vision.recognize(IMAGE, rec)
    assert response.output.items[0].portion_grams_base == 150
    assert (response.model_requested, response.model_served) == (
        "claude-opus-5-5",
        "claude-opus-5-5",
    )
    assert response.fallback_served is False and response.stop_reason == "end_turn"
    assert len(response.prompt_sha256) == 64 and response.sdk_version == anthropic.__version__
    (attempt,) = rec.attempts
    assert attempt.is_model_call and attempt.usage.input_tokens == 1000
    # 1000 × $4/M + 500 × $20/M = $0.014 (official price table, 2026-10-02)
    assert attempt.cost.amount_usd == pytest.approx(0.014)
    assert attempt.cost.provenance is CostProvenance.PRICE_TABLE_ESTIMATE


def test_fallback_served_answer_is_flagged_and_priced_as_served_model():
    vision, _ = provider([message(model="claude-sonnet-5-5", fallback=True)])
    rec = recorder()
    response = vision.recognize(IMAGE, rec)
    assert response.fallback_served and response.model_served == "claude-sonnet-5-5"
    assert rec.attempts[0].cost.amount_usd == pytest.approx(0.007)  # $2/$10 per M


@pytest.mark.parametrize(
    ("response", "code", "outcome"),
    [
        (message(stop_reason="refusal", category="bio"), ErrorCode.REFUSED, AttemptOutcome.REFUSED),
        (message(stop_reason="max_tokens"), ErrorCode.INVALID_SCHEMA, AttemptOutcome.CLIENT_ERROR),
        (message(text="not json"), ErrorCode.INVALID_SCHEMA, AttemptOutcome.CLIENT_ERROR),
    ],
)
def test_refusal_truncation_and_bad_json_are_typed_billed_and_not_retried(response, code, outcome):
    vision, fake = provider([response, message()])
    rec = recorder()
    with pytest.raises(VisionAttemptError) as info:
        vision.recognize(IMAGE, rec)
    assert info.value.code is code and len(fake.calls) == 1
    (attempt,) = rec.attempts
    assert attempt.outcome is outcome
    assert attempt.cost.amount_usd == pytest.approx(0.014)  # billed even though it failed


@pytest.mark.parametrize(
    "bad",
    [
        {**GOOD, "items": [{**ITEM, "portion_grams_low": 300}]},  # low > base
        {**GOOD, "items": [{**ITEM, "portion_grams_base": -5}]},  # negative grams
        {**GOOD, "items": [{**ITEM, "portion_grams_high": 99999}]},  # implausible
        {**GOOD, "items": [{**ITEM, "preparation": "microwaved"}]},  # unsupported enum
        {**GOOD, "items": [{**ITEM, "confidence": 0.93}]},  # no confidence field allowed
        {**GOOD, "items": [ITEM] * 9},  # more than 8 items
        {**GOOD, "items": [{**ITEM, "alternatives": ["a", "b", "c", "d"]}]},
        {"image_assessment": {**GOOD["image_assessment"], "is_food_image": False}, "items": [ITEM]},
    ],
)
def test_schema_valid_but_implausible_output_is_rejected_server_side(bad):
    vision, _ = provider([message(payload=bad)])
    with pytest.raises(VisionAttemptError) as info:
        vision.recognize(IMAGE, recorder())
    assert info.value.code is ErrorCode.INVALID_SCHEMA


@pytest.mark.parametrize(
    ("error", "outcome", "code", "calls"),
    [
        (anthropic.APITimeoutError(request=REQUEST), AttemptOutcome.TIMEOUT, ErrorCode.TIMEOUT, 2),
        (
            anthropic.APIConnectionError(request=REQUEST),
            AttemptOutcome.TRANSPORT_ERROR,
            ErrorCode.PROVIDER_ERROR,
            2,
        ),
        (
            status_error(anthropic.RateLimitError, 429, "rate_limit_error", {"retry-after": "2"}),
            AttemptOutcome.RATE_LIMITED,
            ErrorCode.QUOTA,
            2,
        ),
        (
            status_error(anthropic.InternalServerError, 529, "overloaded_error"),
            AttemptOutcome.SERVER_ERROR,
            ErrorCode.PROVIDER_ERROR,
            2,
        ),
        (
            status_error(anthropic.AuthenticationError, 401, "authentication_error"),
            AttemptOutcome.AUTH_ERROR,
            ErrorCode.AUTHENTICATION,
            1,
        ),
        (
            status_error(anthropic.APIStatusError, 402, "billing_error"),
            AttemptOutcome.CLIENT_ERROR,
            ErrorCode.QUOTA,
            1,
        ),
        (
            status_error(anthropic.BadRequestError, 400, "invalid_request_error"),
            AttemptOutcome.CLIENT_ERROR,
            ErrorCode.PROVIDER_ERROR,
            1,
        ),
        (
            status_error(anthropic.NotFoundError, 404, "not_found_error"),
            AttemptOutcome.CLIENT_ERROR,
            ErrorCode.PROVIDER_ERROR,
            1,
        ),
    ],
)
def test_sdk_errors_map_to_typed_outcomes(error, outcome, code, calls):
    vision, fake = provider([error, error])
    rec = recorder()
    with pytest.raises(AttemptError) as info:
        vision.recognize(IMAGE, rec)
    assert rec.attempts[0].outcome is outcome and info.value.code is code
    assert len(fake.calls) == calls  # only transient failures get their one retry
    dumped = rec.finish(ScanStatus.FAILED, info.value.code).model_dump_json() + repr(info.value)
    assert "SENTINEL" not in dumped and "SENTINEL" not in getattr(info.value, "detail", "")


def test_model_call_budget_blocks_a_third_call():
    vision, fake = provider([message(), message(), message()])
    rec = ScanRecorder("s", "B", budget=BudgetPolicy(max_model_calls=2), clock=ManualClock())
    vision.recognize(IMAGE, rec)
    vision.recognize(IMAGE, rec)
    from foodvision.measurement.budget import BudgetExceeded

    with pytest.raises(BudgetExceeded):
        vision.recognize(IMAGE, rec)
    assert len(fake.calls) == 2


def test_prompt_hash_ignores_line_endings_and_configuration_id_is_versioned():
    text, digest = load_prompt()
    assert "\r" not in text and "confidence percentages" in text
    vision, _ = provider([])
    assert vision.configuration_id.startswith("B:anthropic:claude-opus-5-5:effort-medium:")
    assert digest[:12] in vision.configuration_id


def test_validation_failure_names_the_field_and_rule_but_no_content():
    long_text = "SENTINEL model text " * 20  # 400 characters
    bad = {**GOOD, "items": [{**ITEM, "evidence": long_text, "uncertainty": ["x"] * 7}]}
    vision, _ = provider([message(payload=bad)])
    with pytest.raises(VisionAttemptError) as info:
        vision.recognize(IMAGE, recorder())
    detail = info.value.detail
    assert "items.0.evidence string_too_long" in detail
    assert "items.0.uncertainty too_long" in detail
    assert "SENTINEL" not in detail  # rejected values never reach errors or telemetry


def test_prompt_states_every_server_side_limit():
    # Structured outputs can't enforce lengths or bounds, so the prompt must state them all.
    from foodvision.recognition import hypotheses as h

    prompt = load_prompt()[0]
    assert h.PROMPT_VERSION == "recognize-food-v2"
    for phrase in (
        f"at most {h.MAX_TEXT_CHARS} characters",
        f"`visible_brand` is at most {h.MAX_BRAND_CHARS} characters",
        f"`image_assessment.notes` is at most {h.MAX_NOTES_CHARS} characters",
        f"`alternatives` has at most {h.MAX_ALTERNATIVES} entries",
        f"`uncertainty` at most {h.MAX_UNCERTAINTY}",
        f"at most {h.MAX_PORTION_G:.0f}, with low ≤ base ≤ high",
        f"At most {h.MAX_ITEMS} items",
    ):
        assert phrase in prompt, phrase
