"""The release gate.

Everything here is a reason a release must not go out. The gate is the only
check that a distribution actually runs, because CI has no Android runner, so
each way it can be fooled is worth a test of its own.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pythonbuild.qualification import (
    QualificationError,
    previous_qualified_tag,
    shipped_api_levels,
    verify,
)
from tests.support import make_build

FULL = {"filename": "cpython-full.tar.zst", "sha256": "a" * 64}
INSTALL_ONLY = {"filename": "cpython-install_only.tar.gz", "sha256": "b" * 64}
STRIPPED = {"filename": "cpython-install_only_stripped.tar.gz", "sha256": "c" * 64}
ARTIFACTS = {"full": FULL, "install_only": INSTALL_ONLY, "install_only_stripped": STRIPPED}


def receipt(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "receipt_kind": "android-device-qualification",
        "verdict": {"pass": True, "failures": []},
        "executed_artifact": dict(STRIPPED),
        "bound_artifacts": [dict(FULL), dict(INSTALL_ONLY)],
        "device": {
            "model": "a device",
            "android_release": "14",
            "api_level": 34,
            "abi": "arm64-v8a",
            "context": "termux",
            "page_size": 4096,
        },
        "checks": {
            "identity": {
                "android_api_level": 34,
                "version": "3.14.6",
                "soabi": "cpython-314-aarch64-linux-android",
                "multiarch": "aarch64-linux-android",
                "platform": "android-34-arm64_v8a",
            },
            "runtime_data": {
                "pass": True,
                "ca_certificate_count": 119,
                "openssl_cafile": "/etc/tls/cert.pem",
                "openssl_cafile_present": True,
                "tzpath_configured": "/usr/share/zoneinfo",
                "tzpath_present": [],
                "zones": {},
            },
        },
    }
    document.update(overrides)
    return document


class GateTest(unittest.TestCase):
    def check(
        self,
        document: dict[str, Any] | None,
        *,
        build_option: str = "default",
        api_level: int = 34,
        runtime_data: dict[str, Any] | None = None,
        artifacts: dict[str, dict[str, str]] | None = None,
        tag: str = "20260729",
    ) -> dict[str, Any]:
        build = make_build(build_option, api_level=api_level, runtime_data=runtime_data)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            if document is not None:
                directory = root / tag
                directory.mkdir(parents=True)
                path = directory / f"{build.artifact_infix}.json"
                path.write_text(json.dumps(document), encoding="utf-8")
            return verify(build, tag, artifacts or ARTIFACTS, root=root)

    def refuses(self, message: str, **kwargs: Any) -> None:
        with self.assertRaises(QualificationError) as caught:
            self.check(**kwargs)
        self.assertIn(message, str(caught.exception))

    def test_a_complete_receipt_passes(self) -> None:
        result = self.check(receipt())
        self.assertEqual(result["artifacts_covered"], 3)
        self.assertEqual(result["executed_artifact"], STRIPPED["filename"])
        self.assertEqual(result["device"]["abi"], "arm64-v8a")

    def test_no_receipt_at_all(self) -> None:
        self.refuses("no device qualification receipt", document=None)

    def test_some_other_kind_of_json(self) -> None:
        self.refuses("not a device qualification receipt", document=receipt(receipt_kind="other"))

    def test_the_device_reported_failure(self) -> None:
        self.refuses(
            "records a failed qualification",
            document=receipt(verdict={"pass": False, "failures": ["dlopen"]}),
        )

    def test_an_artifact_the_receipt_does_not_name(self) -> None:
        # The reason receipts cannot be carried forward: a rebuild changes bytes.
        rebuilt = {**ARTIFACTS, "full": {"filename": FULL["filename"], "sha256": "d" * 64}}
        self.refuses("does not cover every artifact", document=receipt(), artifacts=rebuilt)

    def test_the_receipt_ran_against_something_not_in_this_release(self) -> None:
        stray = {"filename": "elsewhere.tar.gz", "sha256": "e" * 64}
        self.refuses(
            "which is not in this release",
            document=receipt(executed_artifact=stray, bound_artifacts=list(ARTIFACTS.values())),
        )

    def test_an_abi_this_project_does_not_release_for(self) -> None:
        document = receipt()
        document["device"]["abi"] = "x86_64"
        self.refuses("an ABI this project does not release for", document=document)

    def test_the_interpreter_disagrees_with_the_declared_floor(self) -> None:
        self.refuses("but", document=receipt(), api_level=35)

    def test_a_receipt_from_before_the_runtime_data_probe(self) -> None:
        document = receipt()
        del document["checks"]["runtime_data"]
        self.refuses("predates the runtime-data probe", document=document)

    def test_a_build_that_compiles_a_trust_store_in_must_resolve_it(self) -> None:
        document = receipt()
        document["checks"]["runtime_data"]["ca_certificate_count"] = 0
        document["checks"]["runtime_data"]["openssl_cafile_present"] = False
        self.refuses(
            "must resolve with nothing",
            document=document,
            runtime_data={"mechanism": "build-default", "openssldir": "/etc/tls"},
        )

    def test_a_build_that_ships_a_data_product_is_not_held_to_one(self) -> None:
        # The same finding is not a fault for `upstream`: it compiles nothing in,
        # so an empty trust store is what its documentation says to expect.
        document = receipt()
        document["checks"]["runtime_data"]["ca_certificate_count"] = 0
        document["checks"]["identity"]["android_api_level"] = 24
        result = self.check(
            document,
            build_option="upstream",
            api_level=24,
            runtime_data={"mechanism": "data-product"},
        )
        self.assertEqual(result["runtime_data"]["ca_certificate_count"], 0)

    def test_a_build_that_compiles_a_tzpath_in_must_resolve_zones(self) -> None:
        document = receipt()
        document["checks"]["runtime_data"]["zones"] = {"Asia/Seoul": "ZoneInfoNotFoundError"}
        self.refuses(
            "time zones did not resolve",
            document=document,
            runtime_data={"mechanism": "build-default", "tzpath": "/usr/share/zoneinfo"},
        )


class HistoryTest(unittest.TestCase):
    """The per-tag floor history the release notes read."""

    def write(self, root: Path, tag: str, infix: str, level: int, passed: bool = True) -> None:
        directory = root / tag
        directory.mkdir(parents=True, exist_ok=True)
        document = receipt()
        document["verdict"] = {"pass": passed, "failures": []}
        document["checks"]["identity"]["android_api_level"] = level
        (directory / f"{infix}.json").write_text(json.dumps(document), encoding="utf-8")

    def test_levels_are_read_per_build(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "20260728", "aarch64-linux-android", 34)
            self.write(root, "20260728", "aarch64-linux-android-upstream", 24)
            self.assertEqual(
                shipped_api_levels("20260728", root=root),
                {"aarch64-linux-android": 34, "aarch64-linux-android-upstream": 24},
            )

    def test_a_failed_receipt_is_not_history(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "20260728", "aarch64-linux-android", 34, passed=False)
            self.assertEqual(shipped_api_levels("20260728", root=root), {})

    def test_an_absent_tag_has_no_levels(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertEqual(shipped_api_levels("19700101", root=Path(tmp)), {})

    def test_the_previous_tag_is_the_newest_earlier_one(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for tag in ("20260101", "20260728", "20260729"):
                self.write(root, tag, "aarch64-linux-android", 34)
            self.assertEqual(previous_qualified_tag("20260729", root=root), "20260728")
            self.assertEqual(previous_qualified_tag("20260728", root=root), "20260101")
            self.assertIsNone(previous_qualified_tag("20260101", root=root))

    def test_a_tag_with_only_failed_receipts_is_skipped(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "20260101", "aarch64-linux-android", 34)
            self.write(root, "20260728", "aarch64-linux-android", 34, passed=False)
            self.assertEqual(previous_qualified_tag("20260729", root=root), "20260101")


if __name__ == "__main__":
    unittest.main()
