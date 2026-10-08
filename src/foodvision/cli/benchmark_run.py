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


def split_config(config: str) -> tuple[str, str | None, str | None]:
    """'B_grounded@openai:gpt-6.1-sol' -> ('B_grounded', 'openai', 'gpt-6.1-sol')."""
    base, _, variant = config.partition("@")
    provider, _, model = variant.partition(":")
    return base, provider or None, model or None


def _pipeline(config: str):
    from foodvision.api.factory import live_pipeline
    from foodvision.pipelines.mock import MockPipeline

    base, provider, model = split_config(config)
    settings = load_settings(CONFIG_APPS[base])
    if base in MODES:  # one batch can compare B modes and providers on identical bytes
        update = {"pipeline_mode": MODES[base]}
        if provider:
            update["vision_provider"] = provider
            update["vision_model"] = model
        settings = settings.model_copy(update=update)
    elif provider:
        raise SystemExit(f"{config}: only App B configs take @provider[:model]")
    config = base
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


def _config_ids(built: dict) -> dict[str, dict]:
    return {
        c: {
            "pipeline_id": p.pipeline_id,
            "configuration_id": getattr(p, "configuration_id", None),
            "catalog_source_versions": getattr(p, "source_versions", None),
        }
        for c, (p, _, _) in built.items()
    }


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
    unknown = [c for c in configs if split_config(c)[0] not in CONFIG_APPS]
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
    frozen = None
    if split in (Split.CALIBRATION, Split.TEST):
        from foodvision.benchmark.freeze import (
            FreezeViolation,
            RunState,
            check_matches,
            load_spec,
            test_already_run,
        )

        if not args.frozen:
            print(
                f"Refusing: the {split.value} split runs only against a frozen spec "
                "(foodvision freeze, then --frozen benchmarks/frozen/<name>.json)."
            )
            return 2
        try:
            frozen = load_spec(Path(args.frozen))
            check_matches(
                frozen, RunState(_config_ids(built), manifest_sha256(groups), version["dirty"])
            )
        except FreezeViolation as exc:
            print(f"Refusing: does not match the frozen spec: {exc}")
            return 2
        if split is Split.TEST and (done := test_already_run(output, frozen)):
            print(
                f"Refusing: the test split already ran for this frozen spec ({done}). "
                "A change needs a new spec and new confirmatory data."
            )
            return 2
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
        "frozen_spec": frozen["name"] if frozen else None,
        "frozen_spec_sha256": frozen["spec_sha256"] if frozen else None,
        "deadline_ms": {c: b.deadline_s * 1000 for c, (_, b, _) in built.items()},
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


class BatchError(RuntimeError):
    pass


def load_batch(batch_dir: Path):
    """(meta, attempts, refs of the batch's split only, not_run). Saved results only."""
    meta = json.loads((batch_dir / "batch.json").read_text(encoding="utf-8"))
    groups, errors = load_groups(Path(meta["manifest"]))
    if errors or manifest_sha256(groups) != meta["manifest_sha256"]:
        raise BatchError("the manifest changed since the batch ran (or no longer parses)")
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
    selected = [g for g in groups if g.split is Split(meta["split"])]
    return meta, attempts, references(selected), not_run


def _policy():
    provider = ProviderSettings()
    return policy_from_settings(
        provider.persist_provider_outputs, provider.provider_output_policy_version
    )


def run_report(args) -> int:
    try:
        meta, attempts, refs, not_run = load_batch(Path(args.batch))
    except BatchError as exc:
        print(f"Refusing: {exc}.")
        return 1
    report = build_report(
        attempts, refs, list(meta["configs"]), _policy(), Purpose.PERSIST, meta, not_run
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


def run_freeze(args) -> int:
    from foodvision.benchmark.freeze import FROZEN_DIR, FreezeViolation, build_spec

    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    groups, errors = load_groups(Path(args.manifest))
    if errors:
        print("Refusing: the manifest doesn't parse; validate it first.")
        return 1
    target = FROZEN_DIR / f"{args.name}.json"
    if target.exists():
        print(f"Refusing: {target} exists; a frozen spec is never overwritten (pick a new name).")
        return 2
    try:
        spec = build_spec(
            args.name, _config_ids({c: _pipeline(c) for c in configs}), manifest_sha256(groups)
        )
    except FreezeViolation as exc:
        print(f"Refusing: {exc}")
        return 2
    FROZEN_DIR.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"Frozen spec written: {target} (sha256 {spec['spec_sha256'][:12]}). Commit it.")
    return 0


