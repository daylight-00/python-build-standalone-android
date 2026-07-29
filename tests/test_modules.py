"""The expected extension modules, derived from CPython's own configure output.

Upstream keeps a hand-written table per Python version and platform. This project
reads the decisions out of the sysconfigdata the distribution ships, so that the
set follows python.org rather than needing an edit here — the same delegation
already applied to the dependency set and the `upstream` API floor.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pythonbuild.modules import check_shared_modules, expectations, shipped_shared

EXT_SUFFIX = ".cpython-314-aarch64-linux-android.so"


def write_stdlib(
    root: Path,
    *,
    states: dict[str, str],
    shared: list[str],
    builtin: list[str],
    ship: list[str] | None = None,
) -> Path:
    stdlib = root / "lib/python3.14"
    (stdlib / "lib-dynload").mkdir(parents=True)
    for name in shared if ship is None else ship:
        (stdlib / "lib-dynload" / f"{name}{EXT_SUFFIX}").write_bytes(b"\x7fELF")
    variables = {
        f"MODULE_{name.upper()}_STATE": state for name, state in states.items()
    }
    variables["MODSHARED_NAMES"] = " ".join(shared)
    variables["MODBUILT_NAMES"] = " ".join(builtin)
    variables["EXT_SUFFIX"] = EXT_SUFFIX
    (stdlib / "_sysconfigdata__android_aarch64-linux-android.py").write_text(
        f"build_time_vars = {variables!r}\n", encoding="utf-8"
    )
    return stdlib


STATES = {
    "_ssl": "yes",
    "_socket": "yes",
    "time": "yes",
    "readline": "missing",
    "_scproxy": "n/a",
}
SHARED = ["_ssl", "_socket"]
BUILTIN = ["time"]


class ExpectationsTest(unittest.TestCase):
    def test_states_are_read_and_lowercased(self) -> None:
        with TemporaryDirectory() as tmp:
            stdlib = write_stdlib(
                Path(tmp), states=STATES, shared=SHARED, builtin=BUILTIN
            )
            found = expectations(stdlib)
        self.assertEqual(found.built, frozenset({"_ssl", "_socket", "time"}))
        self.assertEqual(found.unavailable, {"readline": "missing", "_scproxy": "n/a"})
        self.assertEqual(found.shared, frozenset(SHARED))
        self.assertEqual(found.ext_suffix, EXT_SUFFIX)

    def test_a_sysconfigdata_with_no_decisions_is_an_error(self) -> None:
        with TemporaryDirectory() as tmp:
            stdlib = write_stdlib(Path(tmp), states={}, shared=[], builtin=[])
            with self.assertRaises(RuntimeError):
                expectations(stdlib)

    def test_shipped_shared_reads_the_suffix_off_the_names(self) -> None:
        with TemporaryDirectory() as tmp:
            stdlib = write_stdlib(
                Path(tmp), states=STATES, shared=SHARED, builtin=BUILTIN
            )
            self.assertEqual(shipped_shared(stdlib, EXT_SUFFIX), frozenset(SHARED))


class SharedModuleCheckTest(unittest.TestCase):
    def test_a_matching_distribution_passes(self) -> None:
        with TemporaryDirectory() as tmp:
            stdlib = write_stdlib(
                Path(tmp), states=STATES, shared=SHARED, builtin=BUILTIN
            )
            summary = check_shared_modules(stdlib)
        self.assertEqual(summary["shared_module_count"], 2)
        self.assertEqual(summary["builtin_module_count"], 1)
        self.assertEqual(
            summary["unavailable"], {"_scproxy": "n/a", "readline": "missing"}
        )

    def test_a_module_that_stopped_shipping_is_caught(self) -> None:
        # The failure the old probe could not see: _ssl silently gone.
        with TemporaryDirectory() as tmp:
            stdlib = write_stdlib(
                Path(tmp),
                states=STATES,
                shared=SHARED,
                builtin=BUILTIN,
                ship=["_socket"],
            )
            with self.assertRaises(RuntimeError) as caught:
                check_shared_modules(stdlib)
        self.assertIn("built but not shipped: ['_ssl']", str(caught.exception))

    def test_a_module_nothing_built_is_caught(self) -> None:
        with TemporaryDirectory() as tmp:
            stdlib = write_stdlib(
                Path(tmp),
                states=STATES,
                shared=SHARED,
                builtin=BUILTIN,
                ship=[*SHARED, "_stowaway"],
            )
            with self.assertRaises(RuntimeError) as caught:
                check_shared_modules(stdlib)
        self.assertIn("shipped but not built: ['_stowaway']", str(caught.exception))

    def test_turning_a_module_on_needs_no_edit_here(self) -> None:
        # What `extended` will do: configure starts saying yes to readline, and
        # the expectation follows without a table to update.
        with TemporaryDirectory() as tmp:
            stdlib = write_stdlib(
                Path(tmp),
                states={**STATES, "readline": "yes"},
                shared=[*SHARED, "readline"],
                builtin=BUILTIN,
            )
            summary = check_shared_modules(stdlib)
        self.assertEqual(summary["shared_module_count"], 3)
        self.assertNotIn("readline", summary["unavailable"])


if __name__ == "__main__":
    unittest.main()
