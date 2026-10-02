"""What a release without a device receipt can honestly say about itself.

A qualification receipt is evidence only for the bytes it names, and that does
not change here: nothing below claims an older receipt covers a newer build.

An unattended release goes out without one, and the claim it makes depends on
how far it is from the last build a device ran. If the only thing that differs
is the pinned CPython input, then every part of the distribution this project is
responsible for — the launcher, the loader normalization, the metadata overlay,
the curation, the license set — is the same code that was qualified, and the
residual risk is upstream's. That is the strongest claim available without a
device, and it is the only one that is a *waiver*: ``UPSTREAM_ONLY``.

If anything else differs, the risk is this project's own and nothing can be said
about it, but the release is still published, on the edge channel, saying so:
``CHANGED``. And a build no device has ever run has no earlier build to stand on
at all: ``NEVER_RUN``. The three are recorded, and the release notes say which.

The polarity matters. The set below names what is *allowed* to differ, and
everything else differing drops the claim to ``CHANGED``, so a file nobody
thought about fails closed. Two things are deliberately outside it:

``config/toolchain.lock.json``
    An NDK or patchelf bump changes every compiled byte and can move the API
    floor. That is upstream in origin but not in effect.

anything under ``pythonbuild/``, the scripts, ``licenses/``, ``uv.lock``
    This project's own packaging, and the pinned tools that shape its output.
"""

from __future__ import annotations

import copy
import fnmatch
from dataclasses import dataclass
from typing import Any

# What an unqualified release stands on, strongest claim first.
UPSTREAM_ONLY = "upstream-only"
CHANGED = "changed"
NEVER_RUN = "never-run"
BASES = (UPSTREAM_ONLY, CHANGED, NEVER_RUN)

# Allowed to differ between the qualified commit and the one being released.
# Everything here either is a pin that follows CPython, or cannot reach a byte
# of a distribution.
WAIVABLE = (
    "config/source/cpython-*.lock.json",
    "config/upstream/cpython-*.lock.json",
    # The dependency set is not chosen here: its versions and build numbers are
    # the ones the pinned CPython's Android/android.py names, so it moves with
    # the CPython pin rather than independently.
    "config/source/dependency-recipes.lock.json",
    # Receipts accumulate; a new one cannot invalidate a build. fnmatch's `*`
    # crosses `/`, so this covers the per-tag directories too.
    "qualification/*",
    # Prose.
    "docs/*",
    "*.md",
)


@dataclass(frozen=True)
class Waiver:
    """The evidence an unattended release stands on, or why it has none."""

    previous_tag: str
    previous_api_level: int
    declared_api_level: int
    blocking: tuple[str, ...]
    waived: tuple[str, ...]

    @property
    def granted(self) -> bool:
        return not self.blocking and self.previous_api_level == self.declared_api_level

    @property
    def basis(self) -> str:
        return UPSTREAM_ONLY if self.granted else CHANGED

    def reason(self) -> str:
        if self.previous_api_level != self.declared_api_level:
            return (
                f"the API floor moved from {self.previous_api_level} to "
                f"{self.declared_api_level} since {self.previous_tag}, which changes "
                f"which devices can run this build"
            )
        if self.blocking:
            shown = ", ".join(self.blocking[:5])
            more = (
                f" and {len(self.blocking) - 5} more" if len(self.blocking) > 5 else ""
            )
            return f"this project's own files changed since {self.previous_tag}: {shown}{more}"
        return (
            f"nothing but the pinned input changed since {self.previous_tag}, whose "
            f"artifacts a device ran at API {self.previous_api_level}"
        )


def is_waivable(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in WAIVABLE)


def pins_only(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Whether two parsed ``ci-targets.yaml`` differ in nothing but the pins.

    The file is not waivable as a path: it says what each build compiles in, so a
    changed ``openssldir`` or producer changes bytes the same way a code change
    does. What follows CPython is the input lock a build reads and the API floor
    measured from it; the floor's level is compared on its own, so blanking it here
    does not let a moved floor through.
    """

    def stripped(document: dict[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(document)
        for triple in result.get("android", {}).values():
            for build in triple.get("build_options", {}).values():
                build.pop("input_lock", None)
                build.get("android_api", {}).pop("level", None)
        return result

    return stripped(before) == stripped(after)


def assess(
    *,
    previous_tag: str,
    previous_api_level: int,
    declared_api_level: int,
    changed_paths: list[str],
    also_waivable: frozenset[str] = frozenset(),
) -> Waiver:
    """Decide whether the difference since ``previous_tag`` is upstream's alone.

    ``also_waivable`` names paths a caller has shown, by looking inside them, to
    have moved only as far as the pins.
    """

    def allowed(path: str) -> bool:
        return is_waivable(path) or path in also_waivable

    blocking = tuple(sorted(path for path in changed_paths if not allowed(path)))
    waived = tuple(sorted(path for path in changed_paths if allowed(path)))
    return Waiver(
        previous_tag=previous_tag,
        previous_api_level=previous_api_level,
        declared_api_level=declared_api_level,
        blocking=blocking,
        waived=waived,
    )


__all__ = [
    "BASES",
    "CHANGED",
    "NEVER_RUN",
    "UPSTREAM_ONLY",
    "WAIVABLE",
    "Waiver",
    "assess",
    "is_waivable",
    "pins_only",
]
