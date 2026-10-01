"""Release notes.

The floor callout is the reason this file is generated rather than written: an
API floor can move without a decision in this repository, and the notes are
where that has to become visible.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from tests.support import load_script

notes = load_script("release-notes")

REPOSITORY = "daylight-00/python-build-standalone-android"


def artifact(name: str) -> dict[str, Any]:
    return {"filename": name, "size_bytes": 1048576, "sha256": "f" * 64}


def build_receipt(build_option: str, api_level: int) -> dict[str, Any]:
    infix = "aarch64-linux-android"
    if build_option != "default":
        infix = f"{infix}-{build_option}"
    return {
        "triple": "aarch64-linux-android",
        "build_option": build_option,
        "android_api": {"level": api_level, "policy": "a-stated-rule"},
        "flavors": {
            "full": {
                "python_version": "3.14.6",
                "artifact": artifact(f"cpython-3.14.6+20260729-{infix}-full.tar.zst"),
            },
            "install_only": {"artifact": artifact(f"...-{infix}-install_only.tar.gz")},
            "install_only_stripped": {
                "artifact": artifact(f"...-{infix}-stripped.tar.gz")
            },
        },
    }


RECEIPTS = [build_receipt("upstream", 24), build_receipt("default", 34)]


def render(previous_levels: dict[str, int] | None) -> str:
    with mock.patch.object(
        notes, "shipped_api_levels", return_value=previous_levels or {}
    ):
        # str(): the module was loaded by path, so its annotations are not visible.
        return str(notes.render(RECEIPTS, "20260729", REPOSITORY, "20260728"))


def verdict(basis: str | None, reason: str = "because") -> dict[str, Any]:
    found: dict[str, Any] = {
        "tag": "20260729",
        "device_qualified": basis is None,
    }
    if basis is not None:
        found["waiver"] = {"basis": basis, "previous_tag": "20260728", "reason": reason}
    return found


def render_unqualified(verdicts: list[dict[str, Any]] | None) -> str:
    with mock.patch.object(notes, "shipped_api_levels", return_value={}):
        return str(
            notes.render(
                RECEIPTS,
                "20260729",
                REPOSITORY,
                "20260728",
                device_qualified=False,
                verdicts=verdicts,
            )
        )


class UnqualifiedReleaseNotesTest(unittest.TestCase):
    """A release nobody ran says so first, and claims only what its footing earns."""

    def test_a_qualified_release_carries_no_caution(self) -> None:
        self.assertNotIn("[!CAUTION]", render(None))

    def test_the_caution_comes_before_everything_else(self) -> None:
        text = render_unqualified([verdict("upstream-only")])
        self.assertTrue(text.startswith("> [!CAUTION]"))

    def test_an_upstream_only_change_may_lean_on_the_earlier_device_run(self) -> None:
        text = render_unqualified([verdict("upstream-only")])
        self.assertIn("nothing but the pinned CPython input changed", text)
        self.assertIn("since `20260728`, which a device did run", text)

    def test_a_change_to_this_project_may_not(self) -> None:
        text = render_unqualified(
            [
                verdict(
                    "changed", "this project's own files changed since 20260728: a.py"
                )
            ]
        )
        self.assertIn("this project's own files changed since 20260728: a.py", text)
        self.assertIn("nothing here vouches that it works on one", text)
        self.assertNotIn("the same code", text)

    def test_a_build_no_device_ever_ran_says_so(self) -> None:
        text = render_unqualified(
            [verdict("never-run", "this build has never run on a device")]
        )
        self.assertIn("there is no earlier device run to lean on", text)
        self.assertIn("this build has never run on a device", text)
        self.assertNotIn("the same code", text)

    def test_the_weakest_build_sets_the_claim_for_the_release(self) -> None:
        text = render_unqualified(
            [verdict("upstream-only"), verdict("changed", "files changed")]
        )
        self.assertIn("files changed", text)
        self.assertNotIn("the same code", text)

    def test_with_no_recorded_footing_it_claims_nothing(self) -> None:
        for verdicts in (None, [], [verdict(None)]):
            with self.subTest(verdicts=verdicts):
                text = render_unqualified(verdicts)
                self.assertIn("[!CAUTION]", text)
                self.assertIn("Nothing here vouches that it works on a device", text)
                self.assertNotIn("the same code", text)

    def test_the_catalogs_are_said_to_be_left_alone_in_every_case(self) -> None:
        for basis in ("upstream-only", "changed", "never-run"):
            with self.subTest(basis=basis):
                text = render_unqualified([verdict(basis)])
                self.assertIn("`uv python install` is unaffected", text)


class ReleaseNotesTest(unittest.TestCase):
    def test_unchanged_floors_produce_no_callout(self) -> None:
        text = render(
            {"aarch64-linux-android": 34, "aarch64-linux-android-upstream": 24}
        )
        self.assertNotIn("[!IMPORTANT]", text)
        self.assertTrue(text.startswith("## Builds"))

    def test_a_moved_floor_is_called_out_above_everything(self) -> None:
        text = render(
            {"aarch64-linux-android": 33, "aarch64-linux-android-upstream": 21}
        )
        self.assertTrue(text.startswith("> [!IMPORTANT]"))
        self.assertIn("changed since `20260728`", text)
        self.assertIn("the flagship build moved from API 33 to API 34", text)
        self.assertIn("the `upstream` build moved from API 21 to API 24", text)

    def test_only_the_build_that_moved_is_named(self) -> None:
        text = render(
            {"aarch64-linux-android": 34, "aarch64-linux-android-upstream": 21}
        )
        self.assertIn("the `upstream` build moved", text)
        self.assertNotIn("the flagship build moved", text)

    def test_a_build_with_no_previous_receipt_has_not_moved(self) -> None:
        # It was not in that release, so there is no previous floor to compare.
        text = render({"aarch64-linux-android-upstream": 24})
        self.assertNotIn("[!IMPORTANT]", text)

    def test_no_previous_tag_at_all(self) -> None:
        with mock.patch.object(notes, "previous_qualified_tag", return_value=None):
            text = notes.render(RECEIPTS, "20260729", REPOSITORY)
        self.assertNotIn("[!IMPORTANT]", text)

    def test_the_flagship_comes_first_whatever_order_receipts_arrive_in(self) -> None:
        text = render(None)
        self.assertLess(text.index("*(default)*"), text.index("`upstream`"))

    def test_every_build_appears_in_the_install_section(self) -> None:
        # The flagship was once dropped here, because the key form omits `:default`.
        text = render(None)
        self.assertIn("`aarch64-linux-android`, the flagship", text)
        self.assertIn("`aarch64-linux-android:upstream`, the baseline", text)
        self.assertIn("download-metadata.json", text)
        self.assertIn("download-metadata-upstream.json", text)

    def test_all_three_flavors_are_listed_for_every_build(self) -> None:
        text = render(None)
        for suffix in ("full.tar.zst", "install_only.tar.gz", "stripped.tar.gz"):
            self.assertEqual(text.count(suffix), 2, suffix)

    def test_a_receipt_with_no_entry_in_the_build_table_is_an_error(self) -> None:
        stray = build_receipt("default", 34)
        stray["triple"] = "riscv64-linux-android"
        with self.assertRaises(RuntimeError):
            notes.render([stray], "20260729", REPOSITORY, "20260728")


if __name__ == "__main__":
    unittest.main()
