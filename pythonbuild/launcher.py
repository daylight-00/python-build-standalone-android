"""Build the interpreter frontend.

The official Android package is embedding-oriented and ships no interpreter
executable, so one is compiled against the package's own ``libpython`` and
headers. It is an ordinary ``Py_BytesMain`` frontend with a relative RUNPATH and
nothing else: no loader bootstrap, no CA policy, no argument rewriting.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .elf import PAGE_SIZE, elf_surface
from .targets import ROOT
from .toolchain import Toolchain
from .utils import run_checked, sha256_path

SOURCE = ROOT / "cpython-android/python.c"
RUNPATH = "$ORIGIN/../lib"


def portable_command(command: list[str], replacements: dict[str, str]) -> list[str]:
    """Rewrite host-specific paths out of a command before it is recorded.

    The recorded command ships inside the archive, so it must name neither the
    build machine's directories nor a temporary workspace: those would leak host
    layout to every consumer and make the archive unreproducible.
    """
    ordered = sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True)
    rewritten: list[str] = []
    for token in command:
        for real, placeholder in ordered:
            token = token.replace(real, placeholder)
        rewritten.append(token)
    return rewritten


def build_launcher(
    prefix: Path, output: Path, *, toolchain: Toolchain, python_mm: str
) -> dict[str, Any]:
    """Compile the launcher against an extracted upstream ``prefix``."""
    header = prefix / f"include/python{python_mm}/Python.h"
    library = prefix / f"lib/libpython{python_mm}.so"
    for required in (header, library):
        if not required.is_file():
            raise RuntimeError(
                f"upstream prefix is missing {required.name}: {required}"
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(toolchain.clang),
        "-fPIE",
        "-pie",
        "-O2",
        "-Wall",
        "-Wextra",
        "-pthread",
        f"-Wl,-z,max-page-size={PAGE_SIZE}",
        f"-Wl,-z,common-page-size={PAGE_SIZE}",
        f"-I{prefix / f'include/python{python_mm}'}",
        str(SOURCE),
        f"-L{prefix / 'lib'}",
        f"-lpython{python_mm}",
        "-ldl",
        "-lm",
        "-llog",
        "-Wl,--enable-new-dtags",
        f"-Wl,-rpath,{RUNPATH}",
        "-o",
        str(output),
    ]
    run_checked(command, "launcher compilation")

    run_checked(
        [
            str(toolchain.patchelf),
            "--page-size",
            str(PAGE_SIZE),
            "--set-rpath",
            RUNPATH,
            str(output),
        ],
        "launcher RUNPATH normalization",
    )

    surface = elf_surface(output, str(toolchain.readelf))
    if surface["runpath"] != [RUNPATH]:
        raise RuntimeError(
            f"launcher RUNPATH is {surface['runpath']}, expected [{RUNPATH}]"
        )
    if not surface["load_alignments"] or any(
        value != PAGE_SIZE for value in surface["load_alignments"]
    ):
        raise RuntimeError(
            f"launcher LOAD segments are not 16 KiB aligned: {surface['load_alignments']}"
        )

    return {
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": sha256_path(SOURCE),
        "command": portable_command(
            command,
            {
                str(toolchain.clang): Path(toolchain.clang).name,
                str(output): "<output>",
                str(prefix): "<upstream-prefix>",
                str(SOURCE): SOURCE.relative_to(ROOT).as_posix(),
            },
        ),
        "binary": {"sha256": sha256_path(output), "size_bytes": output.stat().st_size},
        "runpath": RUNPATH,
        "load_alignments": surface["load_alignments"],
        "toolchain": {
            "ndk_revision": toolchain.revision,
            "compiler": Path(toolchain.clang).name,
        },
    }
