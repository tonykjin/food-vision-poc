"""OpenAI vision adapter (POC-14): Responses API, image input, strict JSON-schema output.

Docs checked 2026-10-07 (developers.openai.com: images-vision, structured-outputs, reasoning,
models, pricing). Same public methods as `ClaudeVisionProvider`, so every B pipeline runs on
either provider with the same prompts, schemas, image bytes, budgets and server-side checks.
Differences, recorded in the configuration ID or provenance:
- Strict structured outputs don't support `anyOf`; nullable fields become type arrays. They do
  enforce lengths and bounds, but our own validation still runs on every response.
- No server-side refusal fallback exists; a refusal (a `refusal` content item) is final.
- `reasoning.effort` matches the Claude config's effort; `max_output_tokens` includes
  reasoning tokens, and hitting it (`status: incomplete`) is a typed truncation failure.
- Model IDs like `gpt-6-astra` are aliases, not pinned snapshots: rerun a control set before
  comparing runs far apart in time.
"""

import base64
import copy
import dataclasses
import json
from collections.abc import Callable
from typing import Any

import openai
from pydantic import SecretStr, ValidationError

from foodvision.contracts.errors import ErrorCode
from foodvision.imaging.prepare import PreparedImage
from foodvision.measurement.costs import Price, PriceTable
from foodvision.measurement.events import AttemptOutcome, ProviderUsage, Stage
from foodvision.measurement.retry import CallResult, CallSpec, call_with_retries
from foodvision.measurement.spans import ScanRecorder
from foodvision.providers.claude_vision import (
    RecognitionResponse,
    VisionAttemptError,
    VisionConfig,
    validation_summary,
)
from foodvision.recognition.direct import DIRECT_PROMPT_VERSION, DIRECT_SCHEMA, DirectOutput
from foodvision.recognition.hypotheses import (
    OUTPUT_SCHEMA,
    PROMPT_VERSION,
    RecognitionOutput,
    load_prompt,
)

PROVIDER = "openai"
DEFAULT_MODEL = "gpt-6-astra"  # models page 2026-10-07: flagship, recommended for new projects
IMAGE_DETAIL = "original"  # send the baseline-prepared image as is (no provider resizing)

PRICES = PriceTable(
    version="openai-pricing-2026-10-07",
    source_url="https://developers.openai.com/api/docs/pricing",
    prices={
        "openai/gpt-6-astra": Price(input_usd_per_mtok=10.0, output_usd_per_mtok=50.0),
        "openai/gpt-6.1-sol": Price(input_usd_per_mtok=2.0, output_usd_per_mtok=10.0),
        "openai/gpt-6-luna": Price(input_usd_per_mtok=0.10, output_usd_per_mtok=0.50),
    },
)


def strict_schema(schema: dict) -> dict:
    """Our JSON schema in the form OpenAI strict mode accepts (no anyOf; type arrays)."""

    def convert(node: Any) -> Any:
        if isinstance(node, dict):
            options = node.get("anyOf")
            if options and len(options) == 2 and {"type": "null"} in options:
                (other,) = [o for o in options if o != {"type": "null"}]
                converted = convert(other)
                converted["type"] = [converted["type"], "null"]
                return converted
            if "anyOf" in node:
                raise ValueError("strict mode supports only nullable anyOf")
            return {k: convert(v) for k, v in node.items()}
        if isinstance(node, list):
            return [convert(v) for v in node]
        return node

    return convert(copy.deepcopy(schema))


def priced_model(served: str | None) -> str | None:
    """Map a dated snapshot (e.g. 'gpt-6-astra-2026-09-01') to its priced base model."""
    if served is None:
        return None
    known = [k.split("/", 1)[1] for k in PRICES.prices]
    matches = [m for m in known if served == m or served.startswith(f"{m}-")]
    return max(matches, key=len) if matches else served


def _usage(response: Any) -> ProviderUsage | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    # output_tokens includes reasoning tokens (billed as output).
    return ProviderUsage(
        input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, images=1
    )


def _status_error(exc: openai.APIStatusError) -> VisionAttemptError:
    status, code = exc.status_code, getattr(exc, "code", None)
    if isinstance(exc, openai.RateLimitError):
        if code == "insufficient_quota":  # billing, not a transient limit: never retried
            return VisionAttemptError(
                AttemptOutcome.CLIENT_ERROR,
                code=ErrorCode.QUOTA,
                http_status=status,
                detail="insufficient quota / billing",
            )
        after = exc.response.headers.get("retry-after")
        return VisionAttemptError(
            AttemptOutcome.RATE_LIMITED,
            http_status=status,
            retry_after_s=float(after) if after and after.replace(".", "", 1).isdigit() else None,
            detail="rate limited",
        )
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return VisionAttemptError(
            AttemptOutcome.AUTH_ERROR, http_status=status, detail=f"authentication ({code})"
        )
    if status >= 500:
        return VisionAttemptError(
            AttemptOutcome.SERVER_ERROR, http_status=status, detail=f"server error ({code})"
        )
    return VisionAttemptError(
        AttemptOutcome.CLIENT_ERROR,
        code=ErrorCode.PROVIDER_ERROR,
        http_status=status,
        detail=f"request rejected ({code})",
    )


def _refused(response: Any) -> bool:
    for item in getattr(response, "output", None) or []:
        for part in getattr(item, "content", None) or []:
            if getattr(part, "type", None) == "refusal":
                return True
    return False


