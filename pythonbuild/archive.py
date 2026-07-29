"""Safe extraction and deterministic archive writing.

Every archive this project publishes is byte-reproducible: members are ordered
by path, ownership and timestamps are normalized, and nothing outside the single
``python/`` root can be created on extraction.
"""

from __future__ import annotations

import gzip
import os
import posixpath
import shutil
import stat
import tarfile
import tempfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import zstandard

from .utils import sha256_path

ZSTD_LEVEL = 19


def normalize_member_name(name: str) -> str:
    """Reject any member path that could escape the extraction root."""
    if not name or name.startswith("/") or "\\" in name or "\x00" in name:
        raise ValueError(f"unsafe archive path: {name!r}")
    normalized = posixpath.normpath(name)
    # POSIX tar writers commonly emit a leading "." directory member. It marks
    # the extraction root rather than a component to create, so it is kept as a
    # sentinel while every parent-traversal form stays rejected.
    if normalized == ".":
        return normalized
    if normalized == ".." or normalized.startswith("../"):
        raise ValueError(f"unsafe archive path: {name!r}")
    if any(part in {"", ".", ".."} for part in PurePosixPath(normalized).parts):
        raise ValueError(f"unsafe archive component: {name!r}")
    return normalized


def safe_link_target(member: str, target: str) -> bool:
    """True when a symlink resolves to somewhere under the archive root."""
    if not target or target.startswith("/") or "\\" in target or "\x00" in target:
        return False
    resolved = list(PurePosixPath(member).parent.parts)
    root = PurePosixPath(member).parts[0]
    for part in PurePosixPath(target).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not resolved:
                return False
            resolved.pop()
        else:
            resolved.append(part)
    return bool(resolved) and resolved[0] == root


def safe_extract_tar(
    archive: Path, destination: Path, mode: Literal["r:*", "r:"] = "r:*"
) -> list[dict[str, Any]]:
    destination.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    names: set[str] = set()
    with tarfile.open(archive, mode) as tf:
        members: list[tuple[tarfile.TarInfo, str]] = []
        for member in tf.getmembers():
            name = normalize_member_name(member.name)
            if name in names:
                raise ValueError(f"duplicate archive member: {name}")
            names.add(name)
            if name == "." and not member.isdir():
                raise ValueError("archive root marker must be a directory")
            if member.islnk() or member.isdev() or member.isfifo():
                raise ValueError(f"forbidden archive member type: {name}")
            if not (member.isdir() or member.isfile() or member.issym()):
                raise ValueError(f"unsupported archive member type: {name}")
            if member.issym() and not safe_link_target(name, member.linkname):
                raise ValueError(f"unsafe symlink: {name} -> {member.linkname}")
            members.append((member, name))
        for member, name in members:
            target = destination / name
            permission = stat.S_IMODE(member.mode)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                os.chmod(target, permission)
                kind, digest = "directory", None
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tf.extractfile(member)
                if source is None:
                    raise ValueError(f"cannot read archive member: {name}")
                with target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                os.chmod(target, permission)
                kind, digest = "file", sha256_path(target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(member.linkname, target)
                kind, digest = "symlink", None
            rows.append(
                {
                    "path": name,
                    "type": kind,
                    "mode": f"{permission:04o}",
                    "size": member.size,
                    "sha256": digest,
                    "linkname": member.linkname if member.issym() else None,
                }
            )
    return rows


def newest_member_mtime(archive: Path) -> int:
    """The newest timestamp inside an archive.

    Used as SOURCE_DATE_EPOCH so that anything a compiler stamps with the
    current time — ``__DATE__`` and ``__TIME__``, OpenSSL's build banner —
    becomes a function of the pinned input instead of when the build ran. It is
    derived rather than invented so it needs no constant to keep in step.
    """
    with tarfile.open(archive) as tf:
        return int(max((member.mtime for member in tf.getmembers()), default=0))


def copy_entry(source: Path, target: Path) -> None:
    metadata = source.lstat()
    permission = stat.S_IMODE(metadata.st_mode)
    if stat.S_ISDIR(metadata.st_mode):
        target.mkdir(parents=True, exist_ok=True)
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            copy_entry(child, target / child.name)
        os.chmod(target, permission)
    elif stat.S_ISREG(metadata.st_mode):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target, follow_symlinks=False)
        os.chmod(target, permission)
    elif stat.S_ISLNK(metadata.st_mode):
        linkname = os.readlink(source)
        if linkname.startswith("/"):
            raise ValueError(f"absolute symlink forbidden: {source} -> {linkname}")
        # tree_manifest() performs the authoritative root-aware check later.
        target.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(linkname, target)
    else:
        raise ValueError(f"unsupported filesystem entry: {source}")


