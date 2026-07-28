#!/usr/bin/env python3
"""Build the archive family for one Android build.

    ./build.py --target aarch64-linux-android:upstream --tag 20260727
    ./build.py --target aarch64-linux-android --tag 20260727

A build is named ``triple`` or ``triple:build-option``. The flagship build
option is ``default`` and is selected by naming the triple alone.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from pythonbuild.assemble import (
    BuildContext,
    assemble_full,
    derive_install_only,
    derive_stripped,
    prepare_upstream_prefix,
    stripped_shares_non_elf_bytes,
    verify_projection,
)
from pythonbuild.cpython_source import prepare_source_prefix
from pythonbuild.downloads import DEFAULT_CACHE, acquire
from pythonbuild.targets import get_build, load_builds
from pythonbuild.toolchain import resolve_toolchain
from pythonbuild.utils import write_json


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target", required=True, help="triple or triple:build-option from ci-targets.yaml"
    )
    parser.add_argument("--tag", required=True, help="release tag, e.g. 20260727")
    parser.add_argument("--output-dir", default="dist", type=Path)
    parser.add_argument("--cache", default=DEFAULT_CACHE, type=Path)
    parser.add_argument(
        "--build-dir",
        default=Path("build"),
        type=Path,
        help="where source builds happen; kept between runs so the build interpreter is reused",
    )
    parser.add_argument(
        "--skip-verify", action="store_true", help="skip the projection cross-checks"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    # Anything created without an explicit mode — every mkdir, every JSON record
    # — otherwise takes the caller's umask, and lands in the archive. Two hosts
    # with different umasks would produce different bytes from the same input.
    os.umask(0o022)

    args = parse_args(argv)
    try:
        build = get_build(args.target)
    except KeyError as error:
        print(error, file=sys.stderr)
        print(f"known builds: {', '.join(sorted(load_builds()))}", file=sys.stderr)
        return 2

    context = BuildContext(
        build=build,
        toolchain=resolve_toolchain(build, args.cache),
        tag=args.tag,
        output_dir=args.output_dir.resolve(),
    )

    print(f"==> {build.name}, minimum Android API {build.android_api.level}", flush=True)

    if build.from_upstream_prebuilt:
        with tempfile.TemporaryDirectory(prefix="pbsa-input-") as tmp:
            print("==> acquiring the pinned input", flush=True)
            upstream = acquire(context.lock["archive"], args.cache, what="official Android package")
            source = prepare_upstream_prefix(context, upstream, Path(tmp))
            print("==> assembling full", flush=True)
            full = assemble_full(context, source)
    else:
        print("==> building the dependencies and CPython from source", flush=True)
        source = prepare_source_prefix(
            build=build,
            toolchain=context.toolchain,
            workspace=args.build_dir.resolve() / build.artifact_infix,
            cache=args.cache,
        )
        print("==> assembling full", flush=True)
        full = assemble_full(context, source)
    full_archive = context.output_dir / full["artifact"]["filename"]

    print("==> deriving install_only", flush=True)
    install_only = derive_install_only(context, full_archive)
    install_only_archive = context.output_dir / install_only["artifact"]["filename"]

    print("==> deriving install_only_stripped", flush=True)
    stripped = derive_stripped(context, install_only_archive)
    stripped_archive = context.output_dir / stripped["artifact"]["filename"]

    checks: dict[str, object] = {}
    if not args.skip_verify:
        print("==> verifying install_only is an exact projection of full", flush=True)
        checks["projection"] = verify_projection(full_archive, install_only_archive)
        print("==> verifying the stripped flavor only changed ELF payloads", flush=True)
        checks["stripped"] = stripped_shares_non_elf_bytes(install_only_archive, stripped_archive)

    receipt = {
        "schema_version": 1,
        "triple": build.triple,
        "build_option": build.build_option,
        "android_api": {
            "level": build.android_api.level,
            "policy": build.android_api.policy,
        },
        "tag": args.tag,
        "toolchain": context.toolchain.identity(),
        "flavors": {
            "full": full,
            "install_only": install_only,
            "install_only_stripped": stripped,
        },
        "checks": checks,
    }
    receipt_path = context.output_dir / f"{context.stem(full['python_version'])}.build.json"
    write_json(receipt_path, receipt)

    sums = context.output_dir / "SHA256SUMS"
    lines = [
        f"{record['artifact']['sha256']}  {record['artifact']['filename']}"
        for record in (full, install_only, stripped)
    ]
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print()
    for record in (full, install_only, stripped):
        artifact = record["artifact"]
        print(f"{artifact['sha256']}  {artifact['size_bytes']:>10}  {artifact['filename']}")
    print(f"\nreceipt: {receipt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
