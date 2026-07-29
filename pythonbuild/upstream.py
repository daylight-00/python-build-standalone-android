"""What python.org currently publishes, and what follows from it.

The only thing this project has to watch is CPython's version. Everything else
follows from whichever version is pinned:

- the official Android package lives in the same directory as the source tarball,
  so one discovery covers both builds;
- the dependency set is not chosen here at all. ``Android/android.py`` names the
  exact release assets its own build unpacks, and the source build compiles those
  same versions, so the set is read out of the pinned source rather than tracked
  separately. Bumping OpenSSL because a newer one exists would leave the
  interpreter built against a dependency set CPython does not expect.

Upstream watches many packages, one discovery policy each, because it builds them
all itself. Here there is one policy, and its shape is upstream's: list the
python.org index and read the versions out of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

INDEX = "https://www.python.org/ftp/python/"

# python.org's autoindex links each release directory. Prereleases live as files
# inside an X.Y.Z directory rather than as directories of their own, so listing
# directories yields released patches and nothing else.
_DIRECTORY = r'href="({series}\.(\d+))/"'

# The list literal in Android/android.py's unpack_deps, as `name-version-build`.
_COMPONENT = re.compile(r'"([a-z0-9]+)-([0-9][0-9A-Za-z.]*)-(\d+)"')


@dataclass(frozen=True)
class Component:
    """A dependency the pinned CPython names for its own Android build."""

    name: str
    version: str
    # A token android.py puts in a filename and build.sh takes as an argument,
    # not a quantity. The locks record it as a string and so does this.
    build: str


def patch_versions(listing: str, series: str) -> list[str]:
    """Every released patch of ``series``, oldest first."""
    pattern = re.compile(_DIRECTORY.format(series=re.escape(series)))
    found = {match.group(1): int(match.group(2)) for match in pattern.finditer(listing)}
    return sorted(found, key=lambda version: found[version])


def newest_patch(listing: str, series: str) -> str | None:
    versions = patch_versions(listing, series)
    return versions[-1] if versions else None


def source_archive(version: str) -> dict[str, str]:
    return {
        "filename": f"Python-{version}.tar.xz",
        "url": f"{INDEX}{version}/Python-{version}.tar.xz",
    }


def android_package(
    version: str, triple: str = "aarch64-linux-android"
) -> dict[str, str]:
    return {
        "filename": f"python-{version}-{triple}.tar.gz",
        "url": f"{INDEX}{version}/python-{version}-{triple}.tar.gz",
    }


def dependency_components(android_py: str) -> list[Component]:
    """The dependency set the pinned CPython names, in the order it names them.

    Read from ``unpack_deps`` rather than from a table of this project's own, so
    a CPython bump carries its dependency set with it.
    """
    if "def unpack_deps" not in android_py:
        raise RuntimeError("Android/android.py has no unpack_deps to read")
    body = android_py.split("def unpack_deps", 1)[1].split("]", 1)[0]
    found = [
        Component(name=name, version=version, build=build)
        for name, version, build in _COMPONENT.findall(body)
    ]
    if not found:
        raise RuntimeError("unpack_deps names no dependencies")
    return found


def components_differ(
    declared: list[dict[str, Any]], derived: list[Component]
) -> list[str]:
    """How a pinned dependency set disagrees with what the pinned CPython names."""
    ours = {
        str(entry["name"]): (str(entry["version"]), str(entry["build"]))
        for entry in declared
    }
    theirs = {
        component.name: (component.version, component.build) for component in derived
    }
    problems = [
        f"{name}: CPython names {theirs[name]}, the lock pins {ours[name]}"
        for name in sorted(set(ours) & set(theirs))
        if ours[name] != theirs[name]
    ]
    problems += [
        f"{name}: pinned here, not named by CPython"
        for name in sorted(set(ours) - set(theirs))
    ]
    problems += [
        f"{name}: named by CPython, not pinned here"
        for name in sorted(set(theirs) - set(ours))
    ]
    return problems


__all__ = [
    "INDEX",
    "Component",
    "android_package",
    "components_differ",
    "dependency_components",
    "newest_patch",
    "patch_versions",
    "source_archive",
]
