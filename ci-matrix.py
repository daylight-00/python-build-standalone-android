#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""Emit the CI build matrix from ``ci-targets.yaml``.

    ./ci-matrix.py

GitHub Actions cannot read the target table, so each workflow used to carry its
own copy of the list of builds — two copies, which is one more than the number
of places that can be right. Adding ``extended`` meant editing both by hand.

Upstream generates its matrix from the same file and declares its dependencies
inline so the script runs without the project installed; the matrix job should
not need a full sync to answer one question. This does the same, and still reads
the table through ``pythonbuild.targets`` rather than parsing the YAML again —
the script sits at the repository root, so the package is importable without
being installed, and the rule that the flagship carries no marker in an artifact
name stays stated once.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from pythonbuild.targets import load_builds


def matrix() -> dict[str, Any]:
    return {
        "include": [
            {
                "build": build.name,
                # An artifact name cannot contain the colon that separates a
                # triple from its build option, so the upload name is the infix.
                "artifact": build.artifact_infix,
            }
            for _, build in sorted(load_builds().items())
        ]
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pretty", action="store_true", help="indent the output for reading by eye"
    )
    args = parser.parse_args(argv)
    print(json.dumps(matrix(), indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
