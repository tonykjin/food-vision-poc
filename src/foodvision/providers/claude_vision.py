"""Claude vision adapter (App B, POC-09) using the official Anthropic Python SDK.

Docs checked 2026-10-02:
- https://platform.claude.com/docs/en/build-with-claude/vision (base64 image blocks, image first)
- https://platform.claude.com/docs/en/build-with-claude/structured-outputs (`output_config.format`)
- https://platform.claude.com/docs/en/about-claude/models/overview (model IDs, pricing)

Request: one image + versioned prompt, JSON-schema structured output, adaptive thinking (always
on for current models; effort set explicitly), SDK retries disabled so every attempt is counted
by the Measurement Kit. Optional server-side refusal fallback (`fallbacks: "default"`); when a
fallback model serves the answer it is recorded, because it changes the measured system.
The response is checked in order: stop_reason (refusal, max_tokens), then JSON, then
server-side validation. No result is fabricated on any failure.
"""

import base64
import json
from dataclasses import dataclass
from typing import Any

import anthropic
from pydantic import SecretStr, ValidationError

from foodvision.contracts.errors import ErrorCode
from foodvision.imaging.prepare import PreparedImage
from foodvision.measurement.costs import Price, PriceTable
from foodvision.measurement.events import AttemptOutcome, ProviderUsage, Stage
from foodvision.measurement.retry import AttemptError, CallResult, CallSpec, call_with_retries
from foodvision.measurement.spans import ScanRecorder
from foodvision.recognition.hypotheses import (
    OUTPUT_SCHEMA,
    PROMPT_VERSION,
    RecognitionOutput,
    load_prompt,
)

PROVIDER = "anthropic"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# USD per million tokens, from the official models overview fetched 2026-10-02.
PRICES = PriceTable(
    version="claude-models-overview-2026-10-02",
    source_url="https://platform.claude.com/docs/en/about-claude/models/overview",
    prices={
        "anthropic/claude-opus-5-5": Price(input_usd_per_mtok=4.0, output_usd_per_mtok=20.0),
        "anthropic/claude-sonnet-5-5": Price(input_usd_per_mtok=2.0, output_usd_per_mtok=10.0),
        "anthropic/claude-haiku-4-5-20251001": Price(
            input_usd_per_mtok=1.0, output_usd_per_mtok=5.0
        ),
        "anthropic/claude-haiku-4-5": Price(input_usd_per_mtok=1.0, output_usd_per_mtok=5.0),
        "anthropic/claude-fable-5-1": Price(input_usd_per_mtok=10.0, output_usd_per_mtok=50.0),
    },
)


