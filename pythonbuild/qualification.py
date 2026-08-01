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

from .artifacts import ArtifactName, parse
from .targets import ROOT, Build
from .utils import read_json_object

QUALIFICATION_ROOT = ROOT / "qualification"
ACCEPTED_ABIS = ("arm64-v8a", "aarch64", "arm64")


def receipt_path(
    build: Build, tag: str, python_version: str, root: Path = QUALIFICATION_ROOT
) -> Path:
    """Where a receipt for this build and version belongs.

    Named after the artifact stem without the tag, which the directory already
    carries. The version is in it because a receipt that does not name the Python
    it qualified cannot be told apart from one for another series at the same tag
    — and because reading a directory should not require opening every file.
    """
    return root / tag / f"cpython-{python_version}-{build.artifact_infix}.json"


def describes(receipt: dict[str, Any]) -> ArtifactName | None:
    """What build and version a receipt covers, read out of the receipt.

    Taken from the artifact it ran against rather than from its own filename, so
    a receipt is identified by what it did and not by what the operator happened
    to call it.
    """
    executed = receipt.get("executed_artifact") or {}
    filename = executed.get("filename")
    return parse(str(filename)) if filename else None


def _display_path(path: Path) -> str:
    """Repository-relative where that is meaningful, and the whole path where it is not.

    ``root`` is a parameter so a caller can point somewhere else, and every such
    caller used to crash here: the result was reported with ``relative_to(ROOT)``,
    which raises for anything outside the repository.
    """
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def passing_receipts(directory: Path) -> list[tuple[ArtifactName, dict[str, Any]]]:
    """Every receipt in ``directory`` that passed, with what it says it covers.

    Keyed on the receipt's content rather than its filename, so a rename cannot
    hide a receipt and a receipt cannot claim a build by being named after one.
    """
    found: list[tuple[ArtifactName, dict[str, Any]]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            receipt = read_json_object(path)
        except (OSError, ValueError):
            continue
        if receipt.get("receipt_kind") != "android-device-qualification":
            continue
        if not (receipt.get("verdict") or {}).get("pass"):
            continue
        described = describes(receipt)
        if described is not None:
            found.append((described, receipt))
    return found


def _passing_api_levels(directory: Path) -> dict[str, int]:
    """The API level each passing receipt recorded, by artifact infix."""
    levels: dict[str, int] = {}
    for described, receipt in passing_receipts(directory):
        level = ((receipt.get("checks") or {}).get("identity") or {}).get(
            "android_api_level"
        )
        if level is not None:
            levels[described.artifact_infix] = int(level)
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


def _version_of(artifacts: dict[str, dict[str, Any]]) -> str:
    """The Python version these artifacts are of, read off their names."""
    for record in artifacts.values():
        described = parse(str(record.get("filename", "")))
        if described is not None:
            return described.version
    raise QualificationError(
        f"none of these artifacts has a name this project publishes: "
        f"{sorted(str(r.get('filename')) for r in artifacts.values())}"
    )


def find_receipt(
    build: Build, tag: str, python_version: str, root: Path = QUALIFICATION_ROOT
) -> tuple[Path, dict[str, Any]] | None:
    """The receipt at ``tag`` covering this build and version, whatever its name."""
    directory = root / tag
    if not directory.is_dir():
        return None
    for path in sorted(directory.glob("*.json")):
        try:
            receipt = read_json_object(path)
        except (OSError, ValueError):
            continue
        described = describes(receipt)
        if (
            described is not None
            and described.artifact_infix == build.artifact_infix
            and described.version == python_version
        ):
            return path, receipt
    return None


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
    python_version = _version_of(artifacts)
    found = find_receipt(build, tag, python_version, root)
    if found is None:
        expected = receipt_path(build, tag, python_version, root)
        present = sorted(p.name for p in (root / tag).glob("*.json"))
        holds = f"\n{_display_path(root / tag)} holds: {present}" if present else ""
        raise QualificationError(
            f"no device qualification receipt for {build.name} {python_version} "
            f"at {tag}.\n"
            f"Run qualify.py on a device and commit the result to "
            f"{_display_path(expected)}.{holds}"
        )
    path, receipt = found

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
        flavor: record
        for flavor, record in artifacts.items()
        if record["sha256"] not in covered
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

    modules = _check_modules(checks, path)
    runtime_data = _check_runtime_data(build, checks, path)

    return {
        "receipt": _display_path(path),
        "executed_artifact": executed["filename"],
        "artifacts_covered": len(artifacts),
        "device": {
            key: device.get(key)
            for key in (
                "model",
                "android_release",
                "api_level",
                "abi",
                "context",
                "page_size",
            )
        },
        "interpreter": {
            key: identity.get(key)
            for key in (
                "version",
                "soabi",
                "multiarch",
                "platform",
                "android_api_level",
            )
        },
        "runtime_data": runtime_data,
        "modules": modules,
    }


def _check_modules(checks: dict[str, Any], path: Path) -> dict[str, Any]:
    """Every module CPython said it built has to import on the device.

    The expectation is derived from the distribution's own sysconfigdata, so this
    catches a module that stopped being built as well as one that fails to load —
    an earlier probe imported whatever was in lib-dynload and could only see the
    second.
    """
    observed = checks.get("extensions") or {}
    if "expected" not in observed:
        raise QualificationError(
            f"{path} predates the derived module check. Re-run qualify.py so the receipt "
            f"records every module CPython says it built, not only the ones that shipped."
        )
    if not observed.get("pass"):
        raise QualificationError(
            f"{path} could not probe modules: {observed.get('error')}"
        )
    failures = observed.get("failures") or {}
    if failures:
        detail = "\n  ".join(
            f"{name}: {reason}" for name, reason in sorted(failures.items())
        )
        raise QualificationError(
            f"{path} records modules that CPython built and the device could not import:\n"
            f"  {detail}"
        )
    return {
        "source": observed.get("source"),
        "expected": len(observed.get("expected") or []),
        "builtin": len(observed.get("builtin") or []),
        "unavailable": sorted(observed.get("unavailable") or {}),
    }


def _check_runtime_data(
    build: Build, checks: dict[str, Any], path: Path
) -> dict[str, Any]:
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
        raise QualificationError(
            f"{path} could not probe runtime data: {observed.get('error')}"
        )

    zones = observed.get("zones") or {}
    summary = {
        "mechanism": declared.get("mechanism"),
        "ca_certificate_count": observed.get("ca_certificate_count"),
        "ca_default_verify_pass": observed.get("ca_default_verify_pass"),
        "ca_default_verify": observed.get("ca_default_verify"),
        "tzpath_configured": observed.get("tzpath_configured"),
        "tzpath_present": observed.get("tzpath_present"),
        "zones": zones,
    }
    # Only what the build actually declares is required to work unaided. A path
    # this build does not compile in is not this build's promise to keep.
    problems = []
    ca_resolved = bool(
        observed.get("ca_certificate_count")
        or observed.get("ca_default_verify_pass")
    )
    if declared.get("openssldir") and not ca_resolved:
        problems.append(
            f"the default CA store could not verify a native root from "
            f"{observed.get('openssl_capath')!r}: "
            f"{observed.get('ca_default_verify') or observed.get('ca_error')}"
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
