"""ELF inspection, RUNPATH normalization, and recorded stripping.

Every ELF object in an install prefix gets exactly one relative ``DT_RUNPATH``
pointing from its own directory to ``lib``. No ``LD_LIBRARY_PATH`` and no
bootstrap re-exec is required to load the distribution, and the mutation must
leave ``DT_NEEDED``, SONAME, architecture, ELF kind, and the 16 KiB
program-segment alignment untouched.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .utils import run, sha256_path

DYNAMIC_RE = re.compile(r"\((NEEDED|SONAME|RPATH|RUNPATH)\).*\[(.*)\]")
PAGE_SIZE = 16384

REMOVABLE_SECTIONS = {".symtab", ".strtab"}
REMOVABLE_SECTION_PREFIXES = (".debug", ".zdebug")


def is_elf(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    with path.open("rb") as stream:
        return stream.read(4) == b"\x7fELF"


def elf_objects(root: Path) -> list[Path]:
    return [path for path in sorted(root.rglob("*")) if is_elf(path)]


def resolve_tool(tool: str) -> Path:
    """Resolve a tool to an absolute path without dereferencing its alias.

    LLVM multi-call binaries pick their interface from ``argv[0]``: ``readelf``
    may be a symlink to ``llvm-readobj`` and ``llvm-strip`` to ``llvm-objcopy``.
    Following the symlink before execution silently changes both command-line
    and output semantics, so only the recorded identity may look through it.
    """
    candidate = Path(tool).expanduser()
    if candidate.is_absolute() or candidate.parent != Path("."):
        invocation = (candidate if candidate.is_absolute() else Path.cwd() / candidate).absolute()
        if not invocation.is_file():
            raise FileNotFoundError(f"tool not found: {tool}")
        return invocation
    found = shutil.which(tool)
    if not found:
        raise FileNotFoundError(f"tool not found on PATH: {tool}")
    return Path(found).absolute()


def elf_surface(path: Path, readelf: str = "readelf") -> dict[str, Any]:
    """The parts of an ELF a mutation must not change."""
    header = run([readelf, "-h", str(path)])
    dynamic = run([readelf, "-d", str(path)])
    loads = run([readelf, "-lW", str(path)])
    if header.returncode or dynamic.returncode or loads.returncode:
        raise RuntimeError(
            f"readelf failed for {path}: {header.stderr}{dynamic.stderr}{loads.stderr}"
        )
    kind = machine = ""
    for line in header.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("Type:"):
            kind = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Machine:"):
            machine = stripped.split(":", 1)[1].strip()
    tags: dict[str, list[str]] = {key: [] for key in ("NEEDED", "SONAME", "RPATH", "RUNPATH")}
    for line in dynamic.stdout.splitlines():
        match = DYNAMIC_RE.search(line)
        if match:
            tags[match.group(1)].append(match.group(2))
    alignments: list[int] = []
    for line in loads.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("LOAD "):
            with contextlib.suppress(ValueError):
                alignments.append(int(stripped.split()[-1], 0))
    return {
        "sha256": sha256_path(path),
        "size": path.stat().st_size,
        "type": kind,
        "machine": machine,
        "needed": tags["NEEDED"],
        "soname": tags["SONAME"],
        "rpath": tags["RPATH"],
        "runpath": tags["RUNPATH"],
        "load_alignments": alignments,
    }


def relative_runpath(object_path: Path, libdir: Path) -> str:
    rel = os.path.relpath(libdir, object_path.parent)
    return "$ORIGIN" if rel == "." else "$ORIGIN/" + rel.replace(os.sep, "/")


def alignment_policy(before: list[int], after: list[int]) -> dict[str, Any]:
    before_ok = bool(before) and all(value == PAGE_SIZE for value in before)
    after_ok = bool(after) and all(value == PAGE_SIZE for value in after)
    return {
        "before_load_count": len(before),
        "after_load_count": len(after),
        "before_all_16k": before_ok,
        "after_all_16k": after_ok,
        "load_count_not_reduced": len(after) >= len(before),
        "preserved": before_ok and after_ok and len(after) >= len(before),
    }


def set_relative_runpaths(
    install: Path, patchelf: str = "patchelf", readelf: str = "readelf"
) -> list[dict[str, Any]]:
    """Give every ELF under ``install`` one relative RUNPATH to ``install/lib``."""
    libdir = install / "lib"
    objects = elf_objects(install)
    if not objects:
        raise RuntimeError("no ELF objects found in the install tree")
    help_result = run([patchelf, "--help"])
    if "--page-size" not in (help_result.stdout + help_result.stderr):
        raise RuntimeError("patchelf lacks the required --page-size support")

    rows: list[dict[str, Any]] = []
    for path in objects:
        rel = path.relative_to(install).as_posix()
        before = elf_surface(path, readelf)
        expected = relative_runpath(path, libdir)
        command = [patchelf, "--page-size", str(PAGE_SIZE), "--set-rpath", expected, str(path)]
        mutation = run(command)
        if mutation.returncode:
            raise RuntimeError(f"patchelf failed for {rel}: {mutation.stderr.strip()}")
        after = elf_surface(path, readelf)
        alignment = alignment_policy(before["load_alignments"], after["load_alignments"])
        exact = (
            before["type"] == after["type"]
            and before["machine"] == after["machine"]
            and before["needed"] == after["needed"]
            and before["soname"] == after["soname"]
            and before["rpath"] == after["rpath"]
            and after["runpath"] == [expected]
            and alignment["preserved"]
        )
        if not exact:
            raise RuntimeError(f"RUNPATH mutation changed more than the RUNPATH: {rel}")
        rows.append(
            {
                "path": rel,
                # Recorded without host paths: this ships inside the archive.
                "command": [Path(patchelf).name, *command[1:-1], f"<install>/{rel}"],
                "expected_runpath": expected,
                "before": before,
                "after": after,
                "alignment_policy": alignment,
            }
        )
    return rows


def section_names(path: Path, readelf: str = "readelf") -> list[str]:
    readelf_path = resolve_tool(readelf)
    result = run([str(readelf_path), "-SW", str(path)])
    if result.returncode:
        raise RuntimeError(f"readelf section census failed for {path}: {result.stderr.strip()}")
    names: list[str] = []
    for line in result.stdout.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("[") or "]" not in stripped:
            continue
        fields = stripped.split("]", 1)[1].strip().split()
        if fields and fields[0].startswith("."):
            names.append(fields[0])
    return names


def section_census(path: Path, readelf: str = "readelf") -> dict[str, Any]:
    sections = section_names(path, readelf)
    removable = [
        name
        for name in sections
        if name in REMOVABLE_SECTIONS or name.startswith(REMOVABLE_SECTION_PREFIXES)
    ]
    return {
        "sections": sections,
        "removable_sections": removable,
        "has_symtab": ".symtab" in sections,
        "has_strtab": ".strtab" in sections,
        "debug_sections": [
            name for name in sections if name.startswith(REMOVABLE_SECTION_PREFIXES)
        ],
        "eligible": bool(removable),
    }


def tool_identity(tool: str) -> dict[str, Any]:
    """Identify a tool by name, content, and version — never by host path."""
    invocation = resolve_tool(tool)
    result = run([str(invocation), "--version"])
    return {
        "name": invocation.name,
        "canonical_name": invocation.resolve().name,
        "is_symlink": invocation.is_symlink(),
        "sha256": sha256_path(invocation),
        "size_bytes": invocation.stat().st_size,
        "version": result.stdout.strip().splitlines()[:1],
    }


def strip_object(
    path: Path, *, strip_tool: str, readelf: str = "readelf", display_path: str | None = None
) -> dict[str, Any]:
    """Strip one object, recording its full before/after identity."""
    strip_path = resolve_tool(strip_tool)
    before_surface = elf_surface(path, readelf)
    before_sections = section_census(path, readelf)
    before_hash = sha256_path(path)
    command = [str(strip_path), "--strip-unneeded", str(path)]
    result: subprocess.CompletedProcess[str] = run(command)
    if result.returncode:
        raise RuntimeError(f"strip failed for {path}: {result.stderr.strip()}")
    after_surface = elf_surface(path, readelf)
    after_sections = section_census(path, readelf)
    preserved = all(
        before_surface[key] == after_surface[key]
        for key in ("type", "machine", "needed", "soname", "rpath", "runpath", "load_alignments")
    )
    if not preserved:
        raise RuntimeError(f"strip changed the dynamic or alignment surface: {path}")
    after_hash = sha256_path(path)
    recorded = display_path or path.name
    return {
        "command": [strip_path.name, "--strip-unneeded", f"<install>/{recorded}"],
        "before": {
            "sha256": before_hash,
            "size_bytes": before_surface["size"],
            "surface": before_surface,
            "section_census": before_sections,
        },
        "after": {
            "sha256": after_hash,
            "size_bytes": after_surface["size"],
            "surface": after_surface,
            "section_census": after_sections,
        },
        "changed": before_hash != after_hash,
        "removable_sections_removed": not after_sections["eligible"],
    }
