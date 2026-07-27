"""Acquisition of pinned build inputs.

Nothing enters a build unless its filename, size, and SHA-256 match a lock file
in ``config/``. Downloads are cached so repeated builds are offline after the
first acquisition.
"""

from __future__ import annotations

import platform
import shutil
import tarfile
import urllib.request
from pathlib import Path
from typing import Any

from .utils import file_identity, require_identity, sha256_path

DEFAULT_CACHE = Path("downloads")


def host_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        machine = "x86_64"
    elif machine in {"arm64", "aarch64"}:
        machine = "aarch64"
    if system == "darwin":
        return "darwin"
    return f"{system}-{machine}"


def _fetch(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    with urllib.request.urlopen(url) as response, partial.open("wb") as output:
        shutil.copyfileobj(response, output)
    partial.replace(destination)


def acquire(spec: dict[str, Any], cache: Path = DEFAULT_CACHE, *, what: str = "input") -> Path:
    """Return a cached copy of ``spec``, downloading it if needed.

    ``spec`` is a lock entry with ``filename``, ``url``, ``size_bytes``, and
    either ``sha256`` or ``sha1``.
    """
    path = cache / spec["filename"]
    if path.exists():
        try:
            _verify(path, spec, what)
            return path
        except RuntimeError:
            path.unlink()
    _fetch(spec["url"], path)
    _verify(path, spec, what)
    return path


def _verify(path: Path, spec: dict[str, Any], what: str) -> None:
    if "sha256" in spec:
        require_identity(path, spec, what)
        return
    if "sha1" in spec:
        import hashlib

        digest = hashlib.sha1()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        observed = {"filename": path.name, "size_bytes": path.stat().st_size}
        expected = {key: spec[key] for key in observed}
        if observed != expected or digest.hexdigest() != spec["sha1"]:
            raise RuntimeError(f"{what} does not match its lock: {file_identity(path)}")
        return
    raise ValueError(f"lock entry for {what} carries no checksum")


def extract_tarball(archive: Path, destination: Path) -> Path:
    """Extract a trusted, already-checksum-verified tool tarball."""
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tf:
        tf.extractall(destination, filter="data")
    return destination


def host_entry(section: dict[str, Any], what: str) -> dict[str, Any]:
    hosts = section["hosts"]
    tag = host_tag()
    if tag not in hosts:
        known = ", ".join(sorted(hosts))
        raise RuntimeError(f"{what} is not pinned for host {tag}; pinned hosts: {known}")
    return hosts[tag]


__all__ = [
    "DEFAULT_CACHE",
    "acquire",
    "extract_tarball",
    "host_entry",
    "host_tag",
    "sha256_path",
]
