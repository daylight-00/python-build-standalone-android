"""Resolve the minimum Android API level the flagship build should target.

``ci-targets.yaml`` states the rule:

    the last API level whose Bionic additions change the CPython build

which is the same as: *the lowest level whose build decisions already match the
highest level the pinned NDK can compile for*. Raising the floor past that point
buys no behaviour and costs device coverage.

That sentence is measured here rather than re-derived. The obvious alternative —
reading ``AC_CHECK_FUNCS`` out of ``configure.ac`` and looking each name up in
Bionic's ``__INTRODUCED_IN`` annotations — has to interpret shell conditionals to
know which probes actually run for Android, which means reimplementing
``configure``. The documented analysis got exactly that wrong once: it recorded
that ``lchmod`` is skipped because its probe sits under ``test "$MACHDEP" !=
linux``, when ``MACHDEP`` is ``android`` and the probe does run.

So each candidate level is configured and the generated ``pyconfig.h`` compared.
That covers every kind of decision configure makes — function probes, header
probes, anything — and needs no table of Bionic's history.

Both inputs are pinned: the CPython source archive by ``config/source``, and the
NDK by ``config/toolchain.lock.json``. The answer follows a CPython bump or an
NDK bump on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFINE = re.compile(r"^\s*#\s*define\s+([A-Za-z_][A-Za-z0-9_]*)\s*(.*?)\s*$")

# Written by configure from the level it was given, so it differs at every
# candidate by construction and says nothing about a build decision.
LEVEL_DEPENDENT = frozenset({"ANDROID_API_LEVEL"})


@dataclass(frozen=True)
class Resolution:
    """The level the rule selects, and what makes it the answer."""

    level: int
    ndk_max: int
    searched: tuple[int, ...]
    # The decisions that appear at `level` and are absent one level below it.
    boundary: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)

    def evidence(self) -> str:
        if not self.boundary:
            return f"nothing changes anywhere in {self.searched[0]}..{self.ndk_max}"
        changes = ", ".join(
            f"{name} {before!r} -> {after!r}"
            for name, (before, after) in sorted(self.boundary.items())
        )
        return f"API {self.level - 1} -> {self.level} changes {changes}"


def decisions(pyconfig: Path) -> dict[str, str]:
    """Every decision configure recorded, as a comparable mapping."""
    values: dict[str, str] = {}
    for line in pyconfig.read_text(encoding="utf-8").splitlines():
        match = DEFINE.match(line)
        if match and match.group(1) not in LEVEL_DEPENDENT:
            values[match.group(1)] = match.group(2)
    if not values:
        raise RuntimeError(f"no defines in {pyconfig}; configure did not finish")
    return values


def difference(
    lower: dict[str, str], higher: dict[str, str]
) -> dict[str, tuple[str | None, str | None]]:
    return {
        name: (lower.get(name), higher.get(name))
        for name in sorted(set(lower) | set(higher))
        if lower.get(name) != higher.get(name)
    }


def resolve(configure_at: Any, *, lowest: int, ndk_max: int) -> Resolution:
    """Binary-search the lowest level that already decides what ``ndk_max`` decides.

    ``configure_at(level)`` returns that level's decisions. Availability only
    grows with the API level, so "matches the top" is false below the answer and
    true at and above it, which is what makes the search valid — and the boundary
    is confirmed afterwards rather than assumed.
    """
    if lowest > ndk_max:
        raise ValueError(f"nothing to search: {lowest} > {ndk_max}")
    top = configure_at(ndk_max)
    searched = [ndk_max]

    low, high = lowest, ndk_max
    while low < high:
        middle = (low + high) // 2
        searched.append(middle)
        if configure_at(middle) == top:
            high = middle
        else:
            low = middle + 1

    boundary: dict[str, tuple[str | None, str | None]] = {}
    if low > lowest:
        searched.append(low - 1)
        boundary = difference(configure_at(low - 1), top)
        if not boundary:
            # Unreachable while the search holds together, which is the point of
            # asserting it: a bisection that landed on a non-boundary would have
            # returned a floor with nothing behind it.
            raise RuntimeError(
                f"API {low - 1} decides the same as {ndk_max}, so {low} is not the "
                f"lowest level that matches. The search assumed availability only "
                f"grows with the API level; this build does not behave that way."
            )
    return Resolution(
        level=low,
        ndk_max=ndk_max,
        searched=tuple(sorted(set(searched))),
        boundary=boundary,
    )


__all__ = ["Resolution", "decisions", "difference", "resolve"]
