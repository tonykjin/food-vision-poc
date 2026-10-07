"""Vision-provider registry for App B (POC-14).

`VISION_PROVIDER` picks the adapter and `VISION_MODEL` the model (default per provider). Every
adapter uses the same prompts, schemas, image bytes and server-side validation, so a provider
switch changes only the model call. Unsupported providers are refused, never substituted.
"""

from pydantic import SecretStr

from foodvision.config import AgentSettings
from foodvision.providers.claude_vision import VisionConfig

DEFAULT_MODELS = {"anthropic": "claude-opus-5-5", "openai": "gpt-6-astra"}
KEY_NAMES = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
# Checked 2026-10-07 and recorded instead of guessed: DeepSeek documents image input
# (`deepseek-flash`) but its structured-output support is unverified, and there is no key.
UNAVAILABLE = {"deepseek": "no account access; JSON-schema output with images unverified"}


def model_for(settings: AgentSettings) -> str:
    return settings.vision_model or DEFAULT_MODELS[settings.vision_provider]


def key_for(settings: AgentSettings) -> SecretStr | None:
    return {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
    }[settings.vision_provider]


def build_vision_provider(settings: AgentSettings):
    """(provider, None) or (None, reason it is unavailable)."""
    key = key_for(settings)
    if key is None:
        name = KEY_NAMES[settings.vision_provider]
        return None, f"{name} is not configured for VISION_PROVIDER={settings.vision_provider}"
    config = VisionConfig(
        model=model_for(settings),
        effort=settings.vision_effort,
        max_tokens=settings.vision_max_tokens,
        refusal_fallback=settings.vision_refusal_fallback,
    )
    if settings.vision_provider == "openai":
        from foodvision.providers.openai_vision import OpenAIVisionProvider

        return OpenAIVisionProvider(key, config), None
    from foodvision.providers.claude_vision import ClaudeVisionProvider

    return ClaudeVisionProvider(key, config), None
