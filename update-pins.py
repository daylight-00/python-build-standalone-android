#!/usr/bin/env python3
"""Follow python.org's newest patch release of the pinned CPython series.

    ./update-pins.py            # report what is pinned and what is available
    ./update-pins.py --write    # move the pins to the newest patch

Only the CPython version is discovered. Everything else follows from it: the
official Android package lives in the same directory as the source tarball, and
the dependency set is read out of the new source's ``Android/android.py`` rather
than tracked here — see ``pythonbuild/upstream.py``.

A patch bump changes the pinned bytes and nothing else, which is exactly the case
the release waiver was built for: CI can build and validate it unattended, and a
device is needed only to promote the result out of prerelease.

The API floor is not touched. It is measured, by ``resolve-api-level.py``, and
the workflow that measures it triggers on the files this script writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from pythonbuild import upstream
from pythonbuild.targets import ROOT, load_builds
from pythonbuild.utils import read_json_object

USER_AGENT = "python-build-standalone-android update-pins"
TARGETS = ROOT / "ci-targets.yaml"
RECIPE_LOCK = ROOT / "config/source/dependency-recipes.lock.json"


def rewrite(path: Path, value: dict[str, object]) -> None:
    """Write an authored JSON file back, keeping the order it was written in.

    ``write_json`` sorts keys, which is right for a record generated into an
    archive and wrong here: these locks are read top to bottom, and sorting them
    would turn a two-value bump into a whole-file diff nobody can review.
    """
    text = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


@dataclass(frozen=True)
class Fetched:
    filename: str
    url: str
    size_bytes: int
    sha256: str
    path: Path

    def spec(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "url": self.url,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


def read(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return bytes(response.read())


def fetch(spec: dict[str, str], into: Path) -> Fetched:
    """Download an artifact and measure it, since nothing has pinned it yet."""
    path = into / spec["filename"]
    request = urllib.request.Request(spec["url"], headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    size = 0
    with (
        urllib.request.urlopen(request, timeout=120) as response,
        path.open("wb") as out,
    ):
        for block in iter(lambda: response.read(1 << 20), b""):
            digest.update(block)
            size += len(block)
            out.write(block)
    return Fetched(spec["filename"], spec["url"], size, digest.hexdigest(), path)


def android_py(source_archive: Path) -> str:
    """``Android/android.py`` out of a CPython source tarball."""
    with tarfile.open(source_archive) as tar:
        for member in tar:
            if member.name.endswith("/Android/android.py"):
                extracted = tar.extractfile(member)
                if extracted is not None:
                    return extracted.read().decode("utf-8")
    raise RuntimeError(f"{source_archive} contains no Android/android.py")


def pinned() -> tuple[str, dict[str, Path]]:
    """The version every build is pinned to, and where each build's lock lives."""
    locks = {
        build.build_option: build.input_lock_path() for build in load_builds().values()
    }
    versions = {
        option: str(read_json_object(path)["python"]["version"])
        for option, path in locks.items()
    }
    if len(set(versions.values())) != 1:
        raise SystemExit(f"builds are pinned to different versions: {versions}")
    return next(iter(versions.values())), locks


def rewrite_lock(path: Path, version: str, artifact: Fetched, key: str) -> Path:
    """Move one lock to a new version, and to the filename that names it."""
    lock = read_json_object(path)
    old = str(lock["python"]["version"])
    lock["python"]["version"] = version
    lock[key] = artifact.spec()
    flow = lock.get("build_flow")
    if isinstance(flow, dict):
        # The prose names the version it binds to, so it moves with the pin. The
        # path beside it named a file that has never existed and nothing read it.
        flow["dependency_lock"] = RECIPE_LOCK.relative_to(ROOT).as_posix()
        binding = flow.get("dependency_binding")
        if isinstance(binding, str):
            flow["dependency_binding"] = binding.replace(old, version)
    rewrite(path, lock)
    moved = path.with_name(path.name.replace(old, version))
    if moved != path:
        path.rename(moved)
    return moved


def rewrite_recipe_lock(components: list[upstream.Component], version: str) -> None:
    lock = read_json_object(RECIPE_LOCK)
    lock["components"] = [
        {**existing, "version": component.version, "build": component.build}
        for existing, component in zip(lock["components"], components, strict=True)
    ]
    verification = lock.get("verification")
    if isinstance(verification, dict):
        for name, text in list(verification.items()):
            if isinstance(text, str):
                verification[name] = _reversion(text, version)
    rewrite(RECIPE_LOCK, lock)


def _reversion(text: str, version: str) -> str:
    """Move a CPython version named in prose, leaving other versions alone."""
    return re.sub(r"CPython 3\.\d+\.\d+", f"CPython {version}", text)


def repoint_targets(moved: dict[str, Path]) -> None:
    text = TARGETS.read_text(encoding="utf-8")
    for build in load_builds().values():
        new = moved[build.build_option].relative_to(ROOT).as_posix()
        text = text.replace(build.input_lock, new)
    TARGETS.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="apply the newest patch to the pins"
    )
    args = parser.parse_args(argv)

    version, locks = pinned()
    series = ".".join(version.split(".")[:2])
    listing = read(upstream.INDEX).decode("utf-8", "replace")
    newest = upstream.newest_patch(listing, series)
    if newest is None:
        print(f"python.org lists no releases of {series}", file=sys.stderr)
        return 1

    print(f"  pinned     {version}")
    print(
        f"  newest     {newest}   ({len(upstream.patch_versions(listing, series))} patches of {series})"
    )

    if newest == version:
        print("\n  the pins are on the newest patch of this series")
        return 0
    if not args.write:
        print(f"\n  {series} has moved to {newest}; re-run with --write to follow it")
        return 0

    with tempfile.TemporaryDirectory(prefix="pbsa-pins-") as tmp:
        staging = Path(tmp)
        print(f"\n  fetching {newest}")
        source = fetch(upstream.source_archive(newest), staging)
        package = fetch(upstream.android_package(newest), staging)
        components = upstream.dependency_components(android_py(source.path))

        moved = {
            "default": rewrite_lock(locks["default"], newest, source, "source_archive"),
            "upstream": rewrite_lock(locks["upstream"], newest, package, "archive"),
        }
        rewrite_recipe_lock(components, newest)
        repoint_targets(moved)

    print(f"  source     {source.sha256}  {source.filename}")
    print(f"  package    {package.sha256}  {package.filename}")
    print(
        f"  deps       {', '.join(f'{c.name} {c.version}-{c.build}' for c in components)}"
    )
    for option, path in moved.items():
        print(f"  lock       {option}: {path.relative_to(ROOT).as_posix()}")
    print(
        "\n  The API floor is not touched here — it is measured. Let the api-level\n"
        "  workflow re-measure it, and qualify the build on a device before the\n"
        "  release leaves prerelease."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
