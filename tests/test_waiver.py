"""When an unattended release may go out without a receipt for its own bytes.

The waiver never claims an old receipt covers new bytes. It claims that the only
thing which changed is upstream's, so the parts this project is answerable for
are the ones a device already ran. Everything here is a way that claim can be
false.
"""

from __future__ import annotations

import unittest

from pythonbuild.waiver import assess, is_waivable

PINS = [
    "config/source/cpython-3.14.7.lock.json",
    "config/upstream/cpython-3.14.7-aarch64-linux-android.lock.json",
    "config/source/dependency-recipes.lock.json",
    "ci-targets.yaml",
]


def waiver(changed: list[str], *, previous: int = 34, declared: int = 34):
    return assess(
        previous_tag="20260729",
        previous_api_level=previous,
        declared_api_level=declared,
        changed_paths=changed,
    )


class WaivablePathTest(unittest.TestCase):
    def test_the_cpython_pins_may_move(self) -> None:
        for path in PINS:
            with self.subTest(path=path):
                self.assertTrue(is_waivable(path))

    def test_prose_and_receipts_may_move(self) -> None:
        for path in ("docs/technotes.md", "README.md", "qualification/20260730/x.json"):
            with self.subTest(path=path):
                self.assertTrue(is_waivable(path))

    def test_the_toolchain_pin_may_not(self) -> None:
        # Upstream in origin, but an NDK bump changes every compiled byte and can
        # move the API floor.
        self.assertFalse(is_waivable("config/toolchain.lock.json"))

    def test_this_projects_own_code_may_not(self) -> None:
        for path in (
            "pythonbuild/assemble.py",
            "pythonbuild/elf.py",
            "build.py",
            "cpython-android/python.c",
            "cpython-android/run_tests.py",
            "licenses/components.json",
            "uv.lock",
            "pyproject.toml",
            ".github/workflows/release.yml",
            "Justfile",
        ):
            with self.subTest(path=path):
                self.assertFalse(is_waivable(path))

    def test_a_path_nobody_thought_about_fails_closed(self) -> None:
        self.assertFalse(is_waivable("something/new/entirely.py"))
        self.assertFalse(is_waivable("config/source/some-other-pin.json"))


class AssessTest(unittest.TestCase):
    def test_only_the_pins_moved(self) -> None:
        found = waiver(PINS)
        self.assertTrue(found.granted)
        self.assertEqual(found.blocking, ())
        self.assertIn("nothing but the pinned input changed", found.reason())

    def test_nothing_moved_at_all(self) -> None:
        self.assertTrue(waiver([]).granted)

    def test_a_change_to_the_packaging_blocks_it(self) -> None:
        found = waiver([*PINS, "pythonbuild/assemble.py"])
        self.assertFalse(found.granted)
        self.assertEqual(found.blocking, ("pythonbuild/assemble.py",))
        self.assertIn("this project's own files changed", found.reason())

    def test_a_toolchain_bump_blocks_it(self) -> None:
        found = waiver([*PINS, "config/toolchain.lock.json"])
        self.assertFalse(found.granted)
        self.assertIn("config/toolchain.lock.json", found.reason())

    def test_a_moved_floor_blocks_it_even_with_nothing_else_changed(self) -> None:
        # A different floor means a different set of devices, which is exactly
        # what no amount of unchanged packaging can stand in for.
        found = waiver(PINS, previous=34, declared=35)
        self.assertFalse(found.granted)
        self.assertIn("the API floor moved from 34 to 35", found.reason())

    def test_the_reason_does_not_list_every_blocking_path(self) -> None:
        found = waiver([f"pythonbuild/m{n}.py" for n in range(9)])
        self.assertIn("and 4 more", found.reason())

    def test_what_was_waived_is_reported_separately(self) -> None:
        found = waiver([*PINS, "pythonbuild/assemble.py"])
        self.assertIn("ci-targets.yaml", found.waived)
        self.assertNotIn("pythonbuild/assemble.py", found.waived)


if __name__ == "__main__":
    unittest.main()
