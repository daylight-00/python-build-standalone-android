"""The device qualification gate.

CI cannot run an Android distribution — there is no Android runner. So the one
check that matters most is produced out of band, on a real device, by
``qualify.py``, and committed as a receipt. This module is what the release
workflow uses to decide whether that receipt actually covers the artifacts about
to be published.

A receipt is only evidence for the bytes it names. Every artifact in the release
must appear in it by SHA-256, so a receipt from an earlier build cannot be
carried forward silently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .targets import ROOT, Build
from .utils import read_json_object

QUALIFICATION_ROOT = ROOT / "qualification"
ACCEPTED_ABIS = ("arm64-v8a", "aarch64", "arm64")


def receipt_path(build: Build, tag: str, root: Path = QUALIFICATION_ROOT) -> Path:
    return root / tag / f"{build.artifact_infix}.json"


class QualificationError(RuntimeError):
    """The release must not proceed."""


def verify(
    build: Build,
    tag: str,
    artifacts: dict[str, dict[str, Any]],
    *,
    root: Path = QUALIFICATION_ROOT,
) -> dict[str, Any]:
    """Check that a committed receipt covers exactly these artifacts.

    ``artifacts`` maps flavor to a record carrying ``filename`` and ``sha256``,
    as ``build.py`` writes them.
    """
    path = receipt_path(build, tag, root)
    if not path.is_file():
        raise QualificationError(
            f"no device qualification receipt for {build.name} at {tag}.\n"
            f"Run qualify.py on a device and commit the result to {path}."
        )
    receipt = read_json_object(path)

    if receipt.get("receipt_kind") != "android-device-qualification":
        raise QualificationError(f"{path} is not a device qualification receipt")

    verdict = receipt.get("verdict") or {}
    if not verdict.get("pass"):
        failures = ", ".join(verdict.get("failures") or ["unknown"]) or "unknown"
        raise QualificationError(f"{path} records a failed qualification: {failures}")

    covered = {
        entry["sha256"]: entry["filename"]
        for entry in [receipt["executed_artifact"], *receipt.get("bound_artifacts", [])]
    }
    missing = {
        flavor: record for flavor, record in artifacts.items() if record["sha256"] not in covered
    }
    if missing:
        detail = "\n".join(
            f"  {flavor}: {record['filename']} {record['sha256'][:16]}…"
            for flavor, record in sorted(missing.items())
        )
        raise QualificationError(
            f"{path} does not cover every artifact in this release.\n"
            f"Not covered:\n{detail}\n"
            f"The receipt was produced against different bytes; qualify this build."
        )

    executed = receipt["executed_artifact"]
    if executed["sha256"] not in {record["sha256"] for record in artifacts.values()}:
        raise QualificationError(
            f"{path} was executed against {executed['filename']}, which is not in this release"
        )

    device = receipt.get("device") or {}
    abi = device.get("abi") or device.get("machine")
    if abi not in ACCEPTED_ABIS:
        raise QualificationError(
            f"{path} records an ABI this project does not release for: {abi!r}"
        )

    identity = (receipt.get("checks") or {}).get("identity") or {}
    reported_api = identity.get("android_api_level")
    if str(reported_api) != str(build.android_api.level):
        raise QualificationError(
            f"{path} reports ANDROID_API_LEVEL {reported_api!r}, "
            f"but {build.name} declares {build.android_api.level}"
        )

    return {
        "receipt": path.relative_to(ROOT).as_posix(),
        "executed_artifact": executed["filename"],
        "artifacts_covered": len(artifacts),
        "device": {
            key: device.get(key)
            for key in ("model", "android_release", "api_level", "abi", "context", "page_size")
        },
        "interpreter": {
            key: identity.get(key)
            for key in ("version", "soabi", "multiarch", "platform", "android_api_level")
        },
    }
