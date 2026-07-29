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


def _passing_api_levels(directory: Path) -> dict[str, int]:
    """The API level each passing receipt in ``directory`` recorded, by artifact infix."""
    levels: dict[str, int] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            receipt = read_json_object(path)
        except (OSError, ValueError):
            continue
        if receipt.get("receipt_kind") != "android-device-qualification":
            continue
        if not (receipt.get("verdict") or {}).get("pass"):
            continue
        level = ((receipt.get("checks") or {}).get("identity") or {}).get("android_api_level")
        if level is not None:
            levels[path.stem] = int(level)
    return levels


def shipped_api_levels(tag: str, root: Path = QUALIFICATION_ROOT) -> dict[str, int]:
    """The API floor each build shipped with at ``tag``, keyed by artifact infix.

    Read out of the committed receipts rather than kept in a table of its own.
    ``verify`` refuses a release whose interpreter did not report the floor the
    build declares, so a passing receipt records the floor that tag shipped —
    which makes the receipts the repository's own per-tag history of where each
    floor stood, derived rather than transcribed.
    """
    directory = root / tag
    return _passing_api_levels(directory) if directory.is_dir() else {}


def previous_qualified_tag(tag: str, root: Path = QUALIFICATION_ROOT) -> str | None:
    """The newest tag before ``tag`` that carries a passing receipt.

    Tags are ``YYYYMMDD``, so ordering them as strings orders them by date.
    """
    if not root.is_dir():
        return None
    earlier = [
        path.name
        for path in root.iterdir()
        if path.is_dir() and path.name < tag and _passing_api_levels(path)
    ]
    return max(earlier, default=None)


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

    checks = receipt.get("checks") or {}
    identity = checks.get("identity") or {}
    reported_api = identity.get("android_api_level")
    if str(reported_api) != str(build.android_api.level):
        raise QualificationError(
            f"{path} reports ANDROID_API_LEVEL {reported_api!r}, "
            f"but {build.name} declares {build.android_api.level}"
        )

    runtime_data = _check_runtime_data(build, checks, path)

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
        "runtime_data": runtime_data,
    }


def _check_runtime_data(build: Build, checks: dict[str, Any], path: Path) -> dict[str, Any]:
    """Hold a build to what it claims about CA certificates and time zones.

    The device records what it found; which findings are acceptable depends on
    the build. One that compiles the paths in has to resolve them with nothing
    set, because that is the whole reason it is built from source. One that ships
    an external data product is expected not to, so the same finding is not a
    fault there.
    """
    observed = checks.get("runtime_data")
    declared = build.runtime_data
    if observed is None:
        raise QualificationError(
            f"{path} predates the runtime-data probe. Re-run qualify.py so the receipt "
            f"records what the distribution resolves for CA certificates and time zones."
        )
    if not observed.get("pass"):
        raise QualificationError(f"{path} could not probe runtime data: {observed.get('error')}")

    zones = observed.get("zones") or {}
    summary = {
        "mechanism": declared.get("mechanism"),
        "ca_certificate_count": observed.get("ca_certificate_count"),
        "tzpath_configured": observed.get("tzpath_configured"),
        "tzpath_present": observed.get("tzpath_present"),
        "zones": zones,
    }
    # Only what the build actually declares is required to work unaided. A path
    # this build does not compile in is not this build's promise to keep.
    problems = []
    if declared.get("openssldir") and not observed.get("ca_certificate_count"):
        problems.append(
            f"no CA certificates resolved from {observed.get('openssl_cafile')!r} "
            f"(present: {observed.get('openssl_cafile_present')})"
        )
    if declared.get("tzpath"):
        unresolved = {key: value for key, value in zones.items() if value != "pass"}
        if unresolved:
            problems.append(
                f"time zones did not resolve from {observed.get('tzpath_configured')!r} "
                f"(directories present: {observed.get('tzpath_present')}): {sorted(unresolved)}"
            )
    if problems:
        raise QualificationError(
            f"{build.name} compiles these paths in, so they must resolve with nothing "
            f"set. On this device they did not:\n  " + "\n  ".join(problems)
        )
    return summary