class OpenAIVisionProvider:
    provider = PROVIDER

    def __init__(
        self, api_key: SecretStr, config: VisionConfig, client: openai.OpenAI | None = None
    ) -> None:
        if config.refusal_fallback:
            # No server-side fallback exists; record that instead of pretending.
            config = dataclasses.replace(config, refusal_fallback=False)
        self.config = config
        self.prompt, self.prompt_sha256 = load_prompt(PROMPT_VERSION)
        self.direct_prompt, self.direct_prompt_sha256 = load_prompt(DIRECT_PROMPT_VERSION)
        self._client = client or openai.OpenAI(api_key=api_key.get_secret_value(), max_retries=0)

    @property
    def configuration_id(self) -> str:
        return (
            f"B:{PROVIDER}:{self.config.model}:effort-{self.config.effort}:"
            f"{PROMPT_VERSION}@{self.prompt_sha256[:12]}:detail-{IMAGE_DETAIL}:nofallback"
        )

    def _image_part(self, image: PreparedImage) -> dict[str, Any]:
        data = base64.standard_b64encode(image.data).decode("ascii")
        return {
            "type": "input_image",
            "image_url": f"data:{image.media_type};base64,{data}",
            "detail": IMAGE_DETAIL,
        }

    def _create(self, system: str, content: list, schema: dict, name: str, timeout_s: float):
        # Structured output only: no tools are offered.
        client = self._client.with_options(timeout=timeout_s, max_retries=0)
        return client.responses.create(
            model=self.config.model,
            instructions=system,
            input=[{"role": "user", "content": content}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": name,
                    "schema": strict_schema(schema),
                    "strict": True,
                }
            },
            reasoning={"effort": self.config.effort},
            max_output_tokens=self.config.max_tokens,
        )

    def _structured_call(
        self,
        recorder: ScanRecorder,
        *,
        system: str,
        content: list,
        schema: dict,
        name: str,
        validate: Callable[[Any], Any],
        operation: str,
        stage: Stage,
    ) -> tuple[Any, Any]:
        def send(timeout_s: float) -> CallResult:
            try:
                response = self._create(system, content, schema, name, timeout_s)
            except openai.APITimeoutError:
                raise TimeoutError from None
            except openai.APIConnectionError:
                raise VisionAttemptError(
                    AttemptOutcome.TRANSPORT_ERROR, detail="connection error"
                ) from None
            except openai.APIStatusError as exc:
                raise _status_error(exc) from None

            usage = _usage(response)
            served = priced_model(getattr(response, "model", None))  # provenance keeps the raw ID
            billed = {"usage": usage, "provider_model": served}
            if _refused(response):
                raise VisionAttemptError(AttemptOutcome.REFUSED, detail="refused", **billed)
            if getattr(response, "status", None) == "incomplete":
                reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
                raise VisionAttemptError(
                    AttemptOutcome.CLIENT_ERROR,
                    code=ErrorCode.INVALID_SCHEMA,
                    detail=f"output incomplete ({reason})",
                    **billed,
                )
            try:
                output = validate(json.loads(getattr(response, "output_text", "") or ""))
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                kind = "not JSON" if isinstance(exc, json.JSONDecodeError) else "failed validation"
                if isinstance(exc, ValidationError):
                    kind += f": {validation_summary(exc)}"
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
            operation=operation,
            is_model_call=True,
            request_timeout_s=self.config.request_timeout_s,
            stage=stage,
            model=self.config.model,
        )
        return call_with_retries(recorder, spec, send, prices=PRICES).value

    def _provenance(self, response: Any, prompt_version: str, prompt_sha256: str) -> dict:
        return dict(
            provider=PROVIDER,
            model_requested=self.config.model,
            model_served=getattr(response, "model", None) or self.config.model,
            fallback_served=False,
            stop_reason=getattr(response, "status", None),
            prompt_version=prompt_version,
            prompt_sha256=prompt_sha256,
            sdk_version=openai.__version__,
            effort=self.config.effort,
            request_id=getattr(response, "_request_id", None),
        )

    def recognize(self, image: PreparedImage, recorder: ScanRecorder) -> RecognitionResponse:
        output, response = self._structured_call(
            recorder,
            system=self.prompt,
            content=[
                self._image_part(image),
                {"type": "input_text", "text": "Identify the visible foods."},
            ],
            schema=OUTPUT_SCHEMA,
            name="food_recognition",
            validate=RecognitionOutput.model_validate,
            operation="responses.vision",
            stage=Stage.RECOGNITION,
        )
        return RecognitionResponse(
            output=output, **self._provenance(response, PROMPT_VERSION, self.prompt_sha256)
        )

    def estimate_direct(self, image: PreparedImage, recorder: ScanRecorder) -> tuple[Any, dict]:
        output, response = self._structured_call(
            recorder,
            system=self.direct_prompt,
            content=[
                self._image_part(image),
                {
                    "type": "input_text",
                    "text": "Identify the visible foods and estimate nutrition.",
                },
            ],
            schema=DIRECT_SCHEMA,
            name="food_direct_estimate",
            validate=DirectOutput.model_validate,
            operation="responses.direct",
            stage=Stage.RECOGNITION,
        )
        return output, self._provenance(response, DIRECT_PROMPT_VERSION, self.direct_prompt_sha256)

    def choose_matches(
        self,
        image: PreparedImage,
        request_json: str,
        schema: dict,
        validate: Callable[[Any], Any],
        prompt: tuple[str, str, str],
        recorder: ScanRecorder,
    ) -> tuple[Any, dict]:
        """Model call 2: choose among retrieved candidates; `request_json` is data only."""
        version, text, sha256 = prompt
        output, response = self._structured_call(
            recorder,
            system=text,
            content=[self._image_part(image), {"type": "input_text", "text": request_json}],
            schema=schema,
            name="food_match_selection",
            validate=validate,
            operation="responses.select",
            stage=Stage.SELECTION,
        )
        return output, self._provenance(response, version, sha256)
