"""OpenAI vision adapter against a fake SDK client (POC-14). No network, no real key.

Responses are SYNTHETIC: they mimic the Responses API shape documented on 2026-10-07 so
request building, refusal/truncation handling, validation, errors and costs can be tested.
"""

import json
from types import SimpleNamespace

import httpx2
import openai
import pytest
from pydantic import SecretStr
from tests.unit.test_claude_vision import GOOD, IMAGE, ITEM, recorder

from foodvision.cli.benchmark_run import split_config
from foodvision.config import AgentSettings
from foodvision.contracts.errors import ErrorCode
from foodvision.contracts.requests import AnalysisContext
from foodvision.measurement.events import AttemptOutcome
from foodvision.pipelines.agent_direct import DirectPipeline
from foodvision.providers.claude_vision import VisionAttemptError, VisionConfig
from foodvision.providers.openai_vision import (
    OpenAIVisionProvider,
    priced_model,
    strict_schema,
)
from foodvision.providers.registry import build_vision_provider, model_for
from foodvision.recognition.direct import DIRECT_SCHEMA
from foodvision.recognition.hypotheses import OUTPUT_SCHEMA, load_prompt

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/responses")


def response(
    payload=GOOD, status="completed", model="gpt-6-astra", refusal=False, reason=None, text=None
):
    part = (
        SimpleNamespace(type="refusal", refusal="SENTINEL refusal text")
        if refusal
        else SimpleNamespace(type="output_text", text="x")
    )
    return SimpleNamespace(
        model=model,
        status=status,
        incomplete_details=SimpleNamespace(reason=reason) if reason else None,
        output=[SimpleNamespace(type="message", content=[part])],
        output_text=text if text is not None else json.dumps(payload),
        usage=SimpleNamespace(input_tokens=1000, output_tokens=500),
        _request_id="req_SYNTHETIC",
    )


def status_error(cls, status, code=None, headers=None):
    raw = httpx2.Response(status, headers=headers or {}, request=REQUEST)
    return cls(
        "SENTINEL provider text",
        response=raw,
        body={"code": code, "message": "SENTINEL provider text"},
    )


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes, self.calls, self.options = list(outcomes), [], []
        self.responses = SimpleNamespace(create=self._create)

    def with_options(self, **options):
        self.options.append(options)
        return self

    def _create(self, **params):
        self.calls.append(params)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def provider(outcomes, **config):
    fake = FakeClient(outcomes)
    cfg = VisionConfig(model="gpt-6-astra", **config)
    return OpenAIVisionProvider(SecretStr("SENTINEL-KEY"), cfg, client=fake), fake


def test_strict_schema_turns_nullable_anyof_into_type_arrays():
    converted = json.dumps(strict_schema(DIRECT_SCHEMA))
    assert "anyOf" not in converted
    brand = strict_schema(OUTPUT_SCHEMA)["properties"]["items"]["items"]["properties"]
    assert brand["visible_brand"] == {"type": ["string", "null"]}
    with pytest.raises(ValueError, match="nullable anyOf"):
        strict_schema({"anyOf": [{"type": "string"}, {"type": "number"}]})


