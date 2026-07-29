"""Resolution of the pinned build toolchain.

The NDK is expected to be installed already — it is large, and CI installs it
with ``sdkmanager`` so the download is cached by the runner. Everything else is
acquired from ``config/toolchain.lock.json`` on demand.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pkgconf
import zstandard

from .downloads import DEFAULT_CACHE, acquire, extract_tarball, host_entry, host_tag
from .targets import ROOT, Build
from .utils import read_json_object, run

TOOLCHAIN_LOCK = ROOT / "config/toolchain.lock.json"


def pkg_config_identity() -> str:
    """What ``pkg-config`` resolved to, recorded by the builds that run it."""
    version = run([str(pkgconf.get_executable()), "--version"]).stdout.strip()
    return f"pkgconf {version}"


def pkg_config_shim(directory: Path) -> Path:
    """A ``pkg-config`` that is the same program on every host.

    configure and the recipes look it up on PATH, and which implementation they
    find decides both which .pc file is read for a dependency and how the flags
    it yields are spelled. The two in circulation disagree on both, which made
    two hosts produce different interpreters from the same input. Pinned through
    ``uv.lock``, like every other tool this build runs, and exposed under the name
    the builds actually call.
    """
    directory.mkdir(parents=True, exist_ok=True)
    shim = directory / "pkg-config"
    shim.unlink(missing_ok=True)
    shim.symlink_to(pkgconf.get_executable())
    return directory


@dataclass(frozen=True)
class Toolchain:
    ndk: Path
    revision: str
    clang: Path
    readelf: Path
    strip: Path
    patchelf: Path
    patchelf_version: str

    def identity(self) -> dict[str, Any]:
        """Toolchain provenance with no host paths in it.

        This record ships inside the archive, so it names versions rather than
        directories: an absolute path would leak the build machine's layout and
        would differ between two otherwise identical builds.
        """
        version = run([str(self.clang), "--version"]).stdout.splitlines()
        return {
            "ndk_revision": self.revision,
            "build_host": host_tag(),
            "compiler": self.clang.name,
            "compiler_version": version[0] if version else "",
            "readelf": self.readelf.name,
            "strip": self.strip.name,
            "patchelf_version": self.patchelf_version,
            "zstandard": zstandard.__version__,
            "libzstd": ".".join(str(part) for part in zstandard.ZSTD_VERSION),
        }


def _ndk_search_paths(revision: str) -> list[Path]:
    candidates: list[Path] = []
    explicit = os.environ.get("ANDROID_NDK_HOME") or os.environ.get("ANDROID_NDK_ROOT")
    if explicit:
        candidates.append(Path(explicit))
    for variable in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        root = os.environ.get(variable)
        if root:
            candidates.append(Path(root) / "ndk" / revision)
    home = Path.home()
    candidates.extend(
        [
            home / "opt/Android/ndk" / revision,
            home / "Android/Sdk/ndk" / revision,
            Path("/opt/android-sdk/ndk") / revision,
            Path("/usr/local/lib/android/sdk/ndk") / revision,
        ]
    )
    return candidates


def resolve_ndk(revision: str) -> Path:
    for candidate in _ndk_search_paths(revision):
        if (candidate / "toolchains/llvm/prebuilt").is_dir():
            if candidate.name != revision and _ndk_revision(candidate) != revision:
                continue
            return candidate
    searched = "\n  ".join(str(path) for path in _ndk_search_paths(revision))
    raise RuntimeError(
        f"Android NDK {revision} not found. Install it with:\n"
        f"  sdkmanager 'ndk;{revision}'\n"
        f"or set ANDROID_NDK_HOME. Searched:\n  {searched}"
    )


def supported_api_levels(
    ndk: Path, arch_triple: str = "aarch64-linux-android"
) -> range:
    """Every API level this NDK can compile for.

    Read off the sysroot rather than written down: the NDK ships one library
    directory per level it supports, so r27 covering 21 to 35 is a property of
    the revision the toolchain lock pins, not a pair of numbers typed in here.
    """
    libdir = _sysroot(ndk) / "usr/lib" / arch_triple
    levels = sorted(int(path.name) for path in libdir.iterdir() if path.name.isdigit())
    if not levels:
        raise RuntimeError(f"no per-API library directories under {libdir}")
    return range(levels[0], levels[-1] + 1)


def _sysroot(ndk: Path) -> Path:
    return _llvm_bin(ndk).parent / "sysroot"


def _ndk_revision(ndk: Path) -> str | None:
    properties = ndk / "source.properties"
    if not properties.is_file():
        return None
    for line in properties.read_text(encoding="utf-8").splitlines():
        if line.startswith("Pkg.Revision"):
            return line.split("=", 1)[1].strip()
    return None


def _llvm_bin(ndk: Path) -> Path:
    prebuilt = ndk / "toolchains/llvm/prebuilt"
    hosts = sorted(path for path in prebuilt.iterdir() if (path / "bin").is_dir())
    if not hosts:
        raise RuntimeError(f"no prebuilt LLVM toolchain under {prebuilt}")
    return hosts[0] / "bin"


def resolve_patchelf(lock: dict[str, Any], cache: Path = DEFAULT_CACHE) -> Path:
    section = lock["patchelf"]
    installed = cache / f"patchelf-{section['version']}" / str(section["binary_path"])
    if not installed.is_file():
        entry = host_entry(section, "patchelf")
        archive = acquire(entry, cache, what="patchelf")
        extract_tarball(archive, cache / f"patchelf-{section['version']}")
    if not installed.is_file():
        raise RuntimeError(f"patchelf did not unpack to the expected path: {installed}")
    installed.chmod(0o755)
    help_text = run([str(installed), "--help"])
    if "--page-size" not in (help_text.stdout + help_text.stderr):
        raise RuntimeError(f"patchelf at {installed} lacks --page-size support")
    return installed


def resolve_toolchain(build: Build, cache: Path = DEFAULT_CACHE) -> Toolchain:
    lock = read_json_object(TOOLCHAIN_LOCK)
    revision = lock["ndk"]["revision"]
    if revision != build.ndk:
        raise RuntimeError(
            f"build {build.name} pins NDK {build.ndk} but the toolchain lock pins {revision}"
        )
    ndk = resolve_ndk(revision)
    bindir = _llvm_bin(ndk)
    clang = bindir / build.clang
    if not clang.is_file():
        raise RuntimeError(
            f"NDK {revision} has no compiler for API {build.android_api.level}: {clang}"
        )
    return Toolchain(
        ndk=ndk,
        revision=revision,
        clang=clang,
        readelf=bindir / "llvm-readelf",
        strip=bindir / "llvm-strip",
        patchelf=resolve_patchelf(lock, cache),
        patchelf_version=lock["patchelf"]["version"],
    )
