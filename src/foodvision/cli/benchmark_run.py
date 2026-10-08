"""`foodvision benchmark` and `foodvision report` (POC-13).

benchmark: manifest-driven paired runs with saved, rights-filtered outputs; the full metrics
(including any transient-only fatsecret metrics) are printed, never written. A real (paid) run
needs --confirm-paid-run plus --max-total-cost-usd and --max-scans.
report: rebuilds the saved report from a batch directory. fatsecret-derived metrics stay
unavailable there because the batch never saved fatsecret outputs.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from foodvision.benchmark.manifest import Split, load_groups
from foodvision.benchmark.metrics import METRICS_VERSION, Attempt
from foodvision.benchmark.report import build_report, source_of, to_markdown
from foodvision.benchmark.runner import (
    CACHE_NOTES,
    REPO_ROOT,
    BatchCaps,
    code_version,
    new_batch_id,
    plan_runs,
    prepare_samples,
    references,
    run_batch,
    select_groups,
)
from foodvision.benchmark.validate import _git_ignored, manifest_sha256
from foodvision.cli.benchmark import _validate
from foodvision.config import AppKind, EvaluatorSettings, ProviderSettings, load_settings
from foodvision.contracts.results import AnalysisResult
from foodvision.imaging.profiles import BASELINE
from foodvision.measurement.budget import BudgetPolicy
from foodvision.measurement.storage_policy import Purpose, filter_result, policy_from_settings

MODES = {"B_grounded": "grounded", "B_direct": "direct"}
CONFIG_APPS = {
    "A_native": AppKind.PROVIDER,
    "B_grounded": AppKind.AGENT,
    "B_direct": AppKind.AGENT,
    "A_mock": AppKind.PROVIDER,
    "B_mock": AppKind.AGENT,
}


def _pipeline(config: str):
    from foodvision.api.factory import live_pipeline
    from foodvision.pipelines.mock import MockPipeline

    settings = load_settings(CONFIG_APPS[config])
    if config in MODES:  # one batch can compare B_grounded and B_direct on identical bytes
        settings = settings.model_copy(update={"pipeline_mode": MODES[config]})
    if config.endswith("_mock"):
        pipeline = MockPipeline(config)
    else:
        pipeline, reason = live_pipeline(CONFIG_APPS[config], settings)
        if pipeline is None:
            raise SystemExit(f"{config} unavailable: {reason}")
        if pipeline.pipeline_id != config:
            raise SystemExit(
                f"{config} requested but the app is configured for "
                f"{pipeline.pipeline_id} (check PIPELINE_MODE)"
            )
    budget = BudgetPolicy(
        deadline_s=settings.max_scan_seconds,
        max_model_calls=settings.max_model_calls_per_scan,
        max_attempts=settings.max_external_attempts_per_scan,
        max_cost_usd=settings.max_scan_cost_usd,
    )
    return pipeline, budget, settings


def _safe_output(path: Path) -> bool:
    resolved = path.resolve()
    return not resolved.is_relative_to(REPO_ROOT) or _git_ignored(resolved)


def _provenance(attempts: list[Attempt], config: str) -> list[dict]:
    seen = {}
    for a in attempts:
        prov = a.result.model_provenance if a.result is not None else None
        if a.config == config and prov is not None:
            key = (prov.model_served, prov.prompt_version, prov.prompt_sha256)
            seen[key] = {
                "model_requested": prov.model_requested,
                "model_served": key[0],
                "prompt_version": key[1],
                "prompt_sha256": key[2],
                "sdk_version": prov.sdk_version,
                "effort": prov.effort,
            }
    return list(seen.values())


def run_benchmark(args) -> int:
    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    unknown = [c for c in configs if c not in CONFIG_APPS]
    if unknown or len(set(configs)) != len(configs):
        print(f"Unknown or repeated configs: {unknown or configs}. Known: {sorted(CONFIG_APPS)}")
        return 2
    if args.concurrency != 1:
        print("Only --concurrency 1 is implemented (sequential runs keep budgets exact).")
        return 2
    paid = [c for c in configs if not c.endswith("_mock")]
    if paid and not (
        args.confirm_paid_run and args.max_total_cost_usd is not None and args.max_scans is not None
    ):
        print(
            f"Refusing a paid run of {paid}: pass --confirm-paid-run, --max-total-cost-usd "
            "and --max-scans."
        )
        return 2
    output = Path(args.output)
    if not _safe_output(output):
        print(
            f"Refusing: {output} is a tracked path in the repository; use work/ or a path "
            "outside Git."
        )
        return 2

    evaluator = EvaluatorSettings()
    data_dir = Path(args.data_dir) if args.data_dir else evaluator.benchmark_data_dir
    manifest = Path(args.manifest)
    groups, validation = _validate(manifest, data_dir)
    if not validation.ok or data_dir is None:
        print("Refusing: the manifest must validate with photo files checked (--data-dir).")
        for e in validation.errors:
            print(f"  {e}")
        return 1
    split = Split(args.split)
    try:
        selected = select_groups(groups, split, args.allow_test_split)
    except PermissionError as exc:
        print(f"Refusing: {exc}")
        return 2
    version = code_version()
    if split is Split.TEST and version["dirty"]:
        print("Refusing a test-split run from a working tree with uncommitted changes.")
        return 2
    if not selected:
        print(f"No reviewed groups in split {split.value}; nothing to run.")
        return 1

    built = {c: _pipeline(c) for c in configs}
    contexts = {(s.region, s.language) for _, _, s in built.values()}
    if len(contexts) != 1:
        print(f"Refusing: configurations use different region/language settings: {contexts}")
        return 2
    region, language = contexts.pop()
    samples = prepare_samples(selected, data_dir)
    plan = plan_runs(samples, configs, args.repeats)
    print(
        f"Planned {len(plan)} run(s): {len(samples)} photo(s) x {len(configs)} config(s) "
        f"x {args.repeats} repeat(s)."
    )

    batch = run_batch(
        plan,
        {c: p for c, (p, _, _) in built.items()},
        {c: b for c, (_, b, _) in built.items()},
        BatchCaps(args.max_total_cost_usd, args.max_scans),
        region,
        language,
    )
    provider = ProviderSettings()
    policy = policy_from_settings(
        provider.persist_provider_outputs, provider.provider_output_policy_version
    )
    batch_id = new_batch_id()
    out = output / batch_id
    out.mkdir(parents=True, exist_ok=False)
    meta = {
        "batch_id": batch_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "split": split.value,
        "repeats": args.repeats,
        "concurrency": 1,
        "metrics_version": METRICS_VERSION,
        "manifest": str(manifest.resolve()),
        "manifest_sha256": manifest_sha256(groups),
        "reference_version": f"manifest@{manifest_sha256(groups)[:12]}",
        "groups": len(selected),
        "samples": len(samples),
        "preprocessing_version": BASELINE.transform_version,
        "region": region,
        "language": language,
        "code": version,
        "caps": {"max_total_cost_usd": args.max_total_cost_usd, "max_scans": args.max_scans},
        "stop_reason": batch.stop_reason,
        "cache_notes": CACHE_NOTES,
        "scored_result": "first automatic result of each run (no corrections exist)",
        "configs": {
            c: {
                "pipeline_id": p.pipeline_id,
                "configuration_id": getattr(p, "configuration_id", None),
                "budget": b.model_dump(),
                "catalog_source_versions": getattr(p, "source_versions", None),
                "model_and_prompt": _provenance(batch.attempts, c),
            }
            for c, (p, b, _) in built.items()
        },
    }
    (out / "batch.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    by_scan = {a.sample_id + f"#{a.repeat}#{a.config}": a for a in batch.attempts}
    with (out / "runs.jsonl").open("w", encoding="utf-8") as f:
        for record in batch.run_records:
            key = f"{record['sample_id']}#{record['repeat']}#{record['config']}"
            res = by_scan[key].result
            saved = {**record}
            if res is not None:  # rights-filtered: restricted fatsecret content never saved
                saved["result"] = filter_result(
                    res, source_of(record["config"]), policy, Purpose.PERSIST
                )
            f.write(json.dumps(saved) + "\n")
        for run in batch.not_run:
            f.write(
                json.dumps(
                    {
                        "config": run.config,
                        "sample_id": run.sample.sample_id,
                        "repeat": run.repeat,
                        "status": "not_run",
                    }
                )
                + "\n"
            )
    refs = references(selected)
    saved_report = build_report(
        batch.attempts, refs, configs, policy, Purpose.PERSIST, meta, len(batch.not_run)
    )
    (out / "report.json").write_text(json.dumps(saved_report, indent=2), encoding="utf-8")
    (out / "report.md").write_text(to_markdown(saved_report), encoding="utf-8")
    shown = build_report(
        batch.attempts,
        refs,
        configs,
        policy,
        Purpose.TRANSIENT_EVALUATION,
        meta,
        len(batch.not_run),
    )
    print("=" * 72)
    print("TRANSIENT REPORT (terminal only; fatsecret-derived metrics are never saved)")
    print("=" * 72)
    print(to_markdown(shown))
    print(f"Saved (rights-filtered): {out}")
    return 0


def run_report(args) -> int:
    batch_dir = Path(args.batch)
    meta = json.loads((batch_dir / "batch.json").read_text(encoding="utf-8"))
    groups, errors = load_groups(Path(meta["manifest"]))
    if errors or manifest_sha256(groups) != meta["manifest_sha256"]:
        print("Refusing: the manifest changed since the batch ran (or no longer parses).")
        return 1
    attempts, not_run = [], 0
    for line in (batch_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record["status"] == "not_run":
            not_run += 1
            continue
        saved = record.get("result")
        result = None
        if saved is not None and not saved.get("_policy", {}).get("dropped"):
            result = AnalysisResult.model_validate(
                {k: v for k, v in saved.items() if k != "_policy"}
            )
        attempts.append(
            Attempt(
                config=record["config"],
                group_id=record["group_id"],
                sample_id=record["sample_id"],
                repeat=record["repeat"],
                status=record["status"],
                error_code=record["error_code"],
                server_total_ms=record["server_total_ms"],
                known_cost_usd=record["known_cost_usd"],
                estimated_cost_usd=record["estimated_cost_usd"],
                result=result,
            )
        )
    provider = ProviderSettings()
    policy = policy_from_settings(
        provider.persist_provider_outputs, provider.provider_output_policy_version
    )
    configs = list(meta["configs"])
    selected = [g for g in groups if g.split is Split(meta["split"])]
    report = build_report(
        attempts, references(selected), configs, policy, Purpose.PERSIST, meta, not_run
    )
    output = Path(args.output)
    if not _safe_output(output):
        print(f"Refusing: {output} is a tracked path in the repository.")
        return 2
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output / "report.md").write_text(to_markdown(report), encoding="utf-8")
    print(to_markdown(report))
    return 0