def test_request_shape_image_schema_effort_and_no_tools():
    vision, fake = provider([response()])
    vision.recognize(IMAGE, recorder())
    (params,) = fake.calls
    assert params["model"] == "gpt-6-astra" and params["max_output_tokens"] == 16000
    assert params["instructions"] == load_prompt()[0]  # same prompt as the Claude adapter
    assert params["reasoning"] == {"effort": "medium"}
    fmt = params["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True
    assert fmt["schema"] == strict_schema(OUTPUT_SCHEMA)
    image, text = params["input"][0]["content"]
    assert image["type"] == "input_image" and image["detail"] == "original"
    assert image["image_url"].startswith("data:image/jpeg;base64,")
    assert text["type"] == "input_text"
    assert "tools" not in params and fake.options[-1]["max_retries"] == 0


def test_valid_output_parsed_with_provenance_and_cost():
    vision, _ = provider([response()])
    rec = recorder()
    result = vision.recognize(IMAGE, rec)
    assert result.output.items[0].portion_grams_base == 150
    assert (result.provider, result.model_served, result.fallback_served) == (
        "openai",
        "gpt-6-astra",
        False,
    )
    assert result.sdk_version == openai.__version__
    # 1000 x $10/M + 500 x $50/M (official pricing page, 2026-10-07)
    assert rec.attempts[0].cost.amount_usd == pytest.approx(0.035)


def test_dated_snapshot_is_priced_as_its_base_model():
    assert priced_model("gpt-6-astra-2026-09-01") == "gpt-6-astra"
    assert priced_model("gpt-6-astra") == "gpt-6-astra"
    assert priced_model("unknown-model") == "unknown-model"
    vision, _ = provider([response(model="gpt-6-astra-2026-09-01")])
    rec = recorder()
    result = vision.recognize(IMAGE, rec)
    assert result.model_served == "gpt-6-astra-2026-09-01"  # provenance keeps the real ID
    assert rec.attempts[0].cost.amount_usd == pytest.approx(0.035)


@pytest.mark.parametrize(
    ("outcome", "code", "attempt_outcome"),
    [
        (response(refusal=True), ErrorCode.REFUSED, AttemptOutcome.REFUSED),
        (
            response(status="incomplete", reason="max_output_tokens"),
            ErrorCode.INVALID_SCHEMA,
            AttemptOutcome.CLIENT_ERROR,
        ),
        (response(text="not json"), ErrorCode.INVALID_SCHEMA, AttemptOutcome.CLIENT_ERROR),
    ],
)
def test_refusal_truncation_and_bad_json_are_typed_billed_and_not_retried(
    outcome, code, attempt_outcome
):
    vision, fake = provider([outcome, response()])
    rec = recorder()
    with pytest.raises(VisionAttemptError) as info:
        vision.recognize(IMAGE, rec)
    assert info.value.code is code and len(fake.calls) == 1
    assert rec.attempts[0].outcome is attempt_outcome
    assert rec.attempts[0].cost.amount_usd == pytest.approx(0.035)  # billed even on failure
    assert "SENTINEL" not in info.value.detail


def test_server_side_validation_names_the_field():
    bad = {**GOOD, "items": [{**ITEM, "portion_grams_low": 300}]}
    vision, _ = provider([response(payload=bad)])
    with pytest.raises(VisionAttemptError) as info:
        vision.recognize(IMAGE, recorder())
    assert info.value.code is ErrorCode.INVALID_SCHEMA
    assert "items.0" in info.value.detail


@pytest.mark.parametrize(
    ("error", "outcome", "code", "calls"),
    [
        (
            status_error(openai.RateLimitError, 429, "insufficient_quota"),
            AttemptOutcome.CLIENT_ERROR,
            ErrorCode.QUOTA,
            1,
        ),  # billing: never retried
        (
            status_error(openai.RateLimitError, 429, "rate_limit_exceeded"),
            AttemptOutcome.RATE_LIMITED,
            ErrorCode.QUOTA,
            2,
        ),
        (
            status_error(openai.AuthenticationError, 401, "invalid_api_key"),
            AttemptOutcome.AUTH_ERROR,
            ErrorCode.AUTHENTICATION,
            1,
        ),
        (
            status_error(openai.InternalServerError, 500),
            AttemptOutcome.SERVER_ERROR,
            ErrorCode.PROVIDER_ERROR,
            2,
        ),
        (openai.APITimeoutError(request=REQUEST), AttemptOutcome.TIMEOUT, ErrorCode.TIMEOUT, 2),
    ],
)
def test_sdk_errors_map_to_typed_outcomes(error, outcome, code, calls):
    vision, fake = provider([error, error])
    rec = recorder()
    with pytest.raises(Exception) as info:
        vision.recognize(IMAGE, rec)
    assert rec.attempts[0].outcome is outcome
    assert getattr(info.value, "code", None) is code
    assert len(fake.calls) == calls
    assert "SENTINEL" not in json.dumps([a.model_dump(mode="json") for a in rec.attempts])


def test_no_fallback_exists_and_configuration_id_names_provider_model_and_detail():
    vision, _ = provider([], refusal_fallback=True)
    assert vision.config.refusal_fallback is False
    assert vision.configuration_id.startswith("B:openai:gpt-6-astra:effort-medium:")
    assert vision.configuration_id.endswith(":detail-original:nofallback")


def test_b_direct_runs_on_openai_with_the_same_contract():
    payload = {
        **GOOD,
        "items": [
            {
                **ITEM,
                "estimated_nutrients": {
                    "energy_kcal": 250.0,
                    "protein_g": 30.0,
                    "carbohydrate_g": 0.0,
                    "fat_g": None,
                },
            }
        ],
    }
    vision, fake = provider([response(payload=payload)])
    context = AnalysisContext(
        scan_id="s",
        original_sha256=IMAGE.original_sha256,
        processed_sha256=IMAGE.processed_sha256,
        preprocessing_version=IMAGE.transform_version,
        pipeline_id="B_direct",
    )
    result = DirectPipeline(vision).analyze(IMAGE, context, recorder())
    assert result.status == "partial" and result.totals.nutrients.fat_g is None
    assert result.configuration_id.startswith("B_direct:openai:gpt-6-astra:")
    assert fake.calls[0]["text"]["format"]["schema"] == strict_schema(DIRECT_SCHEMA)


def test_registry_selects_provider_and_reports_missing_key():
    base = dict(_env_file=None, anthropic_api_key=SecretStr("SENTINEL"))
    openai_settings = AgentSettings(**base, vision_provider="openai")
    assert model_for(openai_settings) == "gpt-6-astra"
    provider_, reason = build_vision_provider(openai_settings)
    assert provider_ is None and "OPENAI_API_KEY" in reason  # never falls back to Claude
    with_key = AgentSettings(**base, vision_provider="openai", openai_api_key=SecretStr("K"))
    assert isinstance(build_vision_provider(with_key)[0], OpenAIVisionProvider)
    claude = build_vision_provider(AgentSettings(**base))[0]
    assert claude.provider == "anthropic" and claude.config.model == "claude-opus-5-5"


def test_deepseek_is_not_a_selectable_provider():
    with pytest.raises(ValueError):
        AgentSettings(_env_file=None, vision_provider="deepseek")


def test_benchmark_config_labels_carry_provider_and_model():
    assert split_config("B_grounded@openai:gpt-6.1-sol") == ("B_grounded", "openai", "gpt-6.1-sol")
    assert split_config("B_direct@openai") == ("B_direct", "openai", None)
    assert split_config("A_native") == ("A_native", None, None)
