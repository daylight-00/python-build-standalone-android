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

from .archive import newest_member_mtime, safe_extract_tar
from .assemble import BUILD_PLACEHOLDER, TOOLCHAIN_PLACEHOLDER, PrefixSource
from .dependencies import (
    bare_toolchain_override,
    build_dependencies,
    file_prefix_map_override,
)
from .downloads import acquire
from .elf import android_note, elf_objects
from .targets import Build
from .toolchain import Toolchain, pkg_config_identity, pkg_config_shim
from .utils import file_identity, read_json_object, run_logged

ANDROID_DRIVER = "Android/android.py"


def _extract_source(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    safe_extract_tar(archive, destination)
    roots = [path for path in destination.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise RuntimeError(
            f"expected one directory in the CPython source archive, got {roots}"
        )
    return roots[0]


def _driver(
    source: Path, cross_build: Path, environment: dict[str, str], *args: str
) -> None:
    run_logged(
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
    toolchain_bin: Path,
    pkg_config_bin: Path,
    readelf: str,
    source_date_epoch: int,
    host_paths: tuple[tuple[str, str], ...],
    sdk_root: Path,
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

    # The same overrides, for the same reasons, applied to the interpreter's own
    # environment script: the recipes' copy of it came from here.
    applied_overrides = [
        override.apply(source / "Android")
        for override in (
            file_prefix_map_override(host_paths),
            bare_toolchain_override(),
        )
    ]

    environment = dict(os.environ)
    environment["ANDROID_API_LEVEL"] = str(android_api)
    # Android/android.py refuses to run without it.
    environment.setdefault("ANDROID_HOME", str(sdk_root))
    environment["SOURCE_DATE_EPOCH"] = str(source_date_epoch)
    # The tools are named without their directory, so the directory has to be on
    # PATH. The environment script puts it there for the steps that source it, but
    # `make` deliberately does not source it — upstream relies on configure having
    # captured the absolute paths in the Makefile, and those are exactly what this
    # build does not want recorded.
    environment["PATH"] = os.pathsep.join(
        [str(pkg_config_bin), str(toolchain_bin), environment.get("PATH", "")]
    )
    # A search path inherited from the host would decide which .pc file is read.
    environment.pop("PKG_CONFIG_PATH", None)

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
        "pkg_config": pkg_config_identity(),
        "source_date_epoch": source_date_epoch,
        "overrides": applied_overrides,
        "driver": ANDROID_DRIVER,
        "objects": verify_install_prefix(
            prefix, android_api=android_api, readelf=readelf
        ),
    }


# What a finished distribution keeps out of the build prefix. Upstream's own
# packaging step uses the same shape of whitelist and drops everything else,
# which is why the official package has no bin/ at all. This one additionally
# keeps CPython's own entry points, because this is a command-line runtime
# rather than an embedding package.
KEEP = {
    "bin": ["python3*", "pydoc3*", "idle3*"],
    "include": ["openssl*", "python*", "sqlite*"],
    "lib": [
        "engines-3",
        "libcrypto*.so*",
        "libpython*",
        "libsqlite*.so*",
        "libssl*.so*",
        "ossl-modules",
        "python*",
    ],
    "lib/pkgconfig": ["*crypto*", "*ssl*", "*python*", "*sqlite*"],
}

# The dependency command-line tools must not reach a distribution. They are not
# what CPython links — it links the libraries — and some of them are the GPLv2
# scripts that the project's licensing position depends on not shipping.
FORBIDDEN_IN_BIN = ("xz", "lzma", "bzip2", "bunzip2", "openssl", "sqlite3", "c_rehash")


def curate_prefix(source: Path, destination: Path) -> dict[str, Any]:
    """Reduce a build prefix to the tree a distribution ships."""
    destination.mkdir(parents=True, exist_ok=True)
    kept: list[str] = []
    for rel_dir, patterns in KEEP.items():
        for pattern in patterns:
            for path in sorted((source / rel_dir).glob(pattern)):
                target = destination / rel_dir / path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                if path.is_symlink():
                    link = os.readlink(path)
                    if link.startswith("/"):
                        raise RuntimeError(
                            f"absolute symlink in the build prefix: {path}"
                        )
                    target.symlink_to(link)
                elif path.is_dir():
                    shutil.copytree(path, target, symlinks=True)
                else:
                    shutil.copy2(path, target)
                kept.append(f"{rel_dir}/{path.name}")

    # `make install` compiles the whole standard library three times over, and
    # upstream removes the result for the same reason: a distribution ships
    # source, not bytecode. It also has to go for this project's reproducibility
    # contract, because timestamp-invalidated bytecode embeds the mtime of the
    # source it was compiled from.
    caches = sorted(path for path in destination.rglob("__pycache__") if path.is_dir())
    for cache in caches:
        shutil.rmtree(cache)
    remaining = list(destination.rglob("*.pyc"))
    if remaining:
        raise RuntimeError(f"bytecode survived curation: {remaining[:3]}")

    dropped_binaries = sorted(
        path.name
        for path in (source / "bin").iterdir()
        if not (destination / "bin" / path.name).exists()
    )
    leaked = sorted(
        path.name
        for path in (destination / "bin").iterdir()
        if any(path.name.startswith(prefix) for prefix in FORBIDDEN_IN_BIN)
    )
    if leaked:
        raise RuntimeError(
            f"dependency command-line tools reached the distribution: {leaked}"
        )
    if list(destination.glob("**/*.a")):
        raise RuntimeError(
            "static archives are build inputs and must not be distributed"
        )

    return {
        "schema_version": 1,
        "kept": kept,
        "dropped_from_bin": dropped_binaries,
        "bytecode_caches_removed": len(caches),
        "rationale": (
            "the dependency command-line tools are not what CPython links, and some of "
            "them are the GPLv2 scripts this project's licensing position depends on not "
            "shipping"
        ),
    }


def prepare_source_prefix(
    *,
    build: Build,
    toolchain: Toolchain,
    workspace: Path,
    cache: Path,
) -> PrefixSource:
    """Build the dependencies and CPython, and curate the result."""
    runtime_data = build.runtime_data
    # One timestamp for the whole build, taken from the primary pinned input.
    source_archive = acquire(
        read_json_object(build.input_lock_path())["source_archive"],
        cache,
        what="CPython source",
    )
    source_date_epoch = newest_member_mtime(source_archive)

    # Every directory of this machine's that a build could record. The workspace
    # covers both the dependency and the interpreter trees under it.
    host_paths = (
        (str(workspace), BUILD_PLACEHOLDER),
        (str(toolchain.ndk), TOOLCHAIN_PLACEHOLDER),
    )

    # One pkg-config for the whole build, and the one this project pins.
    pkg_config_bin = pkg_config_shim(workspace / "pkg-config")

    dependency_prefix, dependencies = build_dependencies(
        workspace=workspace / "dependencies",
        cache=cache,
        ndk_revision=toolchain.revision,
        android_api=build.android_api.level,
        host=build.triple,
        readelf=str(toolchain.readelf),
        source_date_epoch=source_date_epoch,
        host_paths=host_paths,
        pkg_config_bin=pkg_config_bin,
        sdk_root=toolchain.sdk_root,
    )
    built_prefix, cpython = build_cpython(
        workspace=workspace / "cpython",
        cache=cache,
        dependency_prefix=dependency_prefix,
        android_api=build.android_api.level,
        host=build.triple,
        tzpath=runtime_data.get("tzpath"),
        toolchain_bin=toolchain.readelf.parent,
        pkg_config_bin=pkg_config_bin,
        readelf=str(toolchain.readelf),
        source_date_epoch=source_date_epoch,
        host_paths=host_paths,
        sdk_root=toolchain.sdk_root,
        lock_path=build.input_lock_path(),
    )

    curated = workspace / "curated"
    shutil.rmtree(curated, ignore_errors=True)
    curation = curate_prefix(built_prefix, curated)

    return PrefixSource(
        prefix=curated,
        python_version=cpython["python_version"],
        python_mm=".".join(cpython["python_version"].split(".")[:2]),
        record={
            "producer": "cpython-source",
            "lock": build.input_lock,
            "cpython": cpython,
            "dependencies": dependencies,
            "curation": curation,
            "runtime_data": runtime_data,
        },
        retained=None,
        needs_launcher=False,
        host_paths=host_paths,
    )


def verify_install_prefix(
    prefix: Path, *, android_api: int, readelf: str
) -> dict[str, Any]:
    """Every object in the finished prefix must report the requested API level.

    The dependencies were already checked when they were built; this catches the
    interpreter and its extension modules disagreeing with them.
    """
    objects = elf_objects(prefix)
    libpython = [path for path in objects if path.name.startswith("libpython")]
    if not libpython:
        raise RuntimeError(f"no libpython was built into {prefix}")

    mismatched = []
    unstamped = []
    for path in objects:
        rel = path.relative_to(prefix).as_posix()
        note = android_note(path, readelf)
        if note is None:
            unstamped.append(rel)
        elif note["api_level"] != android_api:
            mismatched.append(f"{rel} reports {note['api_level']}")
    if mismatched:
        raise RuntimeError(
            f"objects were not built for API {android_api}: {', '.join(mismatched[:5])}"
        )
    # Every member of a finished distribution is an executable or a shared object
    # the NDK produced, and the NDK stamps all of those. A missing note used to
    # be tolerated, which made the whole check pass silently whenever the note
    # could not be read — the failure mode it exists to prevent.
    if unstamped:
        raise RuntimeError(
            f"objects carry no .note.android.ident, so the API level they were "
            f"built for cannot be confirmed: {', '.join(unstamped[:5])}"
        )

    sample = android_note(libpython[0], readelf) or {}
    return {
        "object_count": len(objects),
        "api_level": android_api,
        "ndk_version": sample.get("ndk_version"),
        "ndk_build_number": sample.get("ndk_build_number"),
    }
