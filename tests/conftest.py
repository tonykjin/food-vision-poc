import pytest

from foodvision.config import FOREIGN_SECRETS

APP_VARIABLES = {
    "MOCK_MODE",
    "DATABASE_URL",
    "USDA_API_KEY",
    "FATSECRET_CLIENT_ID",
    "FATSECRET_CLIENT_SECRET",
    "ANTHROPIC_API_KEY",
    "VISION_MODEL",
    *{name for names in FOREIGN_SECRETS.values() for name in names},
}


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Run every test without real env files or provider variables from the host."""
    for name in APP_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