def copy_tree_contents(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in sorted(source.iterdir(), key=lambda item: item.name):
        copy_entry(child, target / child.name)
    os.chmod(target, stat.S_IMODE(source.lstat().st_mode))


def tree_manifest(root: Path, *, exclude: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Describe every member of ``root``, keyed by its path inside the archive."""
    excluded = set(exclude)
    rows: list[dict[str, Any]] = []
    entries = sorted(
        [root, *root.rglob("*")],
        key=lambda item: item.relative_to(root.parent).as_posix(),
    )
    for path in entries:
        rel = path.relative_to(root.parent).as_posix()
        if rel in excluded:
            continue
        metadata = path.lstat()
        permission = stat.S_IMODE(metadata.st_mode)
        linkname = None
        if stat.S_ISDIR(metadata.st_mode):
            kind, size, digest = "directory", 0, None
        elif stat.S_ISREG(metadata.st_mode):
            kind, size, digest = "file", metadata.st_size, sha256_path(path)
        elif stat.S_ISLNK(metadata.st_mode):
            linkname = os.readlink(path)
            if not safe_link_target(rel, linkname):
                raise ValueError(f"unsafe symlink in tree: {rel} -> {linkname}")
            kind, size, digest = "symlink", 0, None
        else:
            raise ValueError(f"unsupported tree entry: {path}")
        rows.append(
            {
                "path": rel,
                "type": kind,
                "mode": f"{permission:04o}",
                "size": size,
                "sha256": digest,
                "linkname": linkname,
            }
        )
    paths = [row["path"] for row in rows]
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate tree member")
    return rows


def _tar_info(row: dict[str, Any]) -> tarfile.TarInfo:
    info = tarfile.TarInfo(row["path"])
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = 0
    info.mode = int(row["mode"], 8)
    if row["type"] == "directory":
        info.type = tarfile.DIRTYPE
        info.size = 0
    elif row["type"] == "symlink":
        info.type = tarfile.SYMTYPE
        info.linkname = row["linkname"]
        info.size = 0
    else:
        info.type = tarfile.REGTYPE
        info.size = row["size"]
    return info


def write_uncompressed_tar(
    tree_root: Path, output: Path, rows: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    rows = rows if rows is not None else tree_manifest(tree_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w", format=tarfile.PAX_FORMAT) as tf:
        for row in rows:
            info = _tar_info(row)
            source = tree_root.parent / row["path"]
            if row["type"] == "file":
                with source.open("rb") as stream:
                    tf.addfile(info, stream)
            else:
                tf.addfile(info)
    return rows


def write_tar_zst(tree_root: Path, output: Path) -> list[dict[str, Any]]:
    # The library rather than the zstd CLI: the CLI's version is whatever the
    # host happens to have, and two versions compress identical input to
    # different bytes. This one is pinned by uv.lock. Single-threaded because
    # multi-threaded zstd output depends on how the work was divided.
    compressor = zstandard.ZstdCompressor(level=ZSTD_LEVEL, threads=0)
    with tempfile.TemporaryDirectory(prefix="pbsa-tar-") as tmp:
        tar_path = Path(tmp) / "artifact.tar"
        rows = write_uncompressed_tar(tree_root, tar_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tar_path.open("rb") as source, output.open("wb") as target:
            compressor.copy_stream(source, target)
    return rows


def write_tar_gz(tree_root: Path, output: Path) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="pbsa-tar-") as tmp:
        tar_path = Path(tmp) / "artifact.tar"
        rows = write_uncompressed_tar(tree_root, tar_path)
        with (
            tar_path.open("rb") as source,
            output.open("wb") as raw,
            gzip.GzipFile(
                filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9
            ) as compressed,
        ):
            shutil.copyfileobj(source, compressed)
    return rows


def extract_tar_zst(archive: Path, destination: Path) -> Path:
    """Decompress and extract a .tar.zst, returning the extracted tree root."""
    destination.mkdir(parents=True, exist_ok=True)
    tar_path = destination / "archive.tar"
    decompressor = zstandard.ZstdDecompressor()
    with archive.open("rb") as source, tar_path.open("wb") as target:
        decompressor.copy_stream(source, target)
    tree = destination / "tree"
    safe_extract_tar(tar_path, tree, "r:")
    tar_path.unlink()
    return tree
