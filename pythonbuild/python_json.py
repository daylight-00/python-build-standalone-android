"""Generate ``python/PYTHON.json`` in Astral metadata format 8.

Standard fields keep their standard meaning. Fields describing a producer object
graph this project does not own are omitted rather than invented: for the
upstream-derived target there are no core object files, no static libpython, and
no relinkable inittab, so nothing claims otherwise.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .elf import elf_surface, is_elf
from .runtime_metadata import Layout
from .targets import Build
from .utils import read_json

PRODUCER_PATH_MARKERS = ("/Users/runner/", "/home/runner/", "/data/data/com.termux/")

# The SPDX identifiers upstream uses for CPython itself.
CPYTHON_LICENSES = ["Python-2.0", "CNRI-Python"]

# Test packages a repackager may want to strip. Upstream emits a fixed superset;
# this project reports only the ones the distribution actually ships, which
# serves the same purpose without naming packages that are not there.
CANDIDATE_TEST_PACKAGES = (
    "bsddb.test",
    "ctypes.test",
    "distutils.tests",
    "email.test",
    "idlelib.idle_test",
    "json.tests",
    "lib-tk.test",
    "lib2to3.tests",
    "sqlite3.test",
    "test",
    "tkinter.test",
    "unittest.test",
)


def _as_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, list | tuple):
        return " ".join(str(item) for item in value)
    return str(value)


def _sanitize(value: str) -> str:
    """Rewrite prefix placeholders and drop tokens naming a producer path."""
    value = value.replace("/usr/local", "install").replace("${prefix}", "install")
    tokens = re.findall(r"(?:'[^']*'|\"[^\"]*\"|\S+)", value)
    kept = [token for token in tokens if not any(m in token for m in PRODUCER_PATH_MARKERS)]
    return " ".join(kept)


def _config_vars(raw: dict[str, Any], layout: Layout, build: Build) -> dict[str, str]:
    values = {str(key): _sanitize(_as_string(value)) for key, value in sorted(raw.items())}
    values.update(
        {
            "prefix": "install",
            "exec_prefix": "install",
            "base": "install",
            "platbase": "install",
            "installed_base": "install",
            "installed_platbase": "install",
            "projectbase": "install/bin",
            "BINDIR": "install/bin",
            "BINLIBDEST": f"install/{layout.stdlib}",
            "LIBDEST": f"install/{layout.stdlib}",
            "INCLUDEPY": f"install/{layout.include}",
            "CONFINCLUDEPY": f"install/{layout.include}",
            "LIBDIR": "install/lib",
            "LIBPL": f"install/{layout.config_dir}",
            "DESTSHARED": f"install/{layout.stdlib}/lib-dynload",
            "CC": "clang",
            "CXX": "clang++",
            "AR": "llvm-ar",
            "SHELL": "sh -e",
            "TZPATH": _as_string(raw.get("TZPATH", "")),
            "ANDROID_API_LEVEL": str(build.android_api.level),
            "HOST_GNU_TYPE": build.triple,
        }
    )
    return values


def _provider_map(install: Path, readelf: str) -> dict[str, str]:
    providers: dict[str, str] = {}
    for path in sorted(install.rglob("*")):
        if not is_elf(path):
            continue
        rel = "install/" + path.relative_to(install).as_posix()
        for soname in elf_surface(path, readelf)["soname"]:
            providers[soname] = rel
        providers.setdefault(path.name, rel)
    return providers


def _links(needed: list[str], providers: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in sorted(set(needed)):
        if name in providers:
            rows.append({"name": name, "path_dynamic": providers[name], "system": False})
        else:
            rows.append({"name": name, "system": True})
    return rows


def _module_name(filename: str) -> str:
    return filename.split(".cpython-")[0].split(".abi3")[0].split(".so")[0]


def _test_packages(install: Path, layout: Layout) -> list[str]:
    stdlib = install / layout.stdlib
    return [
        package
        for package in CANDIDATE_TEST_PACKAGES
        if (stdlib / Path(*package.split("."))).is_dir()
    ]


def _bytecode_magic_number(install: Path, layout: Layout) -> str:
    """The value ``importlib.util.MAGIC_NUMBER`` would report, hex encoded.

    CPython 3.14 moved the magic number into a C constant, so it cannot be read
    off a shipped ``.pyc`` — the distribution contains none. The distribution
    does ship the internal header that defines it, so the token is reconstructed
    the same way ``_imp.pyc_magic_number_token`` is.
    """
    header = install / layout.include / "internal/pycore_magic_number.h"
    match = re.search(
        r"^#define\s+PYC_MAGIC_NUMBER\s+(\d+)", header.read_text(encoding="utf-8"), re.M
    )
    if not match:
        raise RuntimeError(f"PYC_MAGIC_NUMBER not found in {header}")
    token = int(match.group(1)) | (ord("\r") << 16) | (ord("\n") << 24)
    return token.to_bytes(4, "little").hex()


def build_python_json(
    install: Path,
    build: Build,
    *,
    python_version: str,
    python_mm: str,
    config_vars_source: dict[str, Any],
    readelf: str = "readelf",
) -> dict[str, Any]:
    layout = Layout(python_mm, build.triple)
    tag = "cp" + python_mm.replace(".", "")
    cache_tag = "cpython-" + python_mm.replace(".", "")

    # PEP 739 build-details.json is written by the interpreter itself, so it is
    # the authority for anything upstream would otherwise compute at runtime.
    details_path = install / layout.stdlib / "build-details.json"
    details: dict[str, Any] = {}
    if details_path.is_file():
        loaded = read_json(details_path)
        if isinstance(loaded, dict):
            details = loaded
    implementation: dict[str, Any] = details.get("implementation", {})
    abi: dict[str, Any] = details.get("abi", {})
    version_parts = implementation.get("version", {})

    providers = _provider_map(install, readelf)

    extensions: dict[str, list[dict[str, Any]]] = {}
    dynload = install / layout.stdlib / "lib-dynload"
    if dynload.is_dir():
        for path in sorted(dynload.glob("*.so")):
            if not is_elf(path):
                continue
            name = _module_name(path.name)
            extensions.setdefault(name, []).append(
                {
                    "in_core": False,
                    "init_fn": f"PyInit_{name}",
                    "links": _links(elf_surface(path, readelf)["needed"], providers),
                    "required": False,
                    "shared_lib": "install/" + path.relative_to(install).as_posix(),
                    "variant": "shared-library",
                }
            )

    libpython = install / layout.libpython
    core: dict[str, Any] = {"shared_lib": f"install/{layout.libpython}", "links": []}
    if is_elf(libpython):
        core["links"] = _links(elf_surface(libpython, readelf)["needed"], providers)

    major, minor, micro = (int(part) for part in python_version.split(".")[:3])
    hexversion = implementation.get("hexversion") or (
        (major << 24) | (minor << 16) | (micro << 8) | 0xF0
    )
    extension_suffixes = [
        suffix for suffix in (abi.get("extension_suffix"), abi.get("stable_abi_suffix")) if suffix
    ] or [layout.ext_suffix, ".abi3.so"]

    return {
        # Upstream emits the metadata format version as a string.
        "version": "8",
        "target_triple": build.triple,
        # Deprecated in format 8 in favour of build_options, still emitted.
        "optimizations": build.metadata_build_options,
        "build_options": build.metadata_build_options,
        "python_tag": tag,
        # sys.abiflags, which is empty for a release non-freethreaded build.
        "python_abi_tag": "".join(abi.get("flags") or []),
        # sysconfig.get_platform(), not the wheel platform tag.
        "python_platform_tag": details.get("platform", ""),
        "python_bytecode_magic_number": _bytecode_magic_number(install, layout),
        "python_symbol_visibility": "global-default",
        "crt_features": [
            "bionic-dynamic",
            f"bionic-api-level:{build.android_api.level}",
        ],
        "python_implementation_cache_tag": implementation.get("cache_tag", cache_tag),
        "python_implementation_hex_version": int(hexversion),
        "python_implementation_name": implementation.get("name", "cpython"),
        "python_implementation_version": [
            str(version_parts.get("major", major)),
            str(version_parts.get("minor", minor)),
            str(version_parts.get("micro", micro)),
            str(version_parts.get("releaselevel", "final")),
            str(version_parts.get("serial", 0)),
        ],
        "python_version": python_version,
        "python_major_minor_version": python_mm,
        "python_paths": {
            "data": "install",
            "include": f"install/{layout.include}",
            "platinclude": f"install/{layout.include}",
            "platlib": f"install/{layout.stdlib}/site-packages",
            "platstdlib": f"install/{layout.stdlib}",
            "purelib": f"install/{layout.stdlib}/site-packages",
            "stdlib": f"install/{layout.stdlib}",
        },
        "python_paths_abstract": {
            "data": "{base}",
            "include": "{installed_base}/include/python{py_version_short}{abiflags}",
            "platinclude": "{installed_platbase}/include/python{py_version_short}{abiflags}",
            "platlib": "{platbase}/lib/python{py_version_short}{abi_thread}/site-packages",
            "platstdlib": "{platbase}/lib/python{py_version_short}{abi_thread}",
            "purelib": "{base}/lib/python{py_version_short}{abi_thread}/site-packages",
            "stdlib": "{installed_base}/lib/python{py_version_short}{abi_thread}",
        },
        "python_config_vars": _config_vars(config_vars_source, layout, build),
        "python_exe": f"install/bin/python{python_mm}",
        "python_stdlib_platform_config": f"install/{layout.config_dir}",
        "python_stdlib_test_packages": _test_packages(install, layout),
        "python_suffixes": {
            "bytecode": [".pyc"],
            "debug_bytecode": [".pyc"],
            "extension": [*extension_suffixes, ".so"],
            "optimized_bytecode": [".pyc"],
            "source": [".py"],
        },
        "libpython_link_mode": "shared",
        "python_extension_module_loading": ["builtin", "shared-library"],
        "build_info": {"core": core, "extensions": dict(sorted(extensions.items()))},
        "licenses": CPYTHON_LICENSES,
        # Upstream points this at python/licenses/LICENSE.cpython.txt. This
        # project has no python/licenses/ root yet, so it names the license text
        # the distribution actually carries. Assembling that root is a release
        # blocker; see docs/design.md.
        "license_path": f"install/{layout.stdlib}/LICENSE.txt",
    }
