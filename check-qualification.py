#!/usr/bin/env python3
"""Refuse a release whose artifacts have not been qualified on a device.

    ./check-qualification.py --target aarch64-linux-android:upstream --tag 20260727
    ./check-qualification.py --target … --tag … --allow-waiver

Reads the build receipt produced by ``build.py`` and the device qualification
receipt committed under ``qualification/``, and confirms the second covers the
artifacts the first just produced.

``--allow-waiver`` is for an unattended release. It does not weaken what a
receipt means: when none covers these bytes, it asks instead whether anything
but the pinned CPython input has changed since the last build a device did run,
and permits the release only if nothing has. See ``pythonbuild/waiver.py``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pythonbuild import waiver
from pythonbuild.qualification import (
    QualificationError,
    previous_qualified_tag,
    shipped_api_levels,
    verify,
)
from pythonbuild.targets import Build, get_build
from pythonbuild.utils import read_json_object, run, write_json


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="triple or triple:build-option")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--dist-dir", default="dist", type=Path)
    parser.add_argument(
        "--allow-waiver",
        action="store_true",
        help="when no receipt covers these bytes, permit the release if nothing "
        "but the pinned CPython input has changed since the last qualified tag",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="where to record the verdict, so a release can tell a qualified "
        "build from a waived one without reading prose",
    )
    return parser.parse_args(argv)


def _record(
    report: Path | None,
    build: Build,
    tag: str,
    *,
    qualified: bool,
    detail: dict[str, object] | None = None,
) -> None:
    if report is None:
        return
    write_json(
        report,
        {
            "schema_version": 1,
            "build": build.name,
            "tag": tag,
            "device_qualified": qualified,
            **(detail or {}),
        },
    )


def changed_since(tag: str) -> list[str]:
    """Every tracked path that differs between ``tag`` and the working tree.

    git is the record of what this project changed; nothing has to be committed
    alongside a receipt for the comparison to be possible.
    """
    result = run(["git", "diff", "--name-only", f"{tag}..HEAD"])
    if result.returncode:
        raise QualificationError(
            f"cannot compare against {tag}: {result.stderr.strip()}\n"
            f"The release checkout needs the tag and its history — fetch-depth: 0."
        )
    return [line for line in result.stdout.splitlines() if line]


def consider_waiver(
    build: Build, tag: str, refusal: QualificationError, report: Path | None
) -> int:
    """Permit an unattended release only when the change is upstream's alone."""
    previous = previous_qualified_tag(tag)
    if previous is None:
        print(
            f"qualification gate: REFUSED\n\n{refusal}\n\n"
            f"No earlier qualified tag to compare against, so there is nothing a "
            f"waiver could rest on.",
            file=sys.stderr,
        )
        return 1

    levels = shipped_api_levels(previous)
    if build.artifact_infix not in levels:
        print(
            f"qualification gate: REFUSED\n\n{refusal}\n\n"
            f"{previous} has no passing receipt for {build.name}, so this build has "
            f"never run on a device.",
            file=sys.stderr,
        )
        return 1

    assessment = waiver.assess(
        previous_tag=previous,
        previous_api_level=levels[build.artifact_infix],
        declared_api_level=build.android_api.level,
        changed_paths=changed_since(previous),
    )
    if not assessment.granted:
        print(
            f"qualification gate: REFUSED\n\n{refusal}\n\n"
            f"A waiver was allowed but does not apply: {assessment.reason()}.\n"
            f"Qualify this build on a device and commit the receipt.",
            file=sys.stderr,
        )
        return 1

    print(f"qualification gate: WAIVED for {build.name} at {tag}")
    print("  no receipt covers these bytes; this release is not device-qualified")
    print(f"  standing on  {assessment.reason()}")
    print(f"  changed      {', '.join(assessment.waived) or 'nothing'}")
    print(f"  floor        API {assessment.declared_api_level}, unchanged")
    _record(
        report,
        build,
        tag,
        qualified=False,
        detail={
            "waiver": {
                "previous_tag": assessment.previous_tag,
                "reason": assessment.reason(),
                "changed": list(assessment.waived),
            }
        },
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    build = get_build(args.target)

    pattern = f"*+{args.tag}-{build.artifact_infix}.build.json"
    receipts = sorted(args.dist_dir.glob(pattern))
    if len(receipts) != 1:
        print(f"expected exactly one build receipt matching {pattern}", file=sys.stderr)
        present = sorted(path.name for path in args.dist_dir.glob("*.build.json"))
        if present:
            print(f"\n{args.dist_dir} holds instead:", file=sys.stderr)
            for name in present:
                print(f"  {name}", file=sys.stderr)
            print(
                f"\nBuild this tag first:\n  ./build.py --target {args.target} --tag {args.tag}",
                file=sys.stderr,
            )
        else:
            print(
                f"\n{args.dist_dir} holds no build receipts. Build first:\n"
                f"  ./build.py --target {args.target} --tag {args.tag}",
                file=sys.stderr,
            )
        return 2
    flavors = read_json_object(receipts[0])["flavors"]
    artifacts = {flavor: record["artifact"] for flavor, record in flavors.items()}

    try:
        result = verify(build, args.tag, artifacts)
    except QualificationError as error:
        if not args.allow_waiver:
            print(f"qualification gate: REFUSED\n\n{error}", file=sys.stderr)
            return 1
        return consider_waiver(build, args.tag, error, args.report)

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
    _record(
        args.report,
        build,
        args.tag,
        qualified=True,
        detail={"receipt": result["receipt"]},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