class VisionAttemptError(AttemptError):
    def __init__(
        self,
        outcome: AttemptOutcome,
        *,
        code: ErrorCode | None = None,
        detail: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(outcome, **kwargs)
        if code is not None:
            self.code = code
        self.detail = detail  # our own words; never provider message text


@dataclass(frozen=True)
class VisionConfig:
    model: str
    effort: str = "medium"
    max_tokens: int = 16000
    refusal_fallback: bool = True
    request_timeout_s: float = 60.0


@dataclass(frozen=True)
class RecognitionResponse:
    output: RecognitionOutput
    provider: str
    model_requested: str
    model_served: str
    fallback_served: bool
    stop_reason: str
    prompt_version: str
    prompt_sha256: str
    sdk_version: str
    effort: str
    request_id: str | None


def _usage(response: Any) -> ProviderUsage | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    # No prompt caching is used, so input_tokens is the whole billed input.
    return ProviderUsage(
        input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, images=1
    )


def _fallback_served(response: Any) -> bool:
    iterations = getattr(getattr(response, "usage", None), "iterations", None) or []
    return any(getattr(i, "type", None) == "fallback_message" for i in iterations)


def _status_error(exc: anthropic.APIStatusError) -> VisionAttemptError:
    status = exc.status_code
    if isinstance(exc, anthropic.RateLimitError):
        after = exc.response.headers.get("retry-after")
        return VisionAttemptError(
            AttemptOutcome.RATE_LIMITED,
            http_status=status,
            retry_after_s=float(after) if after and after.replace(".", "", 1).isdigit() else None,
            detail="rate limited",
        )
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return VisionAttemptError(
            AttemptOutcome.AUTH_ERROR, http_status=status, detail=f"authentication ({exc.type})"
        )
    if exc.type == "billing_error":
        return VisionAttemptError(
            AttemptOutcome.CLIENT_ERROR,
            code=ErrorCode.QUOTA,
            http_status=status,
            detail="billing / credit balance",
        )
    if status >= 500:
        return VisionAttemptError(
            AttemptOutcome.SERVER_ERROR, http_status=status, detail=f"server error ({exc.type})"
        )
    return VisionAttemptError(
        AttemptOutcome.CLIENT_ERROR,
        code=ErrorCode.PROVIDER_ERROR,
        http_status=status,
        detail=f"request rejected ({exc.type})",
    )


class ClaudeVisionProvider:
    provider = PROVIDER

    def __init__(
        self, api_key: SecretStr, config: VisionConfig, client: anthropic.Anthropic | None = None
    ) -> None:
        self.config = config
        self.prompt, self.prompt_sha256 = load_prompt(PROMPT_VERSION)
        self._client = client or anthropic.Anthropic(
            api_key=api_key.get_secret_value(), max_retries=0
        )

    @property
    def configuration_id(self) -> str:
        fallback = "fallback" if self.config.refusal_fallback else "nofallback"
        return (
            f"B:{PROVIDER}:{self.config.model}:effort-{self.config.effort}:"
            f"{PROMPT_VERSION}@{self.prompt_sha256[:12]}:{fallback}"
        )

    def _request(self, image: PreparedImage, timeout_s: float) -> Any:
        params: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "system": self.prompt,
            "output_config": {
                "effort": self.config.effort,
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            },
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {  # image before text, per the vision guide
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": image.media_type,
                                "data": base64.standard_b64encode(image.data).decode("ascii"),
                            },
                        },
                        {"type": "text", "text": "Identify the visible foods."},
                    ],
                }
            ],
        }
        client = self._client.with_options(timeout=timeout_s, max_retries=0)
        if self.config.refusal_fallback:
            return client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
        return client.messages.create(**params)

    def recognize(self, image: PreparedImage, recorder: ScanRecorder) -> RecognitionResponse:
        def send(timeout_s: float) -> CallResult:
            try:
                response = self._request(image, timeout_s)
            except anthropic.APITimeoutError:
                raise TimeoutError from None
            except anthropic.APIConnectionError:
                raise VisionAttemptError(
                    AttemptOutcome.TRANSPORT_ERROR, detail="connection error"
                ) from None
            except anthropic.APIStatusError as exc:
                raise _status_error(exc) from None

            usage, served = _usage(response), getattr(response, "model", None)
            billed = {"usage": usage, "provider_model": served}
            if response.stop_reason == "refusal":
                category = getattr(getattr(response, "stop_details", None), "category", None)
                raise VisionAttemptError(
                    AttemptOutcome.REFUSED, detail=f"refused (category: {category})", **billed
                )
            if response.stop_reason == "max_tokens":
                raise VisionAttemptError(
                    AttemptOutcome.CLIENT_ERROR,
                    code=ErrorCode.INVALID_SCHEMA,
                    detail="output truncated at max_tokens",
                    **billed,
                )
            text = next((b.text for b in response.content if b.type == "text"), None)
            try:
                output = RecognitionOutput.model_validate(json.loads(text or ""))
            except (json.JSONDecodeError, ValidationError) as exc:
                kind = "not JSON" if isinstance(exc, json.JSONDecodeError) else "failed validation"
                raise VisionAttemptError(
                    AttemptOutcome.CLIENT_ERROR,
                    code=ErrorCode.INVALID_SCHEMA,
                    detail=f"model output {kind}",
                    **billed,
                ) from None
            return CallResult(
                value=(output, response), http_status=200, usage=usage, provider_model=served
            )

        spec = CallSpec(
            provider=PROVIDER,
            operation="messages.vision",
            is_model_call=True,
            request_timeout_s=self.config.request_timeout_s,
            stage=Stage.RECOGNITION,
            model=self.config.model,
        )
        output, response = call_with_retries(recorder, spec, send, prices=PRICES).value
        return RecognitionResponse(
            output=output,
            provider=PROVIDER,
            model_requested=self.config.model,
            model_served=getattr(response, "model", self.config.model),
            fallback_served=_fallback_served(response),
            stop_reason=response.stop_reason,
            prompt_version=PROMPT_VERSION,
            prompt_sha256=self.prompt_sha256,
            sdk_version=anthropic.__version__,
            effort=self.config.effort,
            request_id=getattr(response, "_request_id", None),
        )
