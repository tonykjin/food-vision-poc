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


def test_opt_in_can_come_from_the_provider_env_file(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ENABLE_LIVE_API_TESTS", raising=False)
    (tmp_path / ".env.provider.local").write_text("ENABLE_LIVE_API_TESTS=true\n")
    # Opt-in accepted; it then stops at the missing --confirm-one-request flag.
    assert main(["smoke-fatsecret", "--image", "x.jpg"]) == 2
    assert "--confirm-one-request" in capsys.readouterr().out


def test_agent_env_file_does_not_enable_provider_smoke(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ENABLE_LIVE_API_TESTS", raising=False)
    (tmp_path / ".env.agent.local").write_text("ENABLE_LIVE_API_TESTS=true\n")
    assert main(["smoke-fatsecret", "--image", "x.jpg", "--confirm-one-request"]) == 2
    assert "ENABLE_LIVE_API_TESTS" in capsys.readouterr().out


def test_vision_smoke_refuses_without_opt_in_and_budget_is_one_call(monkeypatch, capsys):
    from foodvision.cli.smoke import VISION_SMOKE_BUDGET

    monkeypatch.delenv("ENABLE_LIVE_API_TESTS", raising=False)
    assert main(["smoke-vision", "--image", "x.jpg", "--confirm-one-request"]) == 2
    assert "ENABLE_LIVE_API_TESTS" in capsys.readouterr().out
    assert VISION_SMOKE_BUDGET.max_model_calls == 1 and VISION_SMOKE_BUDGET.max_attempts == 1


def test_vision_smoke_summary_names_the_actual_provider(tmp_path, monkeypatch, capsys):
    from tests.conftest import synthetic_image
    from tests.unit.test_openai_vision import provider as openai_provider
    from tests.unit.test_openai_vision import response

    from foodvision.cli.smoke import smoke_vision
    from foodvision.providers import registry

    vision, _ = openai_provider([response()])
    monkeypatch.setattr(registry, "build_vision_provider", lambda settings: (vision, None))
    monkeypatch.setenv("ENABLE_LIVE_API_TESTS", "true")
    monkeypatch.setenv("PIPELINE_MODE", "recognition_only")
    image = tmp_path / "synthetic.jpg"
    image.write_bytes(synthetic_image())
    assert smoke_vision(str(image), confirmed=True) == 0
    out = capsys.readouterr().out
    assert "sdk                openai " in out and "anthropic" not in out
