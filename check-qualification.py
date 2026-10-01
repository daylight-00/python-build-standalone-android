#!/usr/bin/env python3
"""Refuse a release whose artifacts have not been qualified on a device.

    ./check-qualification.py --target aarch64-linux-android:upstream --tag 20260727
    ./check-qualification.py --target … --tag … --allow-waiver

Reads the build receipt produced by ``build.py`` and the device qualification
receipt committed under ``qualification/``, and confirms the second covers the
artifacts the first just produced.

``--allow-waiver`` is for an unattended release. It does not weaken what a
receipt means: when none covers these bytes, the release is permitted anyway and
the verdict records why it is not qualified — whether nothing but the pinned
CPython input changed since the last build a device did run, something of this
project's own did, or no device ever ran this build. See ``pythonbuild/waiver.py``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pythonbuild import waiver
from pythonbuild.qualification import (
    QUALIFICATION_ROOT,
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
        help="when no receipt covers these bytes, permit the release anyway and "
        "record what it stands on instead",
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


def _git_tag_exists(tag: str) -> bool:
    """Whether ``tag`` names a real Git tag in the release checkout."""
    result = run(["git", "show-ref", "--verify", "--quiet", f"refs/tags/{tag}"])
    return result.returncode == 0


def previous_released_qualified_tag(
    tag: str, root: Path = QUALIFICATION_ROOT
) -> str | None:
    """Newest earlier qualified candidate that was actually released as a Git tag.

    Qualification receipts may intentionally exist for candidates that were never
    released. Those receipts remain useful evidence, but there is no commit range
    to diff from unless the candidate also has a Git tag.
    """
    previous = previous_qualified_tag(tag, root=root)
    while previous is not None and not _git_tag_exists(previous):
        previous = previous_qualified_tag(previous, root=root)
    return previous


def consider_waiver(
    build: Build, tag: str, refusal: QualificationError, report: Path | None
) -> int:
    """Let a release with no receipt of its own go out, and record what it stands on.

    Nothing here refuses: an unattended release that waited for a device would
    not be unattended. What varies is the claim. Only a change that is upstream's
    alone earns the waiver proper; anything else is published all the same, as a
    prerelease whose notes say which footing it is on.
    """
    previous = previous_released_qualified_tag(tag)
    levels = shipped_api_levels(previous) if previous else {}
    changed: list[str] = []
    floor: int | None = None

    if previous is None:
        basis = waiver.NEVER_RUN
        reason = "no earlier release was ever qualified on a device"
    elif build.artifact_infix not in levels:
        basis = waiver.NEVER_RUN
        reason = (
            f"{previous} has no passing receipt for {build.name}, so this build "
            f"has never run on a device"
        )
    else:
        assessment = waiver.assess(
            previous_tag=previous,
            previous_api_level=levels[build.artifact_infix],
            declared_api_level=build.android_api.level,
            changed_paths=changed_since(previous),
        )
        basis = assessment.basis
        reason = assessment.reason()
        changed = list(assessment.waived)
        if assessment.granted:
            floor = assessment.declared_api_level

    print(f"qualification gate: NOT QUALIFIED for {build.name} at {tag}")
    print(f"  receipt   {str(refusal).splitlines()[0]}")
    print("  this release is not device-qualified and goes out as a prerelease")
    print(f"  basis     {basis}: {reason}")
    if floor is not None:
        print(f"  changed   {', '.join(changed) or 'nothing'}")
        print(f"  floor     API {floor}, unchanged")
    _record(
        report,
        build,
        tag,
        qualified=False,
        detail={
            "waiver": {
                "basis": basis,
                "previous_tag": previous,
                "reason": reason,
                "changed": changed,
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
