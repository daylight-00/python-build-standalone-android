"""Regression tests for the release qualification command."""

from __future__ import annotations

import contextlib
import io
import json
import runpy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from tests.support import make_build

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = runpy.run_path(str(ROOT / "check-qualification.py"))


class ReleasedQualificationHistoryTest(unittest.TestCase):
    def write_receipt(self, root: Path, tag: str) -> None:
        directory = root / tag
        directory.mkdir(parents=True, exist_ok=True)
        document: dict[str, Any] = {
            "receipt_kind": "android-device-qualification",
            "verdict": {"pass": True, "failures": []},
            "executed_artifact": {
                "filename": (
                    f"cpython-3.14.6+{tag}-aarch64-linux-android-"
                    "install_only_stripped.tar.gz"
                )
            },
            "checks": {"identity": {"android_api_level": 34}},
        }
        (directory / "receipt.json").write_text(json.dumps(document), encoding="utf-8")

    def with_git_tags(self, tags: set[str]) -> Any:
        def fake_run(argv: list[str]) -> SimpleNamespace:
            ref = argv[-1]
            return SimpleNamespace(
                returncode=0 if ref.removeprefix("refs/tags/") in tags else 1,
                stdout="",
                stderr="",
            )

        return fake_run

    def call_with_git_tags(self, tag: str, root: Path, tags: set[str]) -> str | None:
        function = SCRIPT["previous_released_qualified_tag"]
        globals_ = function.__globals__
        original = globals_["run"]
        globals_["run"] = self.with_git_tags(tags)
        try:
            return cast(str | None, function(tag, root=root))
        finally:
            globals_["run"] = original

    def test_unreleased_qualified_candidate_is_skipped(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_receipt(root, "20260729")
            self.write_receipt(root, "20260730")
            self.assertEqual(
                self.call_with_git_tags("20260814", root, {"20260729"}),
                "20260729",
            )

    def test_no_released_qualified_candidate_returns_none(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_receipt(root, "20260730")
            self.assertIsNone(self.call_with_git_tags("20260814", root, set()))


class UnqualifiedReleaseTest(unittest.TestCase):
    """A release with no receipt is recorded, never refused, once it is allowed."""

    PINS = ("config/source/cpython-3.14.7.lock.json", "ci-targets.yaml")

    def consider(
        self,
        *,
        previous: str | None,
        levels: dict[str, int],
        changed: list[str],
        api_level: int = 34,
    ) -> tuple[int, dict[str, Any]]:
        function = SCRIPT["consider_waiver"]
        build = make_build(api_level=api_level)
        with TemporaryDirectory() as tmp:
            report = Path(tmp) / "verdict.json"
            with (
                contextlib.redirect_stdout(io.StringIO()),
                mock.patch.dict(
                    function.__globals__,
                    {
                        "previous_released_qualified_tag": lambda tag: previous,
                        "shipped_api_levels": lambda tag: levels,
                        "changed_since": lambda tag: changed,
                    },
                ),
            ):
                code = function(
                    build, "20260814", SCRIPT["QualificationError"]("x"), report
                )
            return code, json.loads(report.read_text(encoding="utf-8"))

    def test_a_pin_only_change_keeps_the_strongest_claim(self) -> None:
        code, verdict = self.consider(
            previous="20260729",
            levels={"aarch64-linux-android": 34},
            changed=[*self.PINS, "docs/status.md"],
        )
        self.assertEqual(code, 0)
        self.assertFalse(verdict["device_qualified"])
        self.assertEqual(verdict["waiver"]["basis"], "upstream-only")
        self.assertEqual(verdict["waiver"]["previous_tag"], "20260729")
        self.assertIn("docs/status.md", verdict["waiver"]["changed"])

    def test_a_change_to_the_project_is_published_on_a_weaker_claim(self) -> None:
        # This used to be a refusal, which meant no release could go out
        # unattended once anything but a pin had moved.
        code, verdict = self.consider(
            previous="20260729",
            levels={"aarch64-linux-android": 34},
            changed=[*self.PINS, "pythonbuild/assemble.py"],
        )
        self.assertEqual(code, 0)
        self.assertFalse(verdict["device_qualified"])
        self.assertEqual(verdict["waiver"]["basis"], "changed")
        self.assertIn("pythonbuild/assemble.py", verdict["waiver"]["reason"])

    def test_a_moved_floor_is_a_weaker_claim_too(self) -> None:
        code, verdict = self.consider(
            previous="20260729",
            levels={"aarch64-linux-android": 34},
            changed=list(self.PINS),
            api_level=35,
        )
        self.assertEqual(code, 0)
        self.assertEqual(verdict["waiver"]["basis"], "changed")
        self.assertIn("API floor moved from 34 to 35", verdict["waiver"]["reason"])

    def test_a_build_no_device_ever_ran_is_published_and_says_so(self) -> None:
        code, verdict = self.consider(
            previous="20260729",
            levels={"aarch64-linux-android-upstream": 24},
            changed=list(self.PINS),
        )
        self.assertEqual(code, 0)
        self.assertEqual(verdict["waiver"]["basis"], "never-run")
        self.assertIn("has never run on a device", verdict["waiver"]["reason"])

    def test_with_no_qualified_release_at_all_there_is_nothing_to_lean_on(self) -> None:
        code, verdict = self.consider(previous=None, levels={}, changed=[])
        self.assertEqual(code, 0)
        self.assertEqual(verdict["waiver"]["basis"], "never-run")
        self.assertIsNone(verdict["waiver"]["previous_tag"])


if __name__ == "__main__":
    unittest.main()
