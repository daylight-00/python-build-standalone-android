#!/usr/bin/env python3
"""Measure the minimum Android API level the flagship build should target.

    ./resolve-api-level.py                 # report what the rule selects
    ./resolve-api-level.py --check         # fail if ci-targets.yaml disagrees

``ci-targets.yaml`` states the rule and this measures it, by configuring CPython
at candidate levels and comparing the ``pyconfig.h`` each produces. See
``pythonbuild/api_level.py`` for why it is measured rather than re-derived from
``AC_CHECK_FUNCS``.

This is not part of a build. The answer only moves when the CPython pin or the
NDK pin moves, and a floor that changed silently would defeat the release notes
that exist to announce it — so the declared value stays the decision of record
and this reports when it has gone stale.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from pythonbuild.api_level import Resolution, decisions, resolve
from pythonbuild.downloads import DEFAULT_CACHE, acquire
from pythonbuild.logging import log, set_logger
from pythonbuild.targets import get_build
from pythonbuild.toolchain import max_api_level, resolve_ndk
from pythonbuild.utils import read_json_object, run_logged

ANDROID_DRIVER = "Android/android.py"
# Below the oldest level the official package supports there is nothing this
# project would ever ship, so the search does not go there.
LOWEST_CANDIDATE = 21


def extract_source(archive: Path, destination: Path) -> Path:
    if destination.is_dir():
        roots = [path for path in destination.iterdir() if path.is_dir()]
        if len(roots) == 1:
            return roots[0]
    destination.mkdir(parents=True, exist_ok=True)
    run_logged(
        ["tar", "-xf", str(archive), "-C", str(destination)], "extracting CPython"
    )
    roots = [path for path in destination.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise RuntimeError(f"expected one directory in the source archive, got {roots}")
    return roots[0]


def driver(
    source: Path, cross_build: Path, environment: dict[str, str], *args: str
) -> None:
    run_logged(
        [sys.executable, str(source / ANDROID_DRIVER), *args],
        f"android.py {' '.join(args)}",
        cwd=source,
        env={**environment, "CROSS_BUILD_DIR": str(cross_build)},
    )


class Configurer:
    """Configure CPython at a level and report the decisions it made."""

    def __init__(
        self,
        *,
        source: Path,
        cross_build: Path,
        host: str,
        toolchain_bin: Path,
        sdk_root: Path,
        dependency_prefix: Path | None,
    ) -> None:
        self.source = source
        self.cross_build = cross_build
        self.host = host
        self.dependency_prefix = dependency_prefix
        self.environment = dict(os.environ)
        self.environment["PATH"] = os.pathsep.join(
            [str(toolchain_bin), self.environment.get("PATH", "")]
        )
        self.environment.pop("PKG_CONFIG_PATH", None)
        self.environment.setdefault("ANDROID_HOME", str(sdk_root))
        self.cache: dict[int, dict[str, str]] = {}

    def prepare_build_python(self) -> None:
        if (self.cross_build / "build/python").exists():
            log("reusing the build interpreter already in this workspace")
            return
        driver(self.source, self.cross_build, self.environment, "configure-build")
        driver(self.source, self.cross_build, self.environment, "make-build")

    def __call__(self, level: int) -> dict[str, str]:
        if level in self.cache:
            return self.cache[level]
        host_dir = self.cross_build / self.host
        # Every tree a build writes into starts empty, so one level's decisions
        # cannot be read out of another level's leftovers.
        shutil.rmtree(host_dir, ignore_errors=True)
        prefix = host_dir / "prefix"
        prefix.mkdir(parents=True)
        if self.dependency_prefix is not None:
            shutil.copytree(
                self.dependency_prefix, prefix, symlinks=True, dirs_exist_ok=True
            )

        log(f"configuring for API {level}")
        driver(
            self.source,
            self.cross_build,
            {**self.environment, "ANDROID_API_LEVEL": str(level)},
            "configure-host",
            self.host,
        )
        self.cache[level] = decisions(host_dir / "pyconfig.h")
        return self.cache[level]


def report(resolution: Resolution, declared: int) -> None:
    print()
    print(f"  measured floor       API {resolution.level}")
    print(f"  declared             API {declared}")
    print(f"  NDK compiles up to   API {resolution.ndk_max}")
    print(f"  levels configured    {', '.join(str(x) for x in resolution.searched)}")
    print(f"  evidence             {resolution.evidence()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="aarch64-linux-android")
    parser.add_argument("--workspace", default=Path("build/api-level"), type=Path)
    parser.add_argument("--cache", default=DEFAULT_CACHE, type=Path)
    parser.add_argument(
        "--dependency-prefix",
        type=Path,
        help="a built dependency prefix to configure against; without one the "
        "dependent modules are absent at every level alike, which the comparison "
        "cancels out",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero when ci-targets.yaml declares a different level",
    )
    args = parser.parse_args(argv)

    build = get_build(args.target)
    set_logger("api-level")
    ndk = resolve_ndk(build.ndk)
    ndk_max = max_api_level(ndk)
    log(f"NDK {build.ndk} compiles up to API {ndk_max}")

    workspace = args.workspace.resolve()
    lock = read_json_object(build.input_lock_path())
    archive = acquire(lock["source_archive"], args.cache, what="CPython source")
    source = extract_source(archive, workspace / "source")

    toolchain_bin = next((ndk / "toolchains/llvm/prebuilt").iterdir()) / "bin"
    # android.py insists on ANDROID_HOME. Inferring it from the NDK this project
    # already resolved beats making every caller export the same value twice.
    sdk_root = ndk.parent.parent if ndk.parent.name == "ndk" else ndk
    configurer = Configurer(
        source=source,
        cross_build=workspace / "cross-build",
        host=build.triple,
        toolchain_bin=toolchain_bin,
        sdk_root=sdk_root,
        dependency_prefix=(
            args.dependency_prefix.resolve() if args.dependency_prefix else None
        ),
    )
    configurer.prepare_build_python()

    resolution = resolve(configurer, lowest=LOWEST_CANDIDATE, ndk_max=ndk_max)
    report(resolution, build.android_api.level)

    if resolution.level != build.android_api.level:
        print(
            f"\nci-targets.yaml declares API {build.android_api.level}, the rule it "
            f"states selects API {resolution.level}.\n"
            f"Neither number is chosen by this project, so this is a floor that moved "
            f"on its own — update the declaration and say so in the release notes.",
            file=sys.stderr,
        )
        return 1 if args.check else 0
    print("\n  the declared floor is what the rule selects")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:  # pragma: no cover
        raise SystemExit(error.returncode) from error
