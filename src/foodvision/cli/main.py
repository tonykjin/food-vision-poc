"""`foodvision` command-line entry point.

Implemented: `doctor`. Other plan §6/§14 commands (import-usda, validate-manifest,
benchmark, report, calibrate) arrive with their issues; see README.
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

    args = parser.parse_args(argv)
    if args.command == "doctor":
        from foodvision.cli.doctor import run_doctor

        return run_doctor(AppKind(args.app), env_file=args.env_file)
    return 2


if __name__ == "__main__":
    sys.exit(main())
