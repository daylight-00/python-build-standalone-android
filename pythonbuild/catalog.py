"""uv download-metadata catalogs.

uv's managed-Python key is ``{implementation}-{version}-{os}-{arch}-{libc}`` and
has no Android component, so an Android distribution is catalogued as ``linux``
with ``libc: none`` — which is also exactly what uv detects on the device. The
consequence is that two Android targets collide on one key, so each target gets
its own catalog file and the consumer picks one with
``--python-downloads-json-url``.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from .targets import Build

CATALOG_OS = "linux"
CATALOG_LIBC = "none"
CATALOG_FLAVOR = "install_only_stripped"


def catalog_key(implementation: str, python_version: str, build: Build) -> str:
    return f"{implementation}-{python_version}-{CATALOG_OS}-{build.arch}-{CATALOG_LIBC}"


def asset_url(repository: str, tag: str, filename: str) -> str:
    quoted = urllib.parse.quote(filename)
    return f"https://github.com/{repository}/releases/download/{tag}/{quoted}"


def catalog_entry(
    build: Build,
    *,
    python_version: str,
    tag: str,
    filename: str,
    sha256: str,
    repository: str,
    implementation: str = "cpython",
) -> tuple[str, dict[str, Any]]:
    major, minor, patch = (int(part) for part in python_version.split(".")[:3])
    entry = {
        "name": implementation,
        "arch": {"family": build.arch, "variant": None},
        "os": CATALOG_OS,
        "libc": CATALOG_LIBC,
        "major": major,
        "minor": minor,
        "patch": patch,
        "prerelease": "",
        "url": asset_url(repository, tag, filename),
        "sha256": sha256,
        "variant": None,
        "build": tag,
    }
    return catalog_key(implementation, python_version, build), entry


def build_catalog(
    build: Build,
    *,
    python_version: str,
    tag: str,
    filename: str,
    sha256: str,
    repository: str,
) -> dict[str, Any]:
    key, entry = catalog_entry(
        build,
        python_version=python_version,
        tag=tag,
        filename=filename,
        sha256=sha256,
        repository=repository,
    )
    return {key: entry}


def merge_catalog(existing: dict[str, Any], addition: dict[str, Any]) -> dict[str, Any]:
    """Merge catalogs for the same target across releases, newest wins."""
    merged = dict(existing)
    for key, entry in addition.items():
        merged[key] = entry
    return dict(sorted(merged.items()))


def latest_release(repository: str, tag: str) -> dict[str, Any]:
    """The pointer file published on the ``latest-release`` branch."""
    return {
        "version": 1,
        "tag": tag,
        "release_url": f"https://github.com/{repository}/releases/tag/{tag}",
        "asset_url_prefix": f"https://github.com/{repository}/releases/download/{tag}",
    }
