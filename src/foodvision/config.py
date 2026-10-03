"""Per-app settings. Each app reads only its own ignored env file.

App A (provider) never declares model keys; App B (agent) never declares fatsecret keys.
Secrets are SecretStr so repr/logs show '**********'. See docs/credential-handling.md.
"""

from enum import StrEnum
from pathlib import Path

from pydantic import SecretStr
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
    ),
    AppKind.AGENT: (
        "FATSECRET_CLIENT_ID",
        "FATSECRET_CLIENT_SECRET",
        "EVALUATOR_DATABASE_URL",
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
    max_scan_seconds: float = 45.0


class ProviderSettings(CommonSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILES[AppKind.PROVIDER])

    fatsecret_client_id: SecretStr | None = None
    fatsecret_client_secret: SecretStr | None = None
    persist_provider_outputs: bool = False
    provider_output_policy_version: str = "pending"


class AgentSettings(CommonSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILES[AppKind.AGENT])

    anthropic_api_key: SecretStr | None = None
    vision_provider: str = "anthropic"
    vision_model: str | None = None
    pipeline_mode: str = "grounded"
    max_model_calls_per_scan: int = 2
    max_external_attempts_per_scan: int = 8


AppSettings = ProviderSettings | AgentSettings


def load_settings(kind: AppKind, env_file: Path | str | None = None) -> AppSettings:
    """Load one app's settings from the process environment and its own env file."""
    cls = ProviderSettings if kind is AppKind.PROVIDER else AgentSettings
    path = env_file if env_file is not None else ENV_FILES[kind]
    return cls(_env_file=path)
