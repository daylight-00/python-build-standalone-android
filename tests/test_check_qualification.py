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
        targets_follow_pins: bool = True,
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
                        "ci_targets_follow_pins": lambda tag: targets_follow_pins,
                    },
                ),
            ):
                code = function(
                    build, "20260814", SCRIPT["NoReceiptError"]("x"), report
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
        self.assertIn("docs/status.md", verdict["waiver"]["waived"])
        self.assertEqual(verdict["waiver"]["blocking"], [])

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
        self.assertEqual(verdict["waiver"]["blocking"], ["pythonbuild/assemble.py"])

    def test_a_target_table_that_moved_beyond_the_pins_is_not_a_pin(self) -> None:
        # ci-targets.yaml says what a build compiles in, so changing it changes
        # bytes. Only a file that moved no further than the pins is waivable.
        code, verdict = self.consider(
            previous="20260729",
            levels={"aarch64-linux-android": 34},
            changed=list(self.PINS),
            targets_follow_pins=False,
        )
        self.assertEqual(code, 0)
        self.assertEqual(verdict["waiver"]["basis"], "changed")
        self.assertEqual(verdict["waiver"]["blocking"], ["ci-targets.yaml"])

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


class GateTest(unittest.TestCase):
    """What ``--allow-waiver`` may and may not stand in for."""

    def run_gate(
        self, raises: Exception, *argv: str
    ) -> tuple[int, dict[str, Any] | None, io.StringIO]:
        """The exit code, the verdict it recorded (if any), and what it said."""
        main = SCRIPT["main"]
        stderr = io.StringIO()
        with TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (
                dist / "cpython-3.14.7+20260814-aarch64-linux-android.build.json"
            ).write_text(
                json.dumps(
                    {
                        "flavors": {
                            "full": {
                                "artifact": {
                                    "filename": "cpython-3.14.7+20260814-aarch64-linux-android-full.tar.zst",
                                    "sha256": "f" * 64,
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            report = dist / "verdict.json"

            def refuse(*args: Any, **kwargs: Any) -> None:
                raise raises

            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
                mock.patch.dict(
                    main.__globals__,
                    {
                        "verify": refuse,
                        "previous_released_qualified_tag": lambda tag: None,
                    },
                ),
            ):
                code = main(
                    [
                        "--target",
                        "aarch64-linux-android",
                        "--tag",
                        "20260814",
                        "--dist-dir",
                        str(dist),
                        "--report",
                        str(report),
                        *argv,
                    ]
                )
            verdict = (
                json.loads(report.read_text(encoding="utf-8"))
                if report.exists()
                else None
            )
            return code, verdict, stderr

    def test_no_receipt_is_refused_without_the_flag(self) -> None:
        code, verdict, stderr = self.run_gate(SCRIPT["NoReceiptError"]("none"))
        self.assertEqual(code, 1)
        self.assertIsNone(verdict)
        self.assertIn("REFUSED", stderr.getvalue())

    def test_no_receipt_is_published_unqualified_with_the_flag(self) -> None:
        code, verdict, _ = self.run_gate(
            SCRIPT["NoReceiptError"]("none"), "--allow-waiver"
        )
        self.assertEqual(code, 0)
        assert verdict is not None
        self.assertFalse(verdict["device_qualified"])

    def test_a_receipt_that_records_a_failure_is_never_waived(self) -> None:
        # The waiver stands in for evidence that does not exist. A device that ran
        # these bytes and said no is evidence, and no footing outweighs it.
        error = SCRIPT["QualificationError"](
            "receipt.json records a failed qualification"
        )
        code, verdict, stderr = self.run_gate(error, "--allow-waiver")
        self.assertEqual(code, 1)
        self.assertIsNone(verdict)
        self.assertIn("failed qualification", stderr.getvalue())

    def test_a_receipt_for_other_bytes_is_never_waived(self) -> None:
        error = SCRIPT["QualificationError"]("receipt does not cover every artifact")
        code, verdict, _ = self.run_gate(error, "--allow-waiver")
        self.assertEqual(code, 1)
        self.assertIsNone(verdict)


if __name__ == "__main__":
    unittest.main()
