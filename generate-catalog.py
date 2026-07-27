#!/usr/bin/env python3
"""Generate the uv download-metadata catalog for a built target.

    ./generate-catalog.py --target aarch64-linux-android:upstream --tag 20260727

Reads the build receipt produced by ``build.py`` and writes the catalog uv
consumes through ``--python-downloads-json-url``. Each build option gets its own
catalog, because uv's key format cannot tell two Android builds apart.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pythonbuild.catalog import CATALOG_FLAVOR, build_catalog, latest_release, merge_catalog
from pythonbuild.targets import get_build
from pythonbuild.utils import read_json_object, write_json

DEFAULT_REPOSITORY = "daylight-00/python-build-standalone-android"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="triple or triple:build-option")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--build-dir", default="build", type=Path)
    parser.add_argument("--output-dir", default="dist", type=Path)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument(
        "--merge-into",
        type=Path,
        help="existing catalog to merge this release into, keeping older versions",
    )
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
    receipt = read_json_object(receipts[0])
    artifact = receipt["flavors"][CATALOG_FLAVOR]["artifact"]
    python_version = receipt["flavors"]["full"]["python_version"]

    catalog = build_catalog(
        build,
        python_version=python_version,
        tag=args.tag,
        filename=artifact["filename"],
        sha256=artifact["sha256"],
        repository=args.repository,
    )
    if args.merge_into and args.merge_into.is_file():
        catalog = merge_catalog(read_json_object(args.merge_into), catalog)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = args.output_dir / build.uv_catalog
    write_json(catalog_path, catalog)
    write_json(args.output_dir / "latest-release.json", latest_release(args.repository, args.tag))

    print(f"wrote {catalog_path} with {len(catalog)} entries")
    for key in catalog:
        print(f"  {key}  (minimum Android API {build.android_api.level})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
