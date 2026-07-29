"""Progress output.

A source build spends hours inside ``make``. Whatever it prints has to appear
while it is happening: output captured into a buffer and shown only on failure
leaves the log blank for the whole build, which is exactly the situation where
the log is the only way to see where it stopped.

Absolute imports are the default, so this module does not shadow the standard
library ``logging`` for anything that asks for it. Upstream places its own
logger at the same path.
"""

from __future__ import annotations

import sys

# Progress lines this project emits are marked; lines a tool produced are passed
# through unchanged, so a reader can tell which is which in one stream.
PREFIX = "==> "


def log(message: str) -> None:
    """Announce a step this project is taking."""
    print(f"{PREFIX}{message}", flush=True)


def log_raw(line: str) -> None:
    """Pass a line from a tool the build ran through untouched."""
    sys.stdout.write(line if line.endswith("\n") else line + "\n")
    sys.stdout.flush()
