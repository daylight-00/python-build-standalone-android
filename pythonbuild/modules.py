"""What extension modules a distribution is supposed to carry.

Upstream keeps a hand-written table of expected modules per Python version and
per platform, and validates every distribution against it. A table like that has
to be edited whenever CPython changes, and this project deliberately leaves that
class of decision to python.org — the same way it takes the dependency set and
the ``upstream`` API floor from whatever the official package was built with.

So the expectation is derived instead, from the one place that already knows:
CPython's ``configure`` records its per-module decision in the ``sysconfigdata``
the distribution ships.

    MODULE_<NAME>_STATE   yes | missing | disabled | n/a
    MODSHARED_NAMES       the modules built as shared objects
    MODBUILT_NAMES        the modules linked into the interpreter

Nothing here needs updating when a module is added, dropped, or moved between
shared and builtin, and an ``extended`` build that turns readline and Tk on is
held to them the moment ``configure`` says ``yes``.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STATE_PREFIX = "MODULE_"
STATE_SUFFIX = "_STATE"
BUILT = "yes"


@dataclass(frozen=True)
class ModuleExpectations:
    """CPython's own account of which modules this build produced."""

    states: dict[str, str]
    shared: frozenset[str]
    builtin: frozenset[str]
    ext_suffix: str

    @property
    def built(self) -> frozenset[str]:
        """Every module ``configure`` said it built, however it was linked."""
        return frozenset(name for name, state in self.states.items() if state == BUILT)

    @property
    def unavailable(self) -> dict[str, str]:
        """The modules ``configure`` did not build, and what it said about each."""
        return {name: state for name, state in self.states.items() if state != BUILT}


def _module_name(variable: str) -> str:
    return variable[len(STATE_PREFIX) : -len(STATE_SUFFIX)].lower()


def build_time_vars(text: str) -> dict[str, Any]:
    """The ``build_time_vars`` literal out of a sysconfigdata module."""
    match = re.search(r"build_time_vars\s*=\s*(\{.*?\})\s*$", text, re.S | re.M)
    if match:
        with_literal = ast.literal_eval(match.group(1))
        if isinstance(with_literal, dict):
            return with_literal
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "build_time_vars":
                values = ast.literal_eval(node.value)
                if isinstance(values, dict):
                    return values
    raise RuntimeError("build_time_vars not found in sysconfigdata")


def sysconfigdata_path(stdlib: Path) -> Path:
    candidates = sorted(stdlib.glob("_sysconfigdata*.py"))
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected exactly one sysconfigdata under {stdlib}, got {candidates}"
        )
    return candidates[0]


def expectations(stdlib: Path) -> ModuleExpectations:
    """Read what ``configure`` decided, from the distribution's own metadata."""
    values = build_time_vars(sysconfigdata_path(stdlib).read_text(encoding="utf-8"))
    states = {
        _module_name(str(key)): str(value)
        for key, value in values.items()
        if str(key).startswith(STATE_PREFIX) and str(key).endswith(STATE_SUFFIX)
    }
    if not states:
        raise RuntimeError("sysconfigdata records no MODULE_*_STATE decisions")
    return ModuleExpectations(
        states=states,
        shared=frozenset(str(values.get("MODSHARED_NAMES", "")).split()),
        builtin=frozenset(str(values.get("MODBUILT_NAMES", "")).split()),
        ext_suffix=str(values["EXT_SUFFIX"]),
    )


def shipped_shared(stdlib: Path, ext_suffix: str) -> frozenset[str]:
    dynload = stdlib / "lib-dynload"
    if not dynload.is_dir():
        return frozenset()
    return frozenset(
        path.name[: -len(ext_suffix)]
        for path in dynload.glob(f"*{ext_suffix}")
        if path.is_file()
    )


def check_shared_modules(stdlib: Path) -> dict[str, Any]:
    """Every module built as a shared object must be in the distribution, and no other.

    This is the half that can be checked without running the interpreter, so it
    runs during the build. The other half — that each of them, and each builtin,
    actually imports — needs a device, and is what ``qualify.py`` records.
    """
    expected = expectations(stdlib)
    shipped = shipped_shared(stdlib, expected.ext_suffix)

    missing = sorted(expected.shared - shipped)
    unexpected = sorted(shipped - expected.shared)
    if missing or unexpected:
        raise RuntimeError(
            "the shared extension modules in this distribution are not the ones "
            "CPython says it built.\n"
            f"  built but not shipped: {missing}\n"
            f"  shipped but not built: {unexpected}\n"
            "Both sets come from the distribution's own sysconfigdata "
            "(MODSHARED_NAMES), so a difference means the packaging lost or "
            "gained a module."
        )
    return {
        "source": "sysconfigdata",
        "shared_module_count": len(shipped),
        "builtin_module_count": len(expected.built - expected.shared),
        "built": sorted(expected.built),
        "unavailable": dict(sorted(expected.unavailable.items())),
    }


__all__ = [
    "ModuleExpectations",
    "build_time_vars",
    "check_shared_modules",
    "expectations",
    "shipped_shared",
    "sysconfigdata_path",
]
