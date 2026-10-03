"""`foodvision doctor`: boolean-only configuration checks. Makes no network or paid calls.

Prints variable names with `set`/`missing` only, never values, lengths, prefixes or hashes
(docs/credential-handling.md). Exit code 1 means the other app's secrets are present.
"""

import os
from collections.abc import Callable, Mapping
from pathlib import Path

from dotenv import dotenv_values

from foodvision.config import ENV_FILES, FOREIGN_SECRETS, AppKind, load_settings

REQUIRED_FOR_LIVE: dict[AppKind, tuple[str, ...]] = {
    AppKind.PROVIDER: ("FATSECRET_CLIENT_ID", "FATSECRET_CLIENT_SECRET"),
    AppKind.AGENT: ("ANTHROPIC_API_KEY", "VISION_MODEL"),
}
OPTIONAL: tuple[str, ...] = ("USDA_API_KEY", "DATABASE_URL")

LIVE_STATUS: dict[AppKind, str] = {
    AppKind.PROVIDER: "not implemented yet (POC-08, #8)",
    AppKind.AGENT: "not implemented yet (POC-09/POC-10, #9 #10)",
}


def _is_set(value: str | None) -> bool:
    return bool(value and value.strip())


def run_doctor(
    kind: AppKind,
    env_file: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
    out: Callable[[str], None] = print,
) -> int:
    path = Path(env_file if env_file is not None else ENV_FILES[kind])
    environ = os.environ if environ is None else environ
    file_values = dotenv_values(path) if path.is_file() else {}

    def present(name: str) -> bool:
        return _is_set(environ.get(name)) or _is_set(file_values.get(name))

    settings = load_settings(kind, path)

    out(f"foodvision doctor --app {kind.value}")
    out(f"env file            {path} ({'found' if path.is_file() else 'absent'})")
    out(f"mode                {'MOCK (synthetic)' if settings.mock_mode else 'live'}")
    out(f"live pipeline       {LIVE_STATUS[kind]}")
    out("")
    out("required for live mode:")
    for name in REQUIRED_FOR_LIVE[kind]:
        out(f"  {name:<26} {'set' if present(name) else 'missing'}")
    out("optional:")
    for name in OPTIONAL:
        out(f"  {name:<26} {'set' if present(name) else 'missing'}")

    foreign = []
    for name in FOREIGN_SECRETS[kind]:
        if _is_set(file_values.get(name)):
            foreign.append(f"{name} (in {path})")
        if _is_set(environ.get(name)):
            foreign.append(f"{name} (in process environment)")
    out("")
    if foreign:
        out("FAIL: secrets belonging to another app or the evaluator are present:")
        for entry in foreign:
            out(f"  {entry}")
        out("Remove them; each app must run with only its own secrets (plan §5).")
    else:
        out("app isolation       ok (no foreign secrets present)")
    out("network calls       none (doctor makes no paid or live requests)")
    return 1 if foreign else 0
