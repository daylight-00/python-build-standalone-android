"""Build CPython for Android from source.

The upstream ``Android/android.py`` flow is used as-is rather than
reimplemented: it knows how to cross-compile CPython for Android, and following
it keeps this a build of upstream's sources.

Two things are steered from here. The dependency prefix is populated before
configure runs, which makes the flow skip its own download of the prebuilt
archives — the guard upstream already has for a prefix that exists. And
``--with-tzpath`` is passed through, which the flow forwards to ``configure``.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .archive import safe_extract_tar
from .downloads import acquire
from .elf import android_note, elf_objects
from .utils import file_identity, read_json_object, run_checked

ANDROID_DRIVER = "Android/android.py"


def _extract_source(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    safe_extract_tar(archive, destination)
    roots = [path for path in destination.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise RuntimeError(f"expected one directory in the CPython source archive, got {roots}")
    return roots[0]


def _driver(source: Path, cross_build: Path, environment: dict[str, str], *args: str) -> None:
    run_checked(
        [sys.executable, str(source / ANDROID_DRIVER), *args],
        f"android.py {args[0]}",
        cwd=source,
        env={**environment, "CROSS_BUILD_DIR": str(cross_build)},
    )


def build_cpython(
    *,
    workspace: Path,
    cache: Path,
    dependency_prefix: Path,
    android_api: int,
    host: str,
    tzpath: str | None,
    readelf: str,
    lock_path: Path,
) -> tuple[Path, dict[str, Any]]:
    """Cross-compile CPython against an already-built dependency prefix."""
    lock = read_json_object(lock_path)
    source_archive = acquire(lock["source_archive"], cache, what="CPython source")

    source = _extract_source(source_archive, workspace / "source")
    cross_build = workspace / "cross-build"
    prefix = cross_build / host / "prefix"

    # A clean host tree every time: a prefix left over from an earlier run would
    # merge with this one and make the result depend on what was built before.
    # The build interpreter under cross-build/build is independent and expensive,
    # so it is left alone.
    shutil.rmtree(cross_build / host, ignore_errors=True)

    # Upstream skips unpacking the prebuilt dependency archives when the prefix
    # already exists, so populating it here is all it takes to build against the
    # dependencies compiled from source.
    prefix.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(dependency_prefix, prefix, symlinks=True)

    environment = dict(os.environ)
    environment["ANDROID_API_LEVEL"] = str(android_api)

    configure_args = [f"--with-tzpath={tzpath}"] if tzpath else []

    _driver(source, cross_build, environment, "configure-build")
    _driver(source, cross_build, environment, "make-build")
    # `--` so argparse treats the configure arguments as positional rather than
    # as options of its own, which is the convention the driver documents.
    _driver(
        source,
        cross_build,
        environment,
        "configure-host",
        host,
        *(["--", *configure_args] if configure_args else []),
    )
    _driver(source, cross_build, environment, "make-host", host)

    return prefix, {
        "schema_version": 1,
        "source": file_identity(source_archive),
        "python_version": lock["python"]["version"],
        "android_api": android_api,
        "host": host,
        "configure_args": configure_args,
        "driver": ANDROID_DRIVER,
        "objects": verify_prefix(prefix, android_api=android_api, readelf=readelf),
    }


def verify_prefix(prefix: Path, *, android_api: int, readelf: str) -> dict[str, Any]:
    """Every object in the finished prefix must report the requested API level.

    The dependencies were already checked when they were built; this catches the
    interpreter and its extension modules disagreeing with them.
    """
    objects = elf_objects(prefix)
    libpython = [path for path in objects if path.name.startswith("libpython")]
    if not libpython:
        raise RuntimeError(f"no libpython was built into {prefix}")

    mismatched = []
    for path in objects:
        note = android_note(path, readelf)
        if note is not None and note["api_level"] != android_api:
            mismatched.append(f"{path.relative_to(prefix).as_posix()} reports {note['api_level']}")
    if mismatched:
        raise RuntimeError(
            f"objects were not built for API {android_api}: {', '.join(mismatched[:5])}"
        )

    sample = android_note(libpython[0], readelf) or {}
    return {
        "object_count": len(objects),
        "api_level": android_api,
        "ndk_version": sample.get("ndk_version"),
        "ndk_build_number": sample.get("ndk_build_number"),
    }
