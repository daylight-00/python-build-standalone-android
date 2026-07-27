"""Assembly of the three archive flavors.

The order is fixed and each flavor is derived from the verified one above it:

    verified input -> full -> install_only -> install_only_stripped

No flavor is ever built from a separate staging tree, so ``install_only`` can
always be reconstructed from ``full`` and compared member for member.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .archive import (
    copy_entry,
    copy_tree_contents,
    extract_tar_zst,
    safe_extract_tar,
    tree_manifest,
    write_tar_gz,
    write_tar_zst,
)
from .elf import elf_objects, is_elf, set_relative_runpaths, strip_object, tool_identity
from .launcher import build_launcher
from .pip_surface import install_bundled_pip
from .python_json import build_python_json
from .runtime_metadata import apply_consumer_overlay, sysconfig_vars_json
from .targets import ROOT, Build
from .toolchain import Toolchain
from .utils import file_identity, read_json_object, require_identity, sha256_path, write_json

RECORDS = "build/records"

# Upstream puts per-component license texts in python/licenses/, which is a
# sibling of python/install/ and so does not survive the install-only
# projection — the flavor most consumers actually take ships without them.
# Placing them inside the prefix instead lands them at python/licenses/ in
# install-only, the same relative path upstream uses, and keeps them in every
# flavor.
LICENSES = "licenses"
LICENSE_SOURCE = ROOT / "licenses"


@dataclass(frozen=True)
class PrefixSource:
    """An install prefix ready to be packaged, and where it came from.

    The two producers differ only here. The upstream-derived build extracts a
    prefix out of the official package and has to supply an interpreter, because
    that package is embedding-oriented and ships none. The source build produces
    its own prefix with CPython's own interpreter already in it.
    """

    prefix: Path
    python_version: str
    python_mm: str
    record: dict[str, Any]
    retained: Path | None = None
    needs_launcher: bool = True


@dataclass(frozen=True)
class BuildContext:
    build: Build
    toolchain: Toolchain
    tag: str
    output_dir: Path

    @property
    def lock(self) -> dict[str, Any]:
        return read_json_object(self.build.input_lock_path())

    def stem(self, python_version: str) -> str:
        return self.build.artifact_stem(python_version, self.tag)


def _install_launcher(install: Path, launcher: Path, python_mm: str) -> list[dict[str, str]]:
    bindir = install / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    executable = bindir / f"python{python_mm}"
    shutil.copyfile(launcher, executable)
    os.chmod(executable, 0o755)
    aliases: list[dict[str, str]] = []
    for name in ("python3", "python"):
        alias = bindir / name
        if alias.exists() or alias.is_symlink():
            alias.unlink()
        os.symlink(f"python{python_mm}", alias)
        aliases.append({"path": f"bin/{name}", "target": f"python{python_mm}"})
    return aliases


def _install_licenses(install: Path) -> dict[str, Any]:
    """Copy the per-component license texts into the prefix."""
    manifest = LICENSE_SOURCE / "components.json"
    if not manifest.is_file():
        raise RuntimeError(f"license manifest is missing: {manifest}")
    target = install / LICENSES
    target.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for source in sorted(LICENSE_SOURCE.glob("LICENSE.*.txt")):
        shutil.copyfile(source, target / source.name)
        os.chmod(target / source.name, 0o644)
        rows.append({"path": f"{LICENSES}/{source.name}", "sha256": sha256_path(source)})
    shutil.copyfile(manifest, target / manifest.name)
    os.chmod(target / manifest.name, 0o644)

    declared = {
        component["file"]
        for component in read_json_object(manifest)["components"]
        if component.get("file")
    }
    shipped = {Path(row["path"]).name for row in rows}
    if declared != shipped:
        raise RuntimeError(
            f"license manifest and payload disagree: "
            f"declared-only={sorted(declared - shipped)} shipped-only={sorted(shipped - declared)}"
        )
    return {
        "schema_version": 1,
        "root": LICENSES,
        "manifest": f"{LICENSES}/{manifest.name}",
        "files": rows,
    }


def _copy_retained_material(retained: Path, build: Path) -> None:
    """Keep the input material the archive should carry with it."""
    target = build / "upstream"
    target.mkdir(parents=True, exist_ok=True)
    for child in sorted(retained.iterdir(), key=lambda item: item.name):
        copy_entry(child, target / child.name)


def prepare_upstream_prefix(context: BuildContext, archive: Path, workspace: Path) -> PrefixSource:
    """Extract the official Android package into a prefix ready to package."""
    lock = context.lock
    observed = require_identity(archive, lock["archive"], "official Android package")

    extracted = workspace / "upstream"
    safe_extract_tar(archive, extracted)
    prefix = extracted / "prefix"
    if not prefix.is_dir():
        raise RuntimeError("official package is missing prefix/")
    if (prefix / "bin").exists():
        # The embedding package ships no executables. A bin/ payload would change
        # both the launcher story and the license obligations.
        raise RuntimeError("official package unexpectedly contains prefix/bin")

    # The exact input, and every file it carried outside the prefix, travel with
    # the archive so a consumer can see what it was derived from.
    retained = workspace / "retained"
    (retained / "package").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(archive, retained / "package" / archive.name)
    metadata = retained / "extracted-metadata"
    metadata.mkdir(parents=True, exist_ok=True)
    for child in sorted(extracted.iterdir(), key=lambda item: item.name):
        if child.name != "prefix":
            copy_entry(child, metadata / child.name)

    return PrefixSource(
        prefix=prefix,
        python_version=lock["python"]["version"],
        python_mm=lock["python"]["major_minor"],
        record={
            "official_input": observed,
            "lock": context.build.input_lock,
            "producer": lock["producer"],
        },
        retained=retained,
        needs_launcher=True,
    )


def assemble_full(context: BuildContext, source: PrefixSource) -> dict[str, Any]:
    """Build the canonical ``full`` archive from a prepared install prefix."""
    build = context.build
    python_version = source.python_version
    python_mm = source.python_mm

    context.output_dir.mkdir(parents=True, exist_ok=True)
    artifact = context.output_dir / f"{context.stem(python_version)}-full.tar.zst"

    with tempfile.TemporaryDirectory(prefix="pbsa-full-") as tmp:
        workspace = Path(tmp)
        prefix = source.prefix

        python_root = workspace / "full/python"
        install = python_root / "install"
        build_root = python_root / "build"
        copy_tree_contents(prefix, install)

        # Only the upstream-derived build needs one. The source build ships
        # CPython's own interpreter, so there is no project launcher and
        # therefore no launcher record — absence says it better than a record
        # asserting that nothing was supplied.
        launcher_record: dict[str, Any] | None = None
        if source.needs_launcher:
            launcher_binary = workspace / "launcher/python"
            launcher_record = build_launcher(
                prefix, launcher_binary, toolchain=context.toolchain, python_mm=python_mm
            )
            launcher_record["aliases"] = _install_launcher(install, launcher_binary, python_mm)

        overlay = apply_consumer_overlay(install, python_mm=python_mm, host_triple=build.triple)
        config_vars_source = sysconfig_vars_json(install, python_mm)
        pip = install_bundled_pip(install, python_mm)
        licenses = _install_licenses(install)
        runpaths = set_relative_runpaths(
            install, str(context.toolchain.patchelf), str(context.toolchain.readelf)
        )

        if source.retained is not None:
            _copy_retained_material(source.retained, build_root)
        records = build_root / "records"
        write_json(records / "input.json", {"schema_version": 1, **source.record})
        if launcher_record is not None:
            write_json(records / "launcher.json", {"schema_version": 1, **launcher_record})
        write_json(
            records / "mutations.json",
            {
                "schema_version": 1,
                "elf_runpath": runpaths,
                "runtime_metadata": overlay,
                "pip_surface": pip,
                "licenses": licenses,
            },
        )
        write_json(
            records / "toolchain.json",
            {"schema_version": 1, **context.toolchain.identity()},
        )

        python_json = build_python_json(
            install,
            build,
            python_version=python_version,
            python_mm=python_mm,
            config_vars_source=config_vars_source,
            readelf=str(context.toolchain.readelf),
        )
        write_json(python_root / "PYTHON.json", python_json)

        manifest_path = records / "member-manifest.json"
        excluded = {f"python/{RECORDS}/member-manifest.json"}
        write_json(
            manifest_path,
            {
                "schema_version": 1,
                "excluded_paths": sorted(excluded),
                "members": tree_manifest(python_root, exclude=excluded),
            },
        )

        rows = write_tar_zst(python_root, artifact)

    return {
        "schema_version": 1,
        "flavor": "full",
        "target": build.name,
        "python_version": python_version,
        "tag": context.tag,
        "artifact": {**file_identity(artifact), "member_count": len(rows)},
        "launcher": launcher_record["binary"]["sha256"] if launcher_record else None,
        "elf_object_count": len(runpaths),
        "pip_version": pip["wheel"]["version"],
    }


def derive_install_only(context: BuildContext, full_archive: Path) -> dict[str, Any]:
    """Project ``python/install/**`` from a verified full archive to ``python/**``."""
    stem = full_archive.name.removesuffix("-full.tar.zst")
    artifact = context.output_dir / f"{stem}-install_only.tar.gz"
    source_identity = file_identity(full_archive)

    with tempfile.TemporaryDirectory(prefix="pbsa-install-only-") as tmp:
        workspace = Path(tmp)
        tree = extract_tar_zst(full_archive, workspace)
        source = tree / "python/install"
        if not source.is_dir():
            raise RuntimeError("full archive has no python/install/")
        if not (tree / "python/PYTHON.json").is_file() or not (tree / "python/build").is_dir():
            raise RuntimeError("full archive is missing its full-only roots")

        python_root = workspace / "projection/python"
        copy_tree_contents(source, python_root)
        if (python_root / "PYTHON.json").exists() or (python_root / "build").exists():
            raise RuntimeError("full-only metadata leaked into the install-only projection")

        source_rows = tree_manifest(source)
        rows = write_tar_gz(python_root, artifact)

    return {
        "schema_version": 1,
        "flavor": "install_only",
        "target": context.build.name,
        "source_full": source_identity,
        "projection": {
            "source_prefix": "python/install/",
            "target_prefix": "python/",
            "payload_bytes_changed": False,
            "source_member_count": len(source_rows),
            "archive_member_count": len(rows),
        },
        "artifact": {**file_identity(artifact), "member_count": len(rows)},
    }


def derive_stripped(context: BuildContext, install_only_archive: Path) -> dict[str, Any]:
    """Strip every eligible ELF in a verified install-only archive."""
    stem = install_only_archive.name.removesuffix("-install_only.tar.gz")
    artifact = context.output_dir / f"{stem}-install_only_stripped.tar.gz"
    source_identity = file_identity(install_only_archive)
    strip_tool = str(context.toolchain.strip)
    readelf = str(context.toolchain.readelf)

    with tempfile.TemporaryDirectory(prefix="pbsa-stripped-") as tmp:
        workspace = Path(tmp)
        tree = workspace / "tree"
        safe_extract_tar(install_only_archive, tree)
        python_root = tree / "python"
        if not python_root.is_dir():
            raise RuntimeError("install-only archive has no python/ root")

        rows: list[dict[str, Any]] = []
        already_stripped: list[str] = []
        for path in elf_objects(python_root):
            rel = path.relative_to(python_root).as_posix()
            record = strip_object(path, strip_tool=strip_tool, readelf=readelf, display_path=rel)
            record["path"] = rel
            rows.append(record)
            if not record["changed"]:
                already_stripped.append(rel)

        archive_rows = write_tar_gz(python_root, artifact)

    changed = [row for row in rows if row["changed"]]
    return {
        "schema_version": 1,
        "flavor": "install_only_stripped",
        "target": context.build.name,
        "source_install_only": source_identity,
        "strip_tool": tool_identity(strip_tool),
        "elf_object_count": len(rows),
        "stripped_object_count": len(changed),
        "already_stripped_by_producer": already_stripped,
        "objects": rows,
        "artifact": {**file_identity(artifact), "member_count": len(archive_rows)},
    }


def verify_projection(full_archive: Path, install_only_archive: Path) -> dict[str, Any]:
    """Reconstruct install_only from full and compare member identities."""
    with tempfile.TemporaryDirectory(prefix="pbsa-projection-") as tmp:
        workspace = Path(tmp)
        full_tree = extract_tar_zst(full_archive, workspace / "full")
        install_tree = workspace / "install-only"
        safe_extract_tar(install_only_archive, install_tree)

        # tree_manifest() reports paths relative to the root's parent, so the
        # projection rewrites the leading "install" component to "python".
        expected = {
            "python" + row["path"].removeprefix("install"): row
            for row in tree_manifest(full_tree / "python/install")
        }
        observed = {row["path"]: row for row in tree_manifest(install_tree / "python")}

    missing = sorted(set(expected) - set(observed))
    unexpected = sorted(set(observed) - set(expected))
    differing = sorted(
        path
        for path in set(expected) & set(observed)
        if expected[path]["sha256"] != observed[path]["sha256"]
        or expected[path]["type"] != observed[path]["type"]
        or expected[path]["mode"] != observed[path]["mode"]
        or expected[path]["linkname"] != observed[path]["linkname"]
    )
    if missing or unexpected or differing:
        raise RuntimeError(
            f"install_only is not an exact projection of full: "
            f"missing={missing[:5]} unexpected={unexpected[:5]} differing={differing[:5]}"
        )
    return {
        "member_count": len(expected),
        "exact_projection": True,
    }


def stripped_shares_non_elf_bytes(
    install_only_archive: Path, stripped_archive: Path
) -> dict[str, Any]:
    """Confirm the stripped flavor only differs in ELF payloads."""
    with tempfile.TemporaryDirectory(prefix="pbsa-stripped-check-") as tmp:
        workspace = Path(tmp)
        base = workspace / "install-only"
        stripped = workspace / "stripped"
        safe_extract_tar(install_only_archive, base)
        safe_extract_tar(stripped_archive, stripped)
        base_rows = {row["path"]: row for row in tree_manifest(base / "python")}
        stripped_rows = {row["path"]: row for row in tree_manifest(stripped / "python")}
        if set(base_rows) != set(stripped_rows):
            raise RuntimeError("stripped flavor changed the member set")
        changed: list[str] = []
        for path, row in base_rows.items():
            if row["sha256"] == stripped_rows[path]["sha256"]:
                continue
            if not is_elf(base / path):
                raise RuntimeError(f"stripped flavor changed a non-ELF member: {path}")
            changed.append(path)
    return {"member_count": len(base_rows), "changed_elf_members": sorted(changed)}


__all__ = [
    "BuildContext",
    "assemble_full",
    "derive_install_only",
    "derive_stripped",
    "sha256_path",
    "stripped_shares_non_elf_bytes",
    "verify_projection",
]
