"""Each API entry point imports only its own app's code and no UI framework."""

import json
import os
import subprocess
import sys

import pytest

PROBE = """
import json, sys
import {module}
print(json.dumps(sorted(m for m in sys.modules if m.startswith(("foodvision", "streamlit")))))
"""


def loaded_modules(module: str, cwd) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-c", PROBE.format(module=module)],
        capture_output=True,
        text=True,
        cwd=cwd,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    ("module", "other"),
    [("foodvision.api.provider_app", "agent_app"), ("foodvision.api.agent_app", "provider_app")],
)
def test_api_entry_points_do_not_import_each_other(module, other, tmp_path):
    modules = loaded_modules(module, tmp_path)
    assert module in modules
    assert not [m for m in modules if other in m]
    assert not [m for m in modules if m.startswith("streamlit")]


def test_agent_app_never_loads_fatsecret_code(tmp_path):
    modules = loaded_modules("foodvision.api.agent_app", tmp_path)
    assert not [m for m in modules if "fatsecret" in m or "provider_native" in m]


def test_provider_app_starts_without_any_model_key(tmp_path):
    env_file = tmp_path / ".env.provider.local"
    env_file.write_text("FATSECRET_CLIENT_ID=dummy\nFATSECRET_CLIENT_SECRET=dummy\n")
    probe = (
        "import json, os\n"
        "assert not [k for k in os.environ if k.endswith('_API_KEY') and 'USDA' not in k]\n"
        "from fastapi.testclient import TestClient\n"
        "from foodvision.api.provider_app import app\n"
        "print(json.dumps(TestClient(app).get('/health').json()))"
    )
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        check=True,
    )
    health = json.loads(result.stdout.strip().splitlines()[-1])
    assert health["app"] == "provider" and health["ready"] is True
    assert health["pipeline_id"] == "A_native"


def test_provider_app_never_loads_anthropic_or_agent_code(tmp_path):
    probe = PROBE.replace('("foodvision", "streamlit")', '("foodvision", "streamlit", "anthropic")')
    result = subprocess.run(
        [sys.executable, "-c", probe.format(module="foodvision.api.provider_app")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=True,
    )
    modules = json.loads(result.stdout)
    assert not [m for m in modules if m.startswith("anthropic")]
    assert not [m for m in modules if "claude_vision" in m or "agent_recognition" in m]
