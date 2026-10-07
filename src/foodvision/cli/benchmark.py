"""Evaluator commands: validate-manifest, assign-splits, load-manifest (POC-12).

Settings come from `.env.evaluator.local` (EVALUATOR_DATABASE_URL, BENCHMARK_DATA_DIR) or the
shell, never from an app's env file. Output names groups and problems, never secret values.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from foodvision.benchmark.manifest import Group, ManifestFormatError, load_groups
from foodvision.benchmark.validate import (
    Report,
    check_groups,
    check_location,
    manifest_sha256,
    progress,
)
from foodvision.config import EvaluatorSettings


def _validate(manifest: Path, data_dir: Path | None) -> tuple[list[Group], Report]:
    groups, parse_errors = load_groups(manifest)
    report = Report(errors=parse_errors)
    check_location(manifest, groups, report)
    check_groups(groups, data_dir, report)
    if data_dir is None:
        report.warnings.append("photo files not checked: pass --data-dir or set BENCHMARK_DATA_DIR")
    progress(groups, report)
    return groups, report


def _print(report: Report, groups: list[Group]) -> None:
    print(f"Manifest: {len(groups)} groups, sha256 {manifest_sha256(groups)[:12]}")
    for title, lines in (
        ("Errors", report.errors),
        ("Human work / warnings", report.warnings),
        ("Progress", report.progress),
    ):
        print(f"\n{title} ({len(lines)})" if title != "Progress" else f"\n{title}")
        for line in lines:
            print(f"  {line}")
    print("\nResult: " + ("valid" if report.ok else "INVALID (errors above)"))


def _assign(manifest: Path, seed: str | None, dry_run: bool) -> int:
    from foodvision.benchmark.splits import DEFAULT_SEED, assign_splits

    if not manifest.is_dir():
        print("assign-splits edits group files: pass the group JSON directory.")
        return 2
    groups, errors = load_groups(manifest)
    if errors:
        print("Refusing: fix these parse errors first:")
        for e in errors:
            print(f"  {e}")
        return 1
    try:
        assignments = assign_splits(groups, seed or DEFAULT_SEED)
    except ValueError as exc:
        print(f"Refusing: {exc}")
        return 1
    files = {}
    for file in manifest.glob("*.json"):
        files[json.loads(file.read_text(encoding="utf-8"))["group_id"]] = file
    for group_id, split in sorted(assignments.items()):
        print(f"  {group_id}: {split.value}")
        if not dry_run:
            data = json.loads(files[group_id].read_text(encoding="utf-8"))
            data["split"] = split.value
            files[group_id].write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    verb = "Would assign" if dry_run else "Assigned"
    print(f"{verb} {len(assignments)} group(s); existing splits unchanged.")
    return 0


def _load(manifest: Path, data_dir: Path | None, version: str, settings) -> int:
    from sqlalchemy import create_engine

    from foodvision.benchmark.load import EvaluatorAuthorizationError
    from foodvision.benchmark.load import load_groups as load_db
    from foodvision.data.object_store import LocalObjectStore

    if data_dir is None or settings.evaluator_database_url is None:
        print("Refusing: needs BENCHMARK_DATA_DIR and EVALUATOR_DATABASE_URL (evaluator login).")
        return 2
    groups, report = _validate(manifest, data_dir)
    if not report.ok:
        _print(report, groups)
        print("Refusing to load an invalid manifest.")
        return 1
    reference_version = f"{version}@{manifest_sha256(groups)[:12]}"
    engine = create_engine(settings.evaluator_database_url.get_secret_value())
    try:
        with engine.begin() as conn:
            summary = load_db(
                conn,
                LocalObjectStore(data_dir / "objects"),
                groups,
                data_dir,
                reference_version,
                datetime.now(UTC),
            )
    except EvaluatorAuthorizationError as exc:
        print(f"Refusing: {exc}")
        return 1
    finally:
        engine.dispose()
    print(
        f"Loaded {summary.groups} group(s), {summary.samples} sample(s), "
        f"{summary.new_images} new image(s) as reference_version {reference_version}."
    )
    if summary.skipped:
        print(f"Skipped (draft or no split): {', '.join(summary.skipped)}")
    return 0


def run(args) -> int:
    settings = EvaluatorSettings()
    manifest = Path(args.manifest)
    data_dir_arg = getattr(args, "data_dir", None)
    data_dir = Path(data_dir_arg) if data_dir_arg else settings.benchmark_data_dir
    try:
        if args.command == "assign-splits":
            return _assign(manifest, args.seed, args.dry_run)
        if args.command == "load-manifest":
            return _load(manifest, data_dir, args.reference_version, settings)
        groups, report = _validate(manifest, data_dir)
    except (ManifestFormatError, FileNotFoundError) as exc:
        print(f"Cannot read manifest: {exc}")
        return 2
    _print(report, groups)
    return 0 if report.ok else 1
