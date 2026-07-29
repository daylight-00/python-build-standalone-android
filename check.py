#!/usr/bin/env -S uv run --group check
"""Run every static check this repository has, or fix what can be fixed.

    ./check.py         # lint, formatting, and types
    ./check.py --fix   # apply what ruff can apply, then report the rest

The tools take their scope from their own configuration — ruff from
``ruff.toml``, mypy from ``mypy.ini`` — so this script names no paths and
nothing has to be kept in step with it.
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def run_command(command: list[str]) -> int:
    print("$ " + " ".join(command), flush=True)
    returncode = subprocess.run(
        command, stdout=sys.stdout, stderr=sys.stderr
    ).returncode
    print()
    return returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check code.")
    parser.add_argument(
        "--fix", action="store_true", help="apply the fixes ruff can apply"
    )
    args = parser.parse_args(argv)

    check_args = ["--fix"] if args.fix else []
    format_args = [] if args.fix else ["--check"]

    failures = (
        run_command(["ruff", "check", *check_args])
        + run_command(["ruff", "format", *format_args])
        + run_command(["mypy"])
        # `-t .` so the repository root, not tests/, is the import root and the
        # tests can import pythonbuild.
        + run_command(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."]
        )
    )

    if failures:
        print("Checks failed!")
        return 1
    print("Checks passed!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
