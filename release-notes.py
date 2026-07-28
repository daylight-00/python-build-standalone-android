#!/usr/bin/env python3
"""Render release notes from the build receipts of a release.

    ./release-notes.py --tag 20260727 --dist-dir incoming

The minimum Android API is stated per build, and a change from the previous
release is called out. Neither API level is chosen by this project, so a floor
can move without anyone deciding to move it — the release notes are where that
has to become visible.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from pythonbuild.catalog import CATALOG_FLAVOR
from pythonbuild.targets import DEFAULT_BUILD_OPTION, load_builds
from pythonbuild.utils import read_json_object

REPOSITORY = "daylight-00/python-build-standalone-android"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--dist-dir", default="dist", type=Path)
    parser.add_argument("--previous", type=Path, help="a previous release's notes metadata")
    parser.add_argument("--repository", default=REPOSITORY)
    parser.add_argument("-o", "--output", type=Path)
    return parser.parse_args(argv)


def render(receipts: list[dict[str, Any]], tag: str, repository: str) -> str:
    builds = load_builds()
    lines: list[str] = []

    lines.append("## Builds")
    lines.append("")
    lines.append("| Build | Minimum Android | Python | Where the minimum comes from |")
    lines.append("| --- | --- | --- | --- |")
    for receipt in receipts:
        option = receipt["build_option"]
        name = "*(default)*" if option == DEFAULT_BUILD_OPTION else f"`{option}`"
        api = receipt["android_api"]["level"]
        policy = receipt["android_api"]["policy"].replace("-", " ")
        version = receipt["flavors"]["full"]["python_version"]
        lines.append(f"| {name} | API {api} | {version} | {policy} |")
    lines.append("")

    lines.append("## Installing with uv")
    lines.append("")
    for receipt in receipts:
        key = f"{receipt['triple']}:{receipt['build_option']}"
        build = builds.get(key)
        if build is None:
            continue
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
    for receipt in receipts:
        for flavor in ("full", "install_only", CATALOG_FLAVOR):
            artifact = receipt["flavors"][flavor]["artifact"]
            size = f"{artifact['size_bytes'] / 1_048_576:.1f} MiB"
            lines.append(f"| `{artifact['filename']}` | {size} | `{artifact['sha256']}` |")
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
        print(f"no build receipts for {args.tag} under {args.dist_dir}", file=sys.stderr)
        return 2
    receipts = [read_json_object(path) for path in paths]

    notes = render(receipts, args.tag, args.repository)
    if args.output:
        args.output.write_text(notes, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(notes, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
