"""Resolving the minimum API level by measurement.

The search itself is pure, so it is tested against a stand-in for configure
rather than against a toolchain: what matters is that it finds the lowest level
whose decisions already match the top, confirms the boundary instead of assuming
it, and notices if the assumption it rests on stops holding.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pythonbuild.api_level import decisions, difference, resolve


class FakeConfigure:
    """Decisions that gain a define at each named level, as Bionic does."""

    def __init__(self, introduced: dict[int, str]) -> None:
        self.introduced = introduced
        self.calls: list[int] = []

    def __call__(self, level: int) -> dict[str, str]:
        self.calls.append(level)
        return {
            f"HAVE_{name.upper()}": "1"
            for at, name in sorted(self.introduced.items())
            if at <= level
        } | {"HAVE_ALWAYS": "1"}


class ResolveTest(unittest.TestCase):
    def test_the_answer_is_the_lowest_level_matching_the_top(self) -> None:
        configure = FakeConfigure({26: "old", 34: "close_range"})
        found = resolve(configure, lowest=21, ndk_max=35)
        self.assertEqual(found.level, 34)
        self.assertEqual(found.ndk_max, 35)

    def test_the_boundary_is_reported_as_evidence(self) -> None:
        configure = FakeConfigure({34: "close_range"})
        found = resolve(configure, lowest=21, ndk_max=35)
        self.assertEqual(found.boundary, {"HAVE_CLOSE_RANGE": (None, "1")})
        self.assertIn("API 33 -> 34 changes HAVE_CLOSE_RANGE", found.evidence())

    def test_a_level_above_the_last_change_is_not_chosen(self) -> None:
        # The point of the rule: 35 decides the same as 34, so 35 would only cost
        # device coverage.
        configure = FakeConfigure({34: "close_range"})
        self.assertEqual(resolve(configure, lowest=21, ndk_max=35).level, 34)

    def test_nothing_changing_anywhere_selects_the_lowest_candidate(self) -> None:
        configure = FakeConfigure({})
        found = resolve(configure, lowest=21, ndk_max=35)
        self.assertEqual(found.level, 21)
        self.assertEqual(found.boundary, {})
        self.assertIn("nothing changes", found.evidence())

    def test_a_change_at_the_very_top_selects_it(self) -> None:
        configure = FakeConfigure({35: "mseal"})
        self.assertEqual(resolve(configure, lowest=21, ndk_max=35).level, 35)

    def test_the_search_is_logarithmic(self) -> None:
        configure = FakeConfigure({34: "close_range"})
        resolve(configure, lowest=21, ndk_max=35)
        # 15 candidates: the top, four probes, and the boundary confirmation.
        self.assertLessEqual(len(set(configure.calls)), 7)

    def test_the_level_below_the_answer_really_does_decide_differently(self) -> None:
        # The evidence is produced by configuring one level lower and diffing,
        # not by trusting that the bisection landed on a boundary.
        configure = FakeConfigure({34: "close_range"})
        found = resolve(configure, lowest=21, ndk_max=35)
        self.assertIn(found.level - 1, configure.calls)
        self.assertNotEqual(configure(found.level - 1), configure(found.ndk_max))

    def test_an_empty_range_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            resolve(FakeConfigure({}), lowest=36, ndk_max=35)


class DecisionsTest(unittest.TestCase):
    def write(self, text: str) -> Path:
        directory = Path(self.enterContext(TemporaryDirectory()))
        path = directory / "pyconfig.h"
        path.write_text(text, encoding="utf-8")
        return path

    def test_defines_are_read_with_their_values(self) -> None:
        path = self.write(
            '#define HAVE_CLOSE_RANGE 1\n/* comment */\n#define PY_X "s"\n'
        )
        self.assertEqual(decisions(path), {"HAVE_CLOSE_RANGE": "1", "PY_X": '"s"'})

    def test_the_configured_level_itself_is_not_a_decision(self) -> None:
        # It differs at every candidate by construction and would make every
        # comparison report a difference.
        path = self.write("#define ANDROID_API_LEVEL 34\n#define HAVE_X 1\n")
        self.assertEqual(decisions(path), {"HAVE_X": "1"})

    def test_an_unfinished_configure_is_an_error_not_an_empty_answer(self) -> None:
        path = self.write("/* configure died here */\n")
        with self.assertRaises(RuntimeError):
            decisions(path)

    def test_difference_reports_both_sides(self) -> None:
        self.assertEqual(
            difference({"A": "1", "B": "1"}, {"A": "2", "C": "1"}),
            {"A": ("1", "2"), "B": ("1", None), "C": (None, "1")},
        )


if __name__ == "__main__":
    unittest.main()
