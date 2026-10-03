"""Headless Streamlit page checks (no browser). File upload is covered by human checks."""

from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

APPS = Path(__file__).resolve().parents[2] / "apps"


class FakeResponse:
    def __init__(self, body: dict) -> None:
        self._body = body

    def json(self) -> dict:
        return self._body


@pytest.mark.parametrize(
    ("script", "app"), [("provider_ui.py", "provider"), ("agent_ui.py", "agent")]
)
def test_mock_mode_banner_is_shown(monkeypatch, script, app):
    health = {"status": "ok", "app": app, "mode": "mock", "pipeline_id": "X_mock"}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(health))
    page = AppTest.from_file(str(APPS / script)).run()
    assert not page.exception
    assert any("MOCK MODE" in e.value for e in page.error)


def test_unreachable_api_is_reported(monkeypatch):
    def refuse(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", refuse)
    page = AppTest.from_file(str(APPS / "provider_ui.py")).run()
    assert not page.exception
    assert any("API not reachable" in e.value for e in page.error)


def test_fatsecret_attribution_shown_for_live_provider(monkeypatch):
    health = {"status": "ok", "app": "provider", "mode": "live", "pipeline_id": "A_native"}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(health))
    page = AppTest.from_file(str(APPS / "provider_ui.py")).run()
    assert any(
        '<a href="https://platform.fatsecret.com">Powered by fatsecret Platform API</a>' in m.value
        for m in page.markdown
    )
