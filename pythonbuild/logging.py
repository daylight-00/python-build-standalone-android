"""Progress output.

A source build spends hours inside ``make``. Whatever it prints has to appear
while it is happening: output captured into a buffer and shown only on failure
leaves the log blank for the whole build, which is exactly the situation where
the log is the only way to see where it stopped.

``set_logger`` and ``log`` follow upstream's module of the same name, including
its ``prefix> message`` format, so a line from either project reads the same.

Two deliberate differences. Upstream's ``log`` also writes to a log file set
through ``set_logger``; nothing here consumes one, and a handle that is always
``None`` is machinery pretending to be a feature. And upstream's ``log_raw``
writes bytes to that file only, which is the opposite of what is needed here —
so the passthrough is called ``log_output`` rather than borrowing a name that
means something else. Absolute imports are the default, so neither module
shadows the standard library ``logging``.
"""

from __future__ import annotations

import sys

DEFAULT_PREFIX = "build"
_PREFIX = [DEFAULT_PREFIX]


def set_logger(prefix: str) -> None:
    """Name the thing whose progress is being reported."""
    _PREFIX[0] = prefix


def log(message: str) -> None:
    """Announce a step this project is taking."""
    print(f"{_PREFIX[0]}> {message}", flush=True)


def log_output(line: str) -> None:
    """Pass a line from a tool the build ran through untouched."""
    sys.stdout.write(line if line.endswith("\n") else line + "\n")
    sys.stdout.flush()


__all__ = ["DEFAULT_PREFIX", "log", "log_output", "set_logger"]
