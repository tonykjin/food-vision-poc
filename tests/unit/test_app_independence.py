"""Each API entry point imports only its own app's code and no UI framework."""

import json
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
