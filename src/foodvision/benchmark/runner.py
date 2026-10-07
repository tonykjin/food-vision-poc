"""Manifest-driven benchmark runner (plan §11 fair comparison, POC-13).

- Each photo is prepared once with the baseline profile; every configuration gets the same
  processed bytes and the same context (region, language). No labels reach a pipeline.
- Each (photo, repeat) runs every configuration, and the order rotates so no configuration
  always goes first. Every run is a fresh analysis: there is no application result cache.
- The first automatic result is the one scored; corrections never exist in a batch.
- Failures and exceptions are recorded as failed attempts. Runs stopped by a batch cap are
  listed as not run, and the batch is marked incomplete.
"""

import subprocess
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from foodvision.benchmark.manifest import Group, Split, reference_totals
from foodvision.benchmark.metrics import Attempt, Reference
from foodvision.contracts.errors import ErrorCode
from foodvision.contracts.requests import AnalysisContext
from foodvision.imaging.prepare import PreparedImage, prepare_image
from foodvision.imaging.profiles import BASELINE
from foodvision.measurement.budget import BudgetPolicy
from foodvision.measurement.events import ScanStatus
from foodvision.measurement.spans import ScanRecorder
from foodvision.pipelines.base import Pipeline

REPO_ROOT = Path(__file__).resolve().parents[3]
CACHE_NOTES = [
    "Application result caches: none exist; every run is a fresh analysis.",
    "fatsecret OAuth token is reused across scans after the first (warm credentials).",
    "Vendor-side caches (fatsecret, Anthropic) are not observable or controllable from here.",
    "Anthropic prompt caching is not enabled by the adapter.",
]


@dataclass(frozen=True)
class Sample:
    sample_id: str
    group_id: str
    image: PreparedImage


@dataclass(frozen=True)
class PlannedRun:
    sample: Sample
    repeat: int
    config: str
    position: int  # 0 = this configuration went first for this photo and repeat


@dataclass
class BatchCaps:
    max_total_cost_usd: float | None = None  # known costs only
    max_scans: int | None = None


@dataclass
class BatchResult:
    attempts: list[Attempt] = field(default_factory=list)
    run_records: list[dict] = field(default_factory=list)  # payload-free per run
    not_run: list[PlannedRun] = field(default_factory=list)
    stop_reason: str | None = None


def references(groups: Sequence[Group]) -> dict[str, Reference]:
    out = {}
    for g in groups:
        totals = reference_totals(g)
        if g.recipe is not None:
            components = ((g.recipe.dish_identity, "unknown", g.recipe.served_grams),)
        else:
            components = tuple(
                (c.identity, c.preparation.value, c.edible_grams) for c in g.components
            )
        out[g.group_id] = Reference(
            group_id=g.group_id,
            category=g.category.value,
            grade=g.quality_grade.value,
            expected_outcome=g.expected_outcome.value,
            nutrients=None if totals is None else totals.nutrients,
            components=components,
        )
    return out


def select_groups(groups: Sequence[Group], split: Split, allow_test: bool) -> list[Group]:
    """Only reviewed groups of the requested split. The test split needs explicit consent."""
    if split is Split.TEST and not allow_test:
        raise PermissionError(
            "the test split is the locked final evaluation; pass --allow-test-split only with "
            "frozen data, prompts, configuration and code"
        )
    return [g for g in groups if g.split is split and g.review.status == "reviewed"]


def prepare_samples(groups: Sequence[Group], data_dir: Path) -> list[Sample]:
    samples = []
    for g in groups:
        for photo in g.photos:
            image = prepare_image((data_dir / photo.file).read_bytes(), BASELINE)
            if image.original_sha256 != photo.sha256:
                raise ValueError(f"{g.group_id}/{photo.photo_id}: file does not match manifest")
            samples.append(Sample(f"{g.group_id}:{photo.photo_id}", g.group_id, image))
    return sorted(samples, key=lambda s: s.sample_id)


def plan_runs(samples: Sequence[Sample], configs: Sequence[str], repeats: int) -> list[PlannedRun]:
    """Interleaved, order-rotated: the first config shifts with the photo and the repeat."""
    plan = []
    for repeat in range(repeats):
        for index, sample in enumerate(samples):
            shift = (repeat + index) % len(configs)
            order = [*configs[shift:], *configs[:shift]]
            plan += [PlannedRun(sample, repeat, c, pos) for pos, c in enumerate(order)]
    return plan


def run_batch(
    plan: Sequence[PlannedRun],
    pipelines: Mapping[str, Pipeline],
    budgets: Mapping[str, BudgetPolicy],
    caps: BatchCaps,
    region: str = "US",
    language: str = "en",
) -> BatchResult:
    out = BatchResult()
    spent = 0.0
    for index, run in enumerate(plan):
        if caps.max_scans is not None and index >= caps.max_scans:
            out.stop_reason = f"max_scans {caps.max_scans} reached"
        elif caps.max_total_cost_usd is not None and spent >= caps.max_total_cost_usd:
            out.stop_reason = f"max_total_cost_usd {caps.max_total_cost_usd} reached"
        if out.stop_reason:
            out.not_run = list(plan[index:])
            break
        pipeline = pipelines[run.config]
        scan_id = uuid.uuid4().hex
        recorder = ScanRecorder(
            scan_id,
            pipeline.pipeline_id,
            budget=budgets[run.config],
            configuration_id=getattr(pipeline, "configuration_id", None),
            is_mock=pipeline.is_mock,
        )
        image = run.sample.image
        context = AnalysisContext(
            scan_id=scan_id,
            original_sha256=image.original_sha256,
            processed_sha256=image.processed_sha256,
            preprocessing_version=image.transform_version,
            pipeline_id=pipeline.pipeline_id,
            region=region,
            language=language,
        )
        exception = None
        try:
            result = pipeline.analyze(image, context, recorder)
            status, code = result.status.value, result.error.code if result.error else None
        except Exception as exc:  # never drop a run: record it as a failure
            result, status, code = None, "failed", ErrorCode.PROVIDER_ERROR
            exception = type(exc).__name__  # the type only; messages may echo provider text
        record = recorder.finish(ScanStatus(status), code)
        spent += record.known_cost_usd
        out.attempts.append(
            Attempt(
                config=run.config,
                group_id=run.sample.group_id,
                sample_id=run.sample.sample_id,
                repeat=run.repeat,
                status=status,
                error_code=code.value if code else None,
                server_total_ms=record.server_total_ms,
                known_cost_usd=record.known_cost_usd,
                estimated_cost_usd=record.estimated_cost_usd,
                result=result,
            )
        )
        out.run_records.append(
            {
                "scan_id": scan_id,
                "config": run.config,
                "configuration_id": record.configuration_id,
                "sample_id": run.sample.sample_id,
                "group_id": run.sample.group_id,
                "repeat": run.repeat,
                "order_position": run.position,
                "processed_sha256": image.processed_sha256,
                "status": status,
                "error_code": code.value if code else None,
                "exception": exception,
                "started_at_utc": record.started_at_utc.isoformat(),
                "server_total_ms": record.server_total_ms,
                "attempts": record.attempts,
                "model_calls": record.model_calls,
                "retries": record.retries,
                "timeouts": record.timeouts,
                "known_cost_usd": record.known_cost_usd,
                "estimated_cost_usd": record.estimated_cost_usd,
            }
        )
    return out


def code_version() -> dict:
    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, check=False
        )
        return done.stdout.strip()

    return {"git_commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def new_batch_id(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return f"{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
