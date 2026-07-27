#!/usr/bin/env python3
"""Refuse a release whose artifacts have not been qualified on a device.

    ./check-qualification.py --target aarch64-linux-android:upstream --tag 20260727

Reads the build receipt produced by ``build.py`` and the device qualification
receipt committed under ``qualification/``, and confirms the second covers the
artifacts the first just produced.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pythonbuild.qualification import QualificationError, verify
from pythonbuild.targets import get_build
from pythonbuild.utils import read_json_object


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="triple or triple:build-option")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--build-dir", default="build", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    build = get_build(args.target)

    pattern = f"*+{args.tag}-{build.artifact_infix}.build.json"
    receipts = sorted(args.build_dir.glob(pattern))
    if len(receipts) != 1:
        print(
            f"expected exactly one build receipt matching {pattern}, "
            f"found {[path.name for path in receipts]}",
            file=sys.stderr,
        )
        return 2
    flavors = read_json_object(receipts[0])["flavors"]
    artifacts = {flavor: record["artifact"] for flavor, record in flavors.items()}

    try:
        result = verify(build, args.tag, artifacts)
    except QualificationError as error:
        print(f"qualification gate: REFUSED\n\n{error}", file=sys.stderr)
        return 1

    device = result["device"]
    interpreter = result["interpreter"]
    print(f"qualification gate: passed for {build.name} at {args.tag}")
    print(f"  receipt   {result['receipt']}")
    print(f"  executed  {result['executed_artifact']}")
    print(f"  covers    {result['artifacts_covered']} artifacts")
    print(
        f"  device    {device['model']} / Android {device['android_release']} "
        f"(API {device['api_level']}, {device['abi']}, {device['context']})"
    )
    print(
        f"  reports   {interpreter['version']}, {interpreter['soabi']}, {interpreter['platform']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
