"""Frozen evaluation specification (plan §11 fair comparison, POC-15).

Before any calibration or held-out run, `foodvision freeze` records exactly what is being
evaluated: code commit, configuration IDs (which embed model, effort, prompt hashes and item
cap), confidence-rules, metrics and useful-result versions, preprocessing and catalog versions,
and the manifest hash. The spec holds no labels, so it is committed in Git.

Calibration and test runs refuse to start unless the running code and configurations match the
spec. Code may differ from the frozen commit only under `benchmarks/frozen/` and `docs/` (where
the spec and reports live). The test split is evaluated once per spec; a result that motivates a
change becomes a new spec and needs new confirmatory data.
"""

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from foodvision.benchmark.metrics import (
    ABSOLUTE_FLOOR,
    METRICS_VERSION,
    RELATIVE_TOLERANCE,
    USEFUL_DEFINITION,
)
from foodvision.benchmark.runner import REPO_ROOT, code_version
from foodvision.imaging.profiles import BASELINE
from foodvision.measurement.confidence import RULES_VERSION

FROZEN_DIR = REPO_ROOT / "benchmarks" / "frozen"
SPEC_VERSION = "frozen-spec-v1"
CHANGEABLE_AFTER_FREEZE = ("benchmarks/frozen", "docs")


class FreezeViolation(RuntimeError):
    pass


def build_spec(name: str, configs: dict[str, dict], manifest_sha256: str) -> dict:
    version = code_version()
    if version["dirty"]:
        raise FreezeViolation("commit all changes before freezing (working tree is dirty)")
    spec = {
        "spec_version": SPEC_VERSION,
        "name": name,
        "git_commit": version["git_commit"],
        "configs": configs,  # label -> {"pipeline_id", "configuration_id", catalog versions}
        "confidence_rules_version": RULES_VERSION,
        "metrics_version": METRICS_VERSION,
        "useful_definition": USEFUL_DEFINITION,
        "useful_tolerance": {"absolute_floor": ABSOLUTE_FLOOR, "relative": RELATIVE_TOLERANCE},
        "preprocessing_version": BASELINE.transform_version,
        "manifest_sha256": manifest_sha256,
    }
    spec["spec_sha256"] = spec_hash(spec)
    return spec


def spec_hash(spec: dict) -> str:
    body = {k: v for k, v in spec.items() if k != "spec_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def load_spec(path: Path) -> dict:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if spec.get("spec_version") != SPEC_VERSION or spec_hash(spec) != spec.get("spec_sha256"):
        raise FreezeViolation(f"{path}: not a valid, unmodified frozen spec")
    return spec


def _changed_code(frozen_commit: str) -> list[str]:
    excludes = [f":(exclude){p}" for p in CHANGEABLE_AFTER_FREEZE]
    done = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "diff",
            "--name-only",
            frozen_commit,
            "HEAD",
            "--",
            ".",
            *excludes,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise FreezeViolation(f"frozen commit {frozen_commit[:12]} is not in this repository")
    return [line for line in done.stdout.splitlines() if line]


@dataclass(frozen=True)
class RunState:
    configs: dict[str, dict]
    manifest_sha256: str
    dirty: bool


def check_matches(spec: dict, state: RunState) -> None:
    """Raise FreezeViolation listing every difference between the spec and this run."""
    problems = []
    if state.dirty:
        problems.append("working tree has uncommitted changes")
    changed = _changed_code(spec["git_commit"])
    if changed:
        problems.append(f"code changed since the freeze: {', '.join(changed[:8])}")
    for key, current in (
        ("confidence_rules_version", RULES_VERSION),
        ("metrics_version", METRICS_VERSION),
        ("useful_definition", USEFUL_DEFINITION),
        ("preprocessing_version", BASELINE.transform_version),
    ):
        if spec[key] != current:
            problems.append(f"{key}: frozen {spec[key]!r}, now {current!r}")
    if spec["manifest_sha256"] != state.manifest_sha256:
        problems.append("manifest changed since the freeze")
    if set(spec["configs"]) != set(state.configs):
        problems.append(f"configs: frozen {sorted(spec['configs'])}, now {sorted(state.configs)}")
    for label in set(spec["configs"]) & set(state.configs):
        frozen, now = spec["configs"][label], state.configs[label]
        if frozen != now:
            problems.append(f"{label}: configuration differs from the freeze ({frozen} != {now})")
    if problems:
        raise FreezeViolation("; ".join(problems))


def test_already_run(output: Path, spec: dict) -> list[str]:
    """Test batches already written for this spec (the held-out split runs once)."""
    found = []
    for meta in output.glob("*/batch.json"):
        data = json.loads(meta.read_text(encoding="utf-8"))
        if data.get("split") == "test" and data.get("frozen_spec_sha256") == spec["spec_sha256"]:
            found.append(meta.parent.name)
    return found