def _save(output: Path, name: str, data: dict) -> bool:
    if not _safe_output(output):
        print(f"Refusing: {output} is a tracked path in the repository.")
        return False
    output.mkdir(parents=True, exist_ok=True)
    (output / name).write_text(json.dumps(data, indent=2, default=list), encoding="utf-8")
    return True


def run_calibrate(args) -> int:
    from foodvision.benchmark.calibration import calibrate, save_calibration
    from foodvision.benchmark.report import UNAVAILABLE
    from foodvision.measurement.storage_policy import DataClass

    try:
        meta, attempts, refs, _ = load_batch(Path(args.batch))
    except BatchError as exc:
        print(f"Refusing: {exc}.")
        return 1
    if meta["split"] != "calibration" or not meta.get("frozen_spec_sha256"):
        print("Refusing: calibration needs a calibration-split batch run against a frozen spec.")
        return 2
    if args.config not in meta["configs"]:
        print(f"Unknown config {args.config}; batch has {sorted(meta['configs'])}.")
        return 2
    mine = [a for a in attempts if a.config == args.config]
    version = f"{args.version}@{meta['frozen_spec_sha256'][:12]}"
    try:
        record = calibrate(mine, refs, version, meta["split"])
    except ValueError as exc:
        print(f"Refusing: {exc}")
        return 2
    record.update(config=args.config, batch_id=meta["batch_id"], frozen_spec=meta["frozen_spec"])
    print(json.dumps(record, indent=2, default=list))
    if not _policy().allows(source_of(args.config), DataClass.DERIVED_METRIC, Purpose.PERSIST):
        print(f"Not saved: {UNAVAILABLE}")
        return 0
    if not _save(Path(args.output), f"calibration-{args.config}.json", record):
        return 2
    if args.save_db:
        from sqlalchemy import create_engine

        url = EvaluatorSettings().evaluator_database_url
        if url is None:
            print("Not saved to the database: EVALUATOR_DATABASE_URL is not set.")
            return 2
        engine = create_engine(url.get_secret_value())
        with engine.begin() as conn:
            save_calibration(conn, record)
        engine.dispose()
        print(f"Calibration version {version} saved to benchmark.calibration_versions.")
    return 0


def run_gates(args) -> int:
    from foodvision.benchmark.gates import evaluate_gates
    from foodvision.benchmark.report import UNAVAILABLE
    from foodvision.measurement.storage_policy import DataClass

    try:
        meta, attempts, refs, not_run = load_batch(Path(args.batch))
    except BatchError as exc:
        print(f"Refusing: {exc}.")
        return 1
    if meta["split"] != "test" or not meta.get("frozen_spec_sha256"):
        print("Refusing: decision gates use the held-out test batch run against a frozen spec.")
        return 2
    configs = list(meta["configs"])
    by_config = {c: [a for a in attempts if a.config == c] for c in configs}
    provider = next((c for c in configs if c.startswith("A_native")), None)
    agent = next((c for c in configs if c.startswith("B_")), None)
    deadline = min(meta["deadline_ms"].values())
    result = evaluate_gates(by_config, refs, deadline, not_run == 0, provider, agent)
    result.update(batch_id=meta["batch_id"], frozen_spec=meta["frozen_spec"])
    print(json.dumps(result, indent=2, default=list))
    # Saved copy: drop gates derived from sources whose rights don't allow saved metrics.
    policy = _policy()
    blocked = [
        c
        for c in configs
        if not policy.allows(source_of(c), DataClass.DERIVED_METRIC, Purpose.PERSIST)
    ]
    saved = json.loads(json.dumps(result, default=list))
    if blocked:
        saved["gates"]["useful_rate_B_minus_A"] = UNAVAILABLE
        saved["gates"]["cost_materiality"]["value"] = {
            c: (UNAVAILABLE if c in blocked else v)
            for c, v in saved["gates"]["cost_materiality"]["value"].items()
        }
        saved["overall"] = f"{UNAVAILABLE} (the overall verdict depends on fatsecret metrics)"
    return 0 if _save(Path(args.output), "gates.json", saved) else 2
