"""`foodvision` command-line entry point.

Implemented: `doctor`, `import-usda`, `import-usda-api`, `catalog-report`,
`smoke-fatsecret`, `smoke-vision`, `validate-manifest`, `assign-splits`, `load-manifest`,
`benchmark`, `report`, `freeze`, `calibrate`, `gates`.
"""

import argparse
import sys

from foodvision.config import AppKind


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="foodvision")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Boolean-only configuration checks (no network)")
    doctor.add_argument("--app", required=True, choices=[k.value for k in AppKind])
    doctor.add_argument("--env-file", default=None, help="Override the app's env file path")

    usda = sub.add_parser("import-usda", help="Import a documented FDC JSON download")
    usda.add_argument("--dataset", required=True, help="Path to the official FDC JSON .zip")
    usda.add_argument("--version", required=True, help="Documented source_version")
    usda.add_argument("--subset", default=None, help="Subset manifest (default catalog/...)")

    api = sub.add_parser("import-usda-api", help="Fetch documented Branded FDC IDs via the API")
    api.add_argument("--fdc-ids", default=None, help="Comma-separated IDs (default: manifest)")
    api.add_argument("--subset", default=None)

    report = sub.add_parser("catalog-report", help="Catalog counts, gaps and probe searches")
    report.add_argument("--probes", default=None)

    smoke = sub.add_parser(
        "smoke-fatsecret", help="Opt-in live check: one image, <= 1 token + 1 image request"
    )
    smoke.add_argument("--image", required=True, help="Path to an owned test image")
    smoke.add_argument("--confirm-one-request", action="store_true")

    vision = sub.add_parser("smoke-vision", help="Opt-in live check: one image, one model request")
    vision.add_argument("--image", required=True, help="Path to an owned test image")
    vision.add_argument("--confirm-one-request", action="store_true")

    for name, text in (
        ("validate-manifest", "Validate a reference manifest; show collection progress"),
        ("assign-splits", "Assign family-safe splits to groups that have none"),
        ("load-manifest", "Load reviewed groups into the evaluator-only benchmark schema"),
    ):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("--manifest", required=True, help="Group JSON directory or .jsonl file")
        if name != "assign-splits":
            cmd.add_argument("--data-dir", default=None, help="Private benchmark data directory")
        if name == "assign-splits":
            cmd.add_argument("--seed", default=None)
            cmd.add_argument("--dry-run", action="store_true")
        if name == "load-manifest":
            cmd.add_argument("--reference-version", required=True)

    bench = sub.add_parser("benchmark", help="Paired benchmark runs over one manifest split")
    bench.add_argument("--manifest", required=True)
    bench.add_argument("--split", required=True, choices=["development", "calibration", "test"])
    bench.add_argument("--configs", required=True, help="e.g. A_native,B_grounded")
    bench.add_argument("--repeats", type=int, default=3)
    bench.add_argument("--concurrency", type=int, default=1)
    bench.add_argument("--output", required=True, help="Batch directory parent (e.g. work/)")
    bench.add_argument("--data-dir", default=None)
    bench.add_argument("--max-total-cost-usd", type=float, default=None)
    bench.add_argument("--max-scans", type=int, default=None)
    bench.add_argument("--confirm-paid-run", action="store_true")
    bench.add_argument("--allow-test-split", action="store_true")
    bench.add_argument("--frozen", default=None, help="Frozen spec (required: calibration/test)")

    freeze = sub.add_parser("freeze", help="Record the frozen evaluation spec (commit it)")
    freeze.add_argument("--manifest", required=True)
    freeze.add_argument("--configs", required=True)
    freeze.add_argument("--name", required=True, help="e.g. pilot-v1-freeze-1")

    cal = sub.add_parser("calibrate", help="Bucket pass rates on a calibration-split batch")
    cal.add_argument("--batch", required=True)
    cal.add_argument("--config", required=True, help="e.g. B_grounded")
    cal.add_argument("--version", required=True, help="Calibration version name")
    cal.add_argument("--output", required=True)
    cal.add_argument("--save-db", action="store_true", help="Also write calibration_versions")

    gates = sub.add_parser("gates", help="Go/no-go evidence from the held-out test batch")
    gates.add_argument("--batch", required=True)
    gates.add_argument("--output", required=True)

    rep = sub.add_parser("report", help="Rebuild the saved report of a benchmark batch")
    rep.add_argument("--batch", required=True, help="Batch directory written by benchmark")
    rep.add_argument("--output", required=True)

    args = parser.parse_args(argv)
    if args.command in ("benchmark", "report", "freeze", "calibrate", "gates"):
        from foodvision.cli import benchmark_run

        return {
            "benchmark": benchmark_run.run_benchmark,
            "report": benchmark_run.run_report,
            "freeze": benchmark_run.run_freeze,
            "calibrate": benchmark_run.run_calibrate,
            "gates": benchmark_run.run_gates,
        }[args.command](args)
    if args.command in ("validate-manifest", "assign-splits", "load-manifest"):
        from foodvision.cli import benchmark

        return benchmark.run(args)
    if args.command == "doctor":
        from foodvision.cli.doctor import run_doctor

        return run_doctor(AppKind(args.app), env_file=args.env_file)
    if args.command == "import-usda":
        from foodvision.catalog.commands import import_usda

        return import_usda(args.dataset, args.version, args.subset)
    if args.command == "import-usda-api":
        from foodvision.catalog.commands import import_usda_api

        return import_usda_api(args.fdc_ids, args.subset)
    if args.command == "smoke-fatsecret":
        from foodvision.cli.smoke import smoke_fatsecret

        return smoke_fatsecret(args.image, args.confirm_one_request)
    if args.command == "smoke-vision":
        from foodvision.cli.smoke import smoke_vision

        return smoke_vision(args.image, args.confirm_one_request)
    if args.command == "catalog-report":
        from foodvision.catalog.commands import catalog_report

        return catalog_report(args.probes)
    return 2


if __name__ == "__main__":
    sys.exit(main())
