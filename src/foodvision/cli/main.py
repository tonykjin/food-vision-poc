"""`foodvision` command-line entry point.

Implemented: `doctor`, `import-usda`, `import-usda-api`, `catalog-report`. Other plan
§6/§14 commands (validate-manifest, benchmark, report, calibrate) arrive with their issues.
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

    args = parser.parse_args(argv)
    if args.command == "doctor":
        from foodvision.cli.doctor import run_doctor

        return run_doctor(AppKind(args.app), env_file=args.env_file)
    if args.command == "import-usda":
        from foodvision.catalog.commands import import_usda

        return import_usda(args.dataset, args.version, args.subset)
    if args.command == "import-usda-api":
        from foodvision.catalog.commands import import_usda_api

        return import_usda_api(args.fdc_ids, args.subset)
    if args.command == "catalog-report":
        from foodvision.catalog.commands import catalog_report

        return catalog_report(args.probes)
    return 2


if __name__ == "__main__":
    sys.exit(main())
