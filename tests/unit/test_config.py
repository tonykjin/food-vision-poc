from foodvision.config import AgentSettings, AppKind, ProviderSettings, load_settings


def test_provider_settings_declare_no_model_keys():
    fields = set(ProviderSettings.model_fields)
    assert "fatsecret_client_id" in fields
    assert not {"anthropic_api_key", "openai_api_key", "deepseek_api_key"} & fields


def test_agent_settings_declare_no_fatsecret_keys():
    fields = set(AgentSettings.model_fields)
    assert "anthropic_api_key" in fields
    assert not {"fatsecret_client_id", "fatsecret_client_secret"} & fields


def test_each_app_reads_only_its_own_env_file(tmp_path):
    (tmp_path / ".env.provider.local").write_text("MOCK_MODE=true\n")
    (tmp_path / ".env.agent.local").write_text("MOCK_MODE=false\n")
    assert load_settings(AppKind.PROVIDER).mock_mode is True
    assert load_settings(AppKind.AGENT).mock_mode is False


def test_empty_values_fall_back_to_defaults(tmp_path):
    env = tmp_path / "x.env"
    env.write_text("MOCK_MODE=\nPERSIST_PROVIDER_OUTPUTS=\nREGION=\n")
    settings = load_settings(AppKind.PROVIDER, env)
    assert settings.mock_mode is False
    assert settings.persist_provider_outputs is False
    assert settings.region == "US"


def test_secret_values_are_masked_in_repr(tmp_path):
    env = tmp_path / "x.env"
    env.write_text("ANTHROPIC_API_KEY=SENTINEL-SECRET-VALUE\n")
    settings = load_settings(AppKind.AGENT, env)
    assert "SENTINEL-SECRET-VALUE" not in repr(settings)
    assert settings.anthropic_api_key.get_secret_value() == "SENTINEL-SECRET-VALUE"


def test_provider_outputs_not_persisted_by_default():
    settings = load_settings(AppKind.PROVIDER, "missing.env")
    assert settings.persist_provider_outputs is False
    assert settings.provider_output_policy_version == "pending"
