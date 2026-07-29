#!/usr/bin/env python3
"""Hold a finished archive to the distribution contract.

    ./validate-distribution.py dist/cpython-3.14.6+20260729-*-full.tar.zst
    ./validate-distribution.py cpython-*-install_only.tar.gz

Every other guard in this repository runs while a distribution is being built,
which means a published archive cannot be re-examined without rebuilding it.
This takes the bytes and asks the questions again: does PYTHON.json satisfy the
schema upstream's own reader enforces, are the extension modules the ones
CPython says it built, are the licence texts there, and does anything name a
path it should not.

Upstream validates its distributions the same way, from the archive rather than
from the build tree.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from pythonbuild.archive import extract_tar_zst, safe_extract_tar, tree_manifest
from pythonbuild.conformance import check_python_json
from pythonbuild.modules import check_shared_modules, expectations, shipped_shared

LICENSE_MANIFEST = "licenses/components.json"


def extract(archive: Path, workspace: Path) -> Path:
    if archive.name.endswith(".tar.zst"):
        tree = extract_tar_zst(archive, workspace)
    elif archive.name.endswith(".tar.gz"):
        tree = workspace / "tree"
        safe_extract_tar(archive, tree)
    else:
        raise SystemExit(f"not a distribution archive: {archive}")
    root = tree / "python"
    if not root.is_dir():
        raise SystemExit(f"{archive} has no python/ root")
    return root


def locate_prefix(root: Path) -> tuple[Path, str]:
    """The install prefix inside the archive, and which flavor this is."""
    if (root / "install").is_dir():
        return root / "install", "full"
    return root, "install_only"


def locate_stdlib(prefix: Path) -> Path:
    candidates = sorted((prefix / "lib").glob("python3.*"))
    directories = [path for path in candidates if path.is_dir()]
    if len(directories) != 1:
        raise SystemExit(
            f"expected one lib/python3.* under {prefix}, got {directories}"
        )
    return directories[0]


def check_metadata(root: Path, flavor: str) -> list[str]:
    path = root / "PYTHON.json"
    if flavor != "full":
        if path.exists():
            return ["PYTHON.json is present in an install-only archive"]
        return []
    if not path.is_file():
        return ["full archive has no PYTHON.json"]
    document = json.loads(path.read_text(encoding="utf-8"))
    problems = check_python_json(document)

    run_tests = document.get("run_tests")
    if run_tests and not (root / run_tests).is_file():
        problems.append(
            f"run_tests names {run_tests}, which the archive does not contain"
        )
    license_path = document.get("license_path")
    if license_path and not (root / license_path).is_file():
        problems.append(
            f"license_path names {license_path}, which the archive does not contain"
        )
    return problems


def check_licenses(prefix: Path) -> list[str]:
    manifest = prefix / LICENSE_MANIFEST
    if not manifest.is_file():
        return [f"no licence manifest at {LICENSE_MANIFEST}"]
    components = json.loads(manifest.read_text(encoding="utf-8"))["components"]
    declared = {c["file"] for c in components if c.get("file")}
    shipped = {p.name for p in (prefix / "licenses").glob("LICENSE.*.txt")}
    problems = [
        f"licence text declared but not shipped: {name}"
        for name in sorted(declared - shipped)
    ]
    problems += [
        f"licence text shipped but not declared: {name}"
        for name in sorted(shipped - declared)
    ]
    return problems


def check_members(root: Path) -> list[str]:
    problems = []
    for row in tree_manifest(root):
        link = row.get("linkname")
        if link and (link.startswith("/") or ".." in Path(link).parts):
            problems.append(f"symlink escapes the archive: {row['path']} -> {link}")
    return problems


def validate(archive: Path) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="pbsa-validate-") as tmp:
        root = extract(archive, Path(tmp))
        prefix, flavor = locate_prefix(root)
        stdlib = locate_stdlib(prefix)

        problems = check_metadata(root, flavor)
        problems += check_licenses(prefix)
        problems += check_members(root)
        try:
            summary = check_shared_modules(stdlib)
        except RuntimeError as error:
            problems.append(str(error))
            summary = {}

        if not problems:
            expected = expectations(stdlib)
            shipped = shipped_shared(stdlib, expected.ext_suffix)
            print(f"{archive.name}")
            print(f"  flavor                 {flavor}")
            print(
                f"  shared modules         {len(shipped)}, exactly what configure built"
            )
            print(f"  linked into libpython  {summary.get('builtin_module_count')}")
            print(
                f"  not built              {', '.join(sorted(expected.unavailable)) or 'none'}"
            )
            print(
                f"  licence texts          {len(list((prefix / 'licenses').glob('LICENSE.*.txt')))}"
            )
            if flavor == "full":
                print("  PYTHON.json            conforms to upstream's format 8 schema")
        return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    args = parser.parse_args(argv)

    failed = False
    for archive in args.archives:
        if not archive.is_file():
            print(f"{archive}: no such file", file=sys.stderr)
            failed = True
            continue
        problems = validate(archive)
        if problems:
            failed = True
            print(f"{archive.name}: REFUSED", file=sys.stderr)
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
