#!/usr/bin/env python3
"""Render release notes from the build receipts of a release.

    ./release-notes.py --tag 20260727 --dist-dir incoming

The minimum Android API is stated per build, and a change from the previous
release is called out. Neither API level is chosen by this project, so a floor
can move without anyone deciding to move it — the release notes are where that
has to become visible.

The previous floors come from the qualification receipts committed for the
earlier tag, because the release gate has already held each of those to the
floor its build declared.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from pythonbuild.catalog import CATALOG_FLAVOR
from pythonbuild.qualification import previous_qualified_tag, shipped_api_levels
from pythonbuild.targets import DEFAULT_BUILD_OPTION, Build, load_builds
from pythonbuild.utils import read_json_object

REPOSITORY = "daylight-00/python-build-standalone-android"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--dist-dir", default="dist", type=Path)
    parser.add_argument(
        "--previous-tag",
        help="tag to compare API floors against; defaults to the newest earlier tag "
        "that has a committed qualification receipt",
    )
    parser.add_argument("--repository", default=REPOSITORY)
    parser.add_argument("-o", "--output", type=Path)
    return parser.parse_args(argv)


def _resolve(receipt: dict[str, Any], builds: dict[str, Build]) -> Build:
    """The ci-targets.yaml entry a receipt describes.

    Matched on the fields rather than on a reconstructed key: the key form drops
    ``:default``, and building it here silently left the flagship out of the one
    section a reader follows to install anything.
    """
    build = next(
        (
            candidate
            for candidate in builds.values()
            if candidate.triple == receipt["triple"]
            and candidate.build_option == receipt["build_option"]
        ),
        None,
    )
    if build is None:
        raise RuntimeError(
            f"{receipt['triple']}:{receipt['build_option']} has a receipt but no "
            f"entry in ci-targets.yaml"
        )
    return build


def _floor_callout(previous: str, moved: list[tuple[str, int, int]]) -> list[str]:
    """A floor that moved without anyone deciding to move it has to be unmissable."""
    detail = "; ".join(
        f"{label} moved from API {before} to API {after}"
        for label, before, after in moved
    )
    return [
        "> [!IMPORTANT]",
        f"> **The minimum Android API changed since `{previous}`:** {detail}.",
        "> Neither floor is chosen by this project — one is inherited from the official",
        "> package and the other follows CPython's own feature detection — so a device",
        "> that ran the previous release may not be able to run this one.",
        "",
    ]


def _floors_that_moved(
    pairs: list[tuple[dict[str, Any], Build]], previous: str
) -> list[tuple[str, int, int]]:
    """Compare each build's floor against the one it was qualified at previously.

    A build with no receipt under the earlier tag was not in that release, so it
    has no previous floor and nothing to report.
    """
    before = shipped_api_levels(previous)
    return [
        (
            "the flagship build"
            if build.build_option == DEFAULT_BUILD_OPTION
            else f"the `{build.build_option}` build",
            before[build.artifact_infix],
            receipt["android_api"]["level"],
        )
        for receipt, build in pairs
        if build.artifact_infix in before
        and before[build.artifact_infix] != receipt["android_api"]["level"]
    ]


def render(
    receipts: list[dict[str, Any]],
    tag: str,
    repository: str,
    previous_tag: str | None = None,
) -> str:
    builds = load_builds()
    # Ordered by build, flagship first, rather than by whatever order the receipts
    # were found in: they sort one way when a release collects them per artifact
    # directory and another way when they sit in one, and the notes should not.
    pairs = [
        (receipt, _resolve(receipt, builds))
        for receipt in sorted(
            receipts,
            key=lambda receipt: (
                receipt["build_option"] != DEFAULT_BUILD_OPTION,
                receipt["build_option"],
            ),
        )
    ]
    lines: list[str] = []

    # Above everything else, because a reader who takes in nothing but the first
    # paragraph still has to learn that their device may have dropped out.
    if previous_tag is None:
        previous_tag = previous_qualified_tag(tag)
    if previous_tag:
        moved = _floors_that_moved(pairs, previous_tag)
        if moved:
            lines.extend(_floor_callout(previous_tag, moved))

    lines.append("## Builds")
    lines.append("")
    lines.append("| Build | Minimum Android | Python | Where the minimum comes from |")
    lines.append("| --- | --- | --- | --- |")
    for receipt, _ in pairs:
        option = receipt["build_option"]
        name = "*(default)*" if option == DEFAULT_BUILD_OPTION else f"`{option}`"
        api = receipt["android_api"]["level"]
        # Verbatim, in backticks: it is the identifier ci-targets.yaml states, and
        # de-hyphenating it produced prose that was neither the identifier nor a
        # sentence. What it means is in the documentation.
        policy = f"`{receipt['android_api']['policy']}`"
        version = receipt["flavors"]["full"]["python_version"]
        lines.append(f"| {name} | API {api} | {version} | {policy} |")
    lines.append("")

    lines.append("## Installing with uv")
    lines.append("")
    for receipt, build in pairs:
        label = (
            "the flagship"
            if build.build_option == DEFAULT_BUILD_OPTION
            else "the baseline"
        )
        lines.append(f"`{build.name}`, {label}:")
        lines.append("")
        lines.append(
            f"```console\n"
            f"$ uv python install cpython-{receipt['flavors']['full']['python_version']}"
            f"-linux-{build.arch}-none \\\n"
            f"    --python-downloads-json-url \\\n"
            f"    https://raw.githubusercontent.com/{repository}/latest-release/"
            f"{build.uv_catalog}\n"
            f"```"
        )
        lines.append("")

    lines.append("## Artifacts")
    lines.append("")
    lines.append("| File | Size | SHA-256 |")
    lines.append("| --- | --- | --- |")
    for receipt, _ in pairs:
        for flavor in ("full", "install_only", CATALOG_FLAVOR):
            artifact = receipt["flavors"][flavor]["artifact"]
            size = f"{artifact['size_bytes'] / 1_048_576:.1f} MiB"
            lines.append(
                f"| `{artifact['filename']}` | {size} | `{artifact['sha256']}` |"
            )
    lines.append("")

    lines.append("## Verification")
    lines.append("")
    lines.append("```console")
    lines.append("$ sha256sum -c SHA256SUMS --ignore-missing")
    lines.append(f"$ gh attestation verify <archive> --repo {repository}")
    lines.append("```")
    lines.append("")
    lines.append(
        "Every archive was built twice and compared byte for byte, and each build was run "
        "on a physical device before this release was cut."
    )

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = sorted(args.dist_dir.rglob(f"*+{args.tag}-*.build.json"))
    if not paths:
        print(
            f"no build receipts for {args.tag} under {args.dist_dir}", file=sys.stderr
        )
        return 2
    receipts = [read_json_object(path) for path in paths]

    notes = render(receipts, args.tag, args.repository, args.previous_tag)
    if args.output:
        args.output.write_text(notes, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(notes, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
