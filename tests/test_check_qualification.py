"""Regression tests for the release qualification command."""

from __future__ import annotations

import json
import runpy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any

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
            return function(tag, root=root)
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


if __name__ == "__main__":
    unittest.main()
