"""Per-app settings. Each app reads only its own ignored env file.

App A (provider) never declares model keys; App B (agent) never declares fatsecret keys.
Secrets are SecretStr so repr/logs show '**********'. See docs/credential-handling.md.
"""

from enum import StrEnum
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppKind(StrEnum):
    PROVIDER = "provider"
    AGENT = "agent"


ENV_FILES: dict[AppKind, str] = {
    AppKind.PROVIDER: ".env.provider.local",
    AppKind.AGENT: ".env.agent.local",
}

# Secrets that must never appear in the other app's configuration (plan §5).
FOREIGN_SECRETS: dict[AppKind, tuple[str, ...]] = {
    AppKind.PROVIDER: (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "EVALUATOR_DATABASE_URL",
        "MIGRATION_DATABASE_URL",
    ),
    AppKind.AGENT: (
        "FATSECRET_CLIENT_ID",
        "FATSECRET_CLIENT_SECRET",
        "EVALUATOR_DATABASE_URL",
        "MIGRATION_DATABASE_URL",
    ),
}


class CommonSettings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        env_ignore_empty=True,
        env_file_encoding="utf-8",
    )

    mock_mode: bool = False
    database_url: SecretStr | None = None
    usda_api_key: SecretStr | None = None
    region: str = "US"
    language: str = "en"
    max_scan_seconds: float = Field(default=45.0, gt=0)
    max_external_attempts_per_scan: int = Field(default=8, ge=0)
    # None = no dollar cap (user decision 2026-10-02); call/attempt/deadline limits still apply.
    max_scan_cost_usd: float | None = Field(default=None, ge=0)


class ProviderSettings(CommonSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILES[AppKind.PROVIDER])

    fatsecret_client_id: SecretStr | None = None
    fatsecret_client_secret: SecretStr | None = None
    persist_provider_outputs: bool = False
    provider_output_policy_version: str = "pending"
    # App A has no LLM fallback (plan §8 A3): zero model calls.
    max_model_calls_per_scan: int = Field(default=0, ge=0, le=0)


class AgentSettings(CommonSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILES[AppKind.AGENT])

    anthropic_api_key: SecretStr | None = None
    vision_provider: str = "anthropic"
    vision_model: str | None = None
    pipeline_mode: str = "grounded"
    max_model_calls_per_scan: int = Field(default=2, ge=0)


AppSettings = ProviderSettings | AgentSettings


def load_settings(kind: AppKind, env_file: Path | str | None = None) -> AppSettings:
    """Load one app's settings from the process environment and its own env file."""
    cls = ProviderSettings if kind is AppKind.PROVIDER else AgentSettings
    path = env_file if env_file is not None else ENV_FILES[kind]
    return cls(_env_file=path)
