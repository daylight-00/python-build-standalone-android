"""What an unattended release without a receipt for its own bytes may claim.

The waiver never claims an old receipt covers new bytes. It claims that the only
thing which changed is upstream's, so the parts this project is answerable for
are the ones a device already ran. Everything here is a way that claim can be
false — and when it is, the release is not refused, only held to a weaker one.
"""

from __future__ import annotations

import unittest

from pythonbuild.waiver import (
    BASES,
    CHANGED,
    NEVER_RUN,
    UPSTREAM_ONLY,
    assess,
    is_waivable,
    pins_only,
)

PIN_FILES = [
    "config/source/cpython-3.14.7.lock.json",
    "config/upstream/cpython-3.14.7-aarch64-linux-android.lock.json",
    "config/source/dependency-recipes.lock.json",
]
# What a pin bump changes: the locks, and the table that names them.
PINS = [*PIN_FILES, "ci-targets.yaml"]


def waiver(
    changed: list[str],
    *,
    previous: int = 34,
    declared: int = 34,
    targets_follow_pins: bool = True,
):
    return assess(
        previous_tag="20260729",
        previous_api_level=previous,
        declared_api_level=declared,
        changed_paths=changed,
        also_waivable=(
            frozenset({"ci-targets.yaml"}) if targets_follow_pins else frozenset()
        ),
    )


def targets(
    *, lock: str = "cpython-3.14.6", level: int = 34, openssldir: str = "/a"
) -> dict:
    return {
        "android": {
            "aarch64-linux-android": {
                "build_options": {
                    "default": {
                        "producer": "cpython-source",
                        "input_lock": f"config/source/{lock}.lock.json",
                        "runtime_data": {"openssldir": openssldir},
                        "android_api": {"level": level, "policy": "a-rule"},
                    }
                }
            }
        }
    }


class WaivablePathTest(unittest.TestCase):
    def test_the_cpython_pins_may_move(self) -> None:
        for path in PIN_FILES:
            with self.subTest(path=path):
                self.assertTrue(is_waivable(path))

    def test_the_target_table_is_not_waivable_as_a_path(self) -> None:
        # It says what each build compiles in; whether it moved only as far as the
        # pins is a question about its contents.
        self.assertFalse(is_waivable("ci-targets.yaml"))

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

    def test_only_an_upstream_change_earns_the_waiver_proper(self) -> None:
        self.assertEqual(waiver(PINS).basis, UPSTREAM_ONLY)

    def test_anything_else_is_a_weaker_claim_not_a_missing_one(self) -> None:
        self.assertEqual(waiver([*PINS, "build.py"]).basis, CHANGED)
        self.assertEqual(waiver(PINS, previous=34, declared=35).basis, CHANGED)

    def test_the_bases_run_from_the_strongest_claim_to_the_weakest(self) -> None:
        self.assertEqual(BASES, (UPSTREAM_ONLY, CHANGED, NEVER_RUN))

    def test_the_reason_does_not_list_every_blocking_path(self) -> None:
        found = waiver([f"pythonbuild/m{n}.py" for n in range(9)])
        self.assertIn("and 4 more", found.reason())

    def test_what_was_waived_is_reported_separately(self) -> None:
        found = waiver([*PINS, "pythonbuild/assemble.py"])
        self.assertIn("ci-targets.yaml", found.waived)
        self.assertNotIn("pythonbuild/assemble.py", found.waived)

    def test_a_target_table_that_moved_beyond_the_pins_blocks_it(self) -> None:
        found = waiver(PINS, targets_follow_pins=False)
        self.assertFalse(found.granted)
        self.assertEqual(found.blocking, ("ci-targets.yaml",))


class PinsOnlyTest(unittest.TestCase):
    """The target table follows CPython only through the lock and the floor."""

    def test_a_bump_moves_the_lock_and_the_measured_floor(self) -> None:
        self.assertTrue(pins_only(targets(), targets(lock="cpython-3.14.7", level=35)))

    def test_nothing_moved(self) -> None:
        self.assertTrue(pins_only(targets(), targets()))

    def test_what_a_build_compiles_in_is_not_a_pin(self) -> None:
        self.assertFalse(pins_only(targets(), targets(openssldir="/b")))

    def test_the_rule_behind_the_floor_is_not_a_pin(self) -> None:
        moved = targets()
        moved["android"]["aarch64-linux-android"]["build_options"]["default"][
            "android_api"
        ]["policy"] = "another-rule"
        self.assertFalse(pins_only(targets(), moved))

    def test_a_new_build_is_not_a_pin(self) -> None:
        added = targets()
        added["android"]["aarch64-linux-android"]["build_options"]["extra"] = {}
        self.assertFalse(pins_only(targets(), added))

    def test_the_arguments_are_left_alone(self) -> None:
        before, after = targets(), targets(lock="cpython-3.14.7")
        pins_only(before, after)
        self.assertEqual(before, targets())
        self.assertEqual(after, targets(lock="cpython-3.14.7"))


if __name__ == "__main__":
    unittest.main()
