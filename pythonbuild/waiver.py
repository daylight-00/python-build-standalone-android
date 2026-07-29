"""When a release may go out without a device receipt for its own bytes.

A qualification receipt is evidence only for the bytes it names, and that does
not change here: nothing below claims an older receipt covers a newer build.

What it claims is weaker and true. If the only thing that differs between the
last build a device ran and this one is the pinned CPython input, then every
part of the distribution this project is responsible for — the launcher, the
loader normalization, the metadata overlay, the curation, the licence set — is
the same code that was qualified, and the residual risk is upstream's. That is
the risk an unattended release is willing to take. If anything else differs, the
risk is this project's own and the receipt is required.

The polarity matters. The set below names what is *allowed* to differ, and
everything else differing blocks the waiver, so a file nobody thought about
fails closed. Two things are deliberately outside it:

``config/toolchain.lock.json``
    An NDK or patchelf bump changes every compiled byte and can move the API
    floor. That is upstream in origin but not in effect.

anything under ``pythonbuild/``, the scripts, ``licenses/``, ``uv.lock``
    This project's own packaging, and the pinned tools that shape its output.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

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
    # The declared API floor follows the pins through a measurement.
    "ci-targets.yaml",
    # Receipts accumulate; a new one cannot invalidate a build.
    "qualification/*",
    "qualification/*/*",
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


def assess(
    *,
    previous_tag: str,
    previous_api_level: int,
    declared_api_level: int,
    changed_paths: list[str],
) -> Waiver:
    """Decide whether the difference since ``previous_tag`` is upstream's alone."""
    blocking = tuple(sorted(path for path in changed_paths if not is_waivable(path)))
    waived = tuple(sorted(path for path in changed_paths if is_waivable(path)))
    return Waiver(
        previous_tag=previous_tag,
        previous_api_level=previous_api_level,
        declared_api_level=declared_api_level,
        blocking=blocking,
        waived=waived,
    )


__all__ = ["WAIVABLE", "Waiver", "assess", "is_waivable"]
