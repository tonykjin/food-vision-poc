"""The live smoke command refuses to run without explicit opt-in (no network here)."""

from foodvision.cli.main import main


def test_refuses_without_live_opt_in(monkeypatch, capsys):
    monkeypatch.delenv("ENABLE_LIVE_API_TESTS", raising=False)
    assert main(["smoke-fatsecret", "--image", "x.jpg", "--confirm-one-request"]) == 2
    assert "ENABLE_LIVE_API_TESTS" in capsys.readouterr().out


def test_refuses_without_confirmation(monkeypatch, capsys):
    monkeypatch.setenv("ENABLE_LIVE_API_TESTS", "true")
    assert main(["smoke-fatsecret", "--image", "x.jpg"]) == 2
    assert "--confirm-one-request" in capsys.readouterr().out


def test_refuses_without_credentials(monkeypatch, capsys):
    monkeypatch.setenv("ENABLE_LIVE_API_TESTS", "true")
    assert main(["smoke-fatsecret", "--image", "x.jpg", "--confirm-one-request"]) == 2
    assert "FATSECRET_CLIENT_ID" in capsys.readouterr().out


def test_smoke_budget_is_one_token_plus_one_image_without_retries():
    from foodvision.cli.smoke import SMOKE_BUDGET

    assert SMOKE_BUDGET.max_attempts == 2 and SMOKE_BUDGET.max_retries_per_request == 0
    assert SMOKE_BUDGET.max_model_calls == 0
