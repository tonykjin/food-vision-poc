import pytest

from foodvision.cli.doctor import run_doctor
from foodvision.cli.main import main
from foodvision.config import AppKind

SENTINEL = "SENTINEL-SECRET-9f3a"


def capture(kind, env_file, environ=None):
    lines: list[str] = []
    code = run_doctor(kind, env_file=env_file, environ=environ or {}, out=lines.append)
    return code, "\n".join(lines)


def test_reports_set_and_missing_without_values(tmp_path):
    env = tmp_path / "p.env"
    env.write_text(f"FATSECRET_CLIENT_ID={SENTINEL}\nFATSECRET_CLIENT_SECRET=\n")
    code, output = capture(AppKind.PROVIDER, env)
    assert code == 0
    assert SENTINEL not in output
    assert "FATSECRET_CLIENT_ID" in output and "set" in output
    secret_line = next(line for line in output.splitlines() if "FATSECRET_CLIENT_SECRET" in line)
    assert secret_line.split()[-1] == "missing"


def test_process_environment_counts_as_set(tmp_path):
    code, output = capture(AppKind.AGENT, tmp_path / "none.env", {"ANTHROPIC_API_KEY": SENTINEL})
    assert code == 0
    assert SENTINEL not in output
    key_line = next(line for line in output.splitlines() if "ANTHROPIC_API_KEY" in line)
    assert key_line.split()[-1] == "set"


@pytest.mark.parametrize(
    ("kind", "foreign"),
    [
        (AppKind.PROVIDER, "ANTHROPIC_API_KEY"),
        (AppKind.PROVIDER, "EVALUATOR_DATABASE_URL"),
        (AppKind.AGENT, "FATSECRET_CLIENT_SECRET"),
        (AppKind.AGENT, "MIGRATION_DATABASE_URL"),
    ],
)
def test_foreign_secret_in_env_file_fails(tmp_path, kind, foreign):
    env = tmp_path / "x.env"
    env.write_text(f"{foreign}={SENTINEL}\n")
    code, output = capture(kind, env)
    assert code == 1
    assert foreign in output
    assert SENTINEL not in output


def test_foreign_secret_in_process_environment_fails(tmp_path):
    code, output = capture(AppKind.PROVIDER, tmp_path / "none.env", {"ANTHROPIC_API_KEY": "x"})
    assert code == 1
    assert "process environment" in output


def test_cli_entry_point(tmp_path, capsys):
    env = tmp_path / "a.env"
    env.write_text(f"ANTHROPIC_API_KEY={SENTINEL}\nMOCK_MODE=true\n")
    assert main(["doctor", "--app", "agent", "--env-file", str(env)]) == 0
    output = capsys.readouterr().out
    assert "MOCK" in output
    assert SENTINEL not in output
