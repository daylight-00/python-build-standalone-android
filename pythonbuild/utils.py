"""Small shared primitives."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

CHUNK = 1024 * 1024

# Callers include workflow one-liners, which naturally pass a string.
StrPath = str | os.PathLike[str]


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value))


def read_json(path: StrPath) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_json_object(path: StrPath) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"top-level JSON must be an object: {path}")
    return value


def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False, **kwargs)


def run_checked(command: list[str], what: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    result = run(command, **kwargs)
    if result.returncode:
        raise RuntimeError(f"{what} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result


def file_identity(path: Path) -> dict[str, Any]:
    return {
        "filename": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_path(path),
    }


def require_identity(path: Path, expected: dict[str, Any], what: str) -> dict[str, Any]:
    """Compare a file against a locked filename/size/sha256 triple."""
    observed = file_identity(path)
    mismatched = [
        key for key in ("filename", "size_bytes", "sha256") if observed[key] != expected.get(key)
    ]
    if mismatched:
        raise RuntimeError(
            f"{what} does not match its lock on {', '.join(mismatched)}; observed={observed}"
        )
    return observed
