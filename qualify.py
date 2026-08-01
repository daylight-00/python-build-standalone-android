#!/usr/bin/env python3
"""Run a distribution on an Android device and write a qualification receipt.

    python3 qualify.py cpython-3.14.6+20260727-...-install_only_stripped.tar.gz

Copy this file and the archive to the device and run it there with any Python 3.
It uses only the standard library, because a device is not guaranteed to have
uv, pip, or a virtual environment available.

The receipt it writes binds the checks to the exact archive bytes they ran
against. The release workflow refuses to publish a build whose receipt does not
match the artifacts being released, so a receipt produced against a different
build cannot be reused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

IDENTITY_PROBE = """
import json, sys, sysconfig
print(json.dumps({
    "version": sys.version.split()[0],
    "executable": sys.executable,
    "prefix": sys.prefix,
    "base_prefix": sys.base_prefix,
    "soabi": sysconfig.get_config_var("SOABI"),
    "multiarch": sysconfig.get_config_var("MULTIARCH"),
    "platform": sysconfig.get_platform(),
    "android_api_level": sysconfig.get_config_var("ANDROID_API_LEVEL"),
    "ext_suffix": sysconfig.get_config_var("EXT_SUFFIX"),
    "paths_within_prefix": all(
        p.startswith(sys.prefix) for p in sysconfig.get_paths().values()
    ),
}))
"""

# Importing what happens to be in lib-dynload only proves that what shipped
# works. It cannot notice a module that stopped being built, which is the way a
# distribution silently loses _ssl. The expectation comes from CPython's own
# configure decisions instead, which also covers the modules linked into the
# interpreter rather than shipped as shared objects.
EXTENSIONS_PROBE = """
import importlib, json, sys, sysconfig
variables = sysconfig.get_config_vars()
states = {
    key[len("MODULE_"):-len("_STATE")].lower(): value
    for key, value in variables.items()
    if key.startswith("MODULE_") and key.endswith("_STATE")
}
expected = sorted(name for name, state in states.items() if state == "yes")
failures = {}
for name in expected:
    try:
        importlib.import_module(name)
    except Exception as error:
        failures[name] = f"{type(error).__name__}: {error}"
print(json.dumps({
    "source": "sysconfigdata",
    "expected": expected,
    "count": len(expected),
    "builtin": sorted(set(expected) & set(sys.builtin_module_names)),
    "unavailable": {n: s for n, s in sorted(states.items()) if s != "yes"},
    "failures": failures,
}))
"""

DLOPEN_PROBE = """
import ctypes, json, pathlib, sys
libdir = pathlib.Path(sys.prefix) / "lib"
results = {}
for path in sorted(libdir.rglob("*.so")):
    # Extension modules are covered by the import probe; this one is about the
    # shared libraries they depend on resolving through the relative RUNPATH.
    if path.relative_to(libdir).parts[0].startswith("python3."):
        continue
    try:
        ctypes.CDLL(str(path))
        results[path.relative_to(libdir).as_posix()] = "pass"
    except OSError as error:
        results[path.relative_to(libdir).as_posix()] = str(error)
print(json.dumps(results))
"""

# What the distribution resolves for CA certificates and time zones, without any
# environment set. A build that compiles these paths in should work as it stands;
# one that expects an external data product should not, and saying which is the
# gate's job rather than this probe's.
CA_VERIFY_HELPER = r"""
import ctypes, ctypes.util, pathlib, re, sys


def _default_ca_verification(capath):
    # Verify a certificate through OpenSSL's default store, including lazy capaths.
    if not capath or not pathlib.Path(capath).is_dir():
        return {"pass": False, "error": "default CA directory is absent", "attempted": 0}
    candidates = [
        path
        for path in sorted(pathlib.Path(capath).iterdir())
        if re.fullmatch(r"[0-9a-fA-F]{8}\.[0-9]+", path.name)
    ]
    library = pathlib.Path(sys.prefix) / "lib/libcrypto_python.so"
    library_name = str(library) if library.is_file() else ctypes.util.find_library("crypto")
    if not library_name:
        return {"pass": False, "error": "libcrypto could not be located", "attempted": 0}
    try:
        crypto = ctypes.CDLL(library_name)
        crypto.BIO_new_mem_buf.argtypes = [ctypes.c_void_p, ctypes.c_int]
        crypto.BIO_new_mem_buf.restype = ctypes.c_void_p
        crypto.BIO_free.argtypes = [ctypes.c_void_p]
        crypto.PEM_read_bio_X509.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        ]
        crypto.PEM_read_bio_X509.restype = ctypes.c_void_p
        crypto.X509_free.argtypes = [ctypes.c_void_p]
        crypto.X509_STORE_new.restype = ctypes.c_void_p
        crypto.X509_STORE_free.argtypes = [ctypes.c_void_p]
        crypto.X509_STORE_set_default_paths.argtypes = [ctypes.c_void_p]
        crypto.X509_STORE_set_default_paths.restype = ctypes.c_int
        crypto.X509_STORE_CTX_new.restype = ctypes.c_void_p
        crypto.X509_STORE_CTX_free.argtypes = [ctypes.c_void_p]
        crypto.X509_STORE_CTX_init.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        ]
        crypto.X509_STORE_CTX_init.restype = ctypes.c_int
        crypto.X509_verify_cert.argtypes = [ctypes.c_void_p]
        crypto.X509_verify_cert.restype = ctypes.c_int
        crypto.X509_STORE_CTX_get_error.argtypes = [ctypes.c_void_p]
        crypto.X509_STORE_CTX_get_error.restype = ctypes.c_int
        crypto.X509_verify_cert_error_string.argtypes = [ctypes.c_long]
        crypto.X509_verify_cert_error_string.restype = ctypes.c_char_p
    except Exception as error:
        return {
            "pass": False,
            "error": f"libcrypto interface unavailable: {type(error).__name__}: {error}",
            "attempted": 0,
        }

    store = crypto.X509_STORE_new()
    if not store:
        return {"pass": False, "error": "X509_STORE_new failed", "attempted": 0}
    attempted = 0
    last_error = "no hash-named CA certificates"
    verified = None
    try:
        if crypto.X509_STORE_set_default_paths(store) != 1:
            return {
                "pass": False,
                "error": "X509_STORE_set_default_paths failed",
                "attempted": 0,
            }
        for path in candidates:
            attempted += 1
            data = path.read_bytes()
            buffer = ctypes.create_string_buffer(data)
            bio = crypto.BIO_new_mem_buf(buffer, len(data))
            if not bio:
                last_error = f"BIO_new_mem_buf failed for {path.name}"
                continue
            cert = None
            try:
                cert = crypto.PEM_read_bio_X509(bio, None, None, None)
            finally:
                crypto.BIO_free(bio)
            if not cert:
                last_error = f"PEM_read_bio_X509 failed for {path.name}"
                continue
            ctx = crypto.X509_STORE_CTX_new()
            if not ctx:
                crypto.X509_free(cert)
                last_error = "X509_STORE_CTX_new failed"
                continue
            try:
                if crypto.X509_STORE_CTX_init(ctx, store, cert, None) != 1:
                    last_error = f"X509_STORE_CTX_init failed for {path.name}"
                    continue
                if crypto.X509_verify_cert(ctx) == 1:
                    verified = path.name
                    break
                code = crypto.X509_STORE_CTX_get_error(ctx)
                message = crypto.X509_verify_cert_error_string(code)
                last_error = (
                    message.decode("utf-8", "replace")
                    if message
                    else f"verification error {code}"
                )
            finally:
                crypto.X509_STORE_CTX_free(ctx)
                crypto.X509_free(cert)
    finally:
        crypto.X509_STORE_free(store)
    return {
        "pass": verified is not None,
        "verified_certificate": verified,
        "attempted": attempted,
        "candidate_count": len(candidates),
        "error": None if verified is not None else last_error,
    }
"""

RUNTIME_DATA_PROBE = CA_VERIFY_HELPER + r"""
import json, os, ssl, sysconfig, zoneinfo
paths = ssl.get_default_verify_paths()
try:
    certs = len(ssl.create_default_context().get_ca_certs())
    ca_error = None
except Exception as error:
    certs, ca_error = 0, f"{type(error).__name__}: {error}"
ca_default_verify = _default_ca_verification(paths.openssl_capath)
zones = {}
for key in ("Asia/Seoul", "America/New_York"):
    try:
        zoneinfo.ZoneInfo(key)
        zones[key] = "pass"
    except Exception as error:
        zones[key] = f"{type(error).__name__}: {error}"
print(json.dumps({
    "tzpath_configured": sysconfig.get_config_var("TZPATH"),
    "tzpath_runtime": list(zoneinfo.TZPATH),
    "tzpath_present": [p for p in zoneinfo.TZPATH if os.path.isdir(p)],
    "zones": zones,
    "openssl_cafile": paths.openssl_cafile,
    "openssl_cafile_present": bool(paths.openssl_cafile)
        and os.path.exists(paths.openssl_cafile),
    "openssl_capath": paths.openssl_capath,
    "openssl_capath_present": bool(paths.openssl_capath)
        and os.path.isdir(paths.openssl_capath),
    # Hash-directory certificates are loaded lazily by OpenSSL, so this count can
    # legitimately be zero before a verification. The offline verification above
    # is the authoritative result for a capath-only trust store.
    "ca_certificate_count": certs,
    "ca_default_verify": ca_default_verify,
    "ca_default_verify_pass": ca_default_verify["pass"],
    "ca_error": ca_error,
}))
"""

SUBPROCESS_PROBE = """
import json, subprocess, sys
result = subprocess.run(
    [sys.executable, "-c", "import sys; print(sys.prefix)"],
    capture_output=True, text=True,
)
print(json.dumps({
    "returncode": result.returncode,
    "stdout": result.stdout.strip(),
    "stderr": result.stderr.strip(),
}))
"""


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(
    command: list[str], env: dict[str, str]
) -> subprocess.CompletedProcess[str] | OSError:
    """Never raise. A probe that cannot even start is a result worth recording."""
    try:
        return subprocess.run(command, capture_output=True, text=True, env=env)
    except OSError as error:
        return error


def run_probe(interpreter: Path, source: str, env: dict[str, str]) -> dict[str, Any]:
    result = run([str(interpreter), "-c", source], env)
    if isinstance(result, OSError):
        return {"pass": False, "error": f"could not run the interpreter: {result}"}
    if result.returncode:
        return {"pass": False, "error": result.stderr.strip()[:2000]}
    try:
        return {"pass": True, **json.loads(result.stdout)}
    except json.JSONDecodeError:
        return {
            "pass": False,
            "error": f"probe did not emit JSON: {result.stdout[:500]}",
        }


def run_command(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    result = run(command, env)
    if isinstance(result, OSError):
        return {"pass": False, "stdout": "", "stderr": str(result)}
    return {
        "pass": result.returncode == 0,
        "stdout": result.stdout.strip()[:500],
        "stderr": result.stderr.strip()[:500],
    }


def clean_env(state: Path) -> dict[str, str]:
    """A caller-owned writable state root, and nothing inherited that could hide a bug."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key in ("PATH", "HOME", "LANG", "TERM", "ANDROID_DATA", "ANDROID_ROOT")
    }
    env.update(
        {
            "TMPDIR": str(state / "tmp"),
            "XDG_CACHE_HOME": str(state / "cache"),
            "PYTHONPYCACHEPREFIX": str(state / "pycache"),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "",
        }
    )
    for name in ("tmp", "cache", "pycache"):
        (state / name).mkdir(parents=True, exist_ok=True)
    return env


def extract(archive: Path, destination: Path) -> Path:
    with tarfile.open(archive) as tf:
        for member in tf.getmembers():
            if member.name.startswith("/") or ".." in Path(member.name).parts:
                raise RuntimeError(f"unsafe archive member: {member.name}")
        tf.extractall(destination, filter="data")
    prefix = destination / "python"
    if not (prefix / "bin").is_dir():
        raise RuntimeError(f"archive did not extract a python/bin: {archive}")
    return prefix


def interpreter_of(prefix: Path) -> Path:
    candidates = sorted(prefix.glob("bin/python3.*"))
    exact = [
        path
        for path in candidates
        if path.name.count(".") == 1 and not path.is_symlink()
    ]
    if not exact:
        raise RuntimeError(f"no versioned interpreter under {prefix}/bin")
    return exact[0]


def qualify(archive: Path, workspace: Path) -> dict[str, Any]:
    checks: dict[str, Any] = {}

    prefix = extract(archive, workspace / "runtime")
    interpreter = interpreter_of(prefix)
    env = clean_env(workspace / "state")

    checks["identity"] = run_probe(interpreter, IDENTITY_PROBE, env)
    checks["extensions"] = run_probe(interpreter, EXTENSIONS_PROBE, env)
    checks["dlopen"] = run_probe(interpreter, DLOPEN_PROBE, env)
    checks["subprocess"] = run_probe(interpreter, SUBPROCESS_PROBE, env)
    checks["runtime_data"] = run_probe(interpreter, RUNTIME_DATA_PROBE, env)

    # No LD_LIBRARY_PATH is set anywhere above: the relative RUNPATH has to be
    # doing the work on its own.
    checks["ld_library_path_required"] = {"pass": "LD_LIBRARY_PATH" not in env}

    # A relocated copy at a deeper path must behave identically.
    relocated_root = workspace / "relocated/a/deeper/path"
    relocated_root.mkdir(parents=True, exist_ok=True)
    relocated = relocated_root / "python"
    shutil.copytree(prefix, relocated, symlinks=True)
    checks["relocated_identity"] = run_probe(
        interpreter_of(relocated), IDENTITY_PROBE, env
    )

    # pip is installed from the distribution's own ensurepip wheel; it must at
    # least run offline.
    checks["pip"] = run_command([str(interpreter), "-m", "pip", "--version"], env)

    venv_dir = workspace / "state/venv"
    checks["venv"] = run_command(
        [str(interpreter), "-m", "venv", "--without-pip", str(venv_dir)], env
    )
    if checks["venv"]["pass"]:
        checks["venv_identity"] = run_probe(
            venv_dir / "bin/python", IDENTITY_PROBE, env
        )

    return checks


def evaluate(
    checks: dict[str, Any],
    expected_api: int | None,
    *,
    builtin_runtime_data: bool = False,
) -> dict[str, Any]:
    identity = checks.get("identity", {})
    failures: list[str] = []

    for name in (
        "identity",
        "extensions",
        "dlopen",
        "subprocess",
        "relocated_identity",
        "pip",
        "venv",
    ):
        if not checks.get(name, {}).get("pass"):
            failures.append(name)

    if checks.get("extensions", {}).get("failures"):
        failures.append("extension-import")
    dlopen = {
        k: v for k, v in checks.get("dlopen", {}).items() if k not in ("pass", "error")
    }
    if any(value != "pass" for value in dlopen.values()):
        failures.append("dlopen")
    if not identity.get("paths_within_prefix"):
        failures.append("paths-outside-prefix")
    if identity.get("multiarch") and "android" not in identity["multiarch"]:
        failures.append("not-android")
    relocated = checks.get("relocated_identity", {})
    if relocated.get("prefix") == identity.get("prefix"):
        failures.append("relocation-not-exercised")
    if expected_api is not None and identity.get("android_api_level") not in (
        expected_api,
        str(expected_api),
    ):
        failures.append("api-level-mismatch")

    # Only a build that compiles these paths in is expected to resolve them with
    # nothing set. For one that ships an external data product, finding no trust
    # store here is the documented behaviour rather than a fault.
    runtime_data = checks.get("runtime_data", {})
    if not runtime_data.get("pass"):
        failures.append("runtime_data")
    elif builtin_runtime_data and not (
        runtime_data.get("ca_certificate_count")
        or runtime_data.get("ca_default_verify_pass")
    ):
        failures.append("builtin-ca-unverified")

    return {"pass": not failures, "failures": sorted(set(failures))}


def device() -> dict[str, Any]:
    def getprop(name: str) -> str | None:
        try:
            result = subprocess.run(
                ["getprop", name], capture_output=True, text=True, timeout=10
            )
        except (OSError, subprocess.SubprocessError):
            return None
        value = result.stdout.strip()
        return value or None

    return {
        "model": getprop("ro.product.model"),
        "android_release": getprop("ro.build.version.release"),
        "api_level": getprop("ro.build.version.sdk"),
        "abi": getprop("ro.product.cpu.abi"),
        "machine": platform.machine(),
        "context": "termux" if "com.termux" in sys.prefix else "unknown",
        "page_size": os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else None,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="the install-only archive to run")
    parser.add_argument(
        "--also-binds",
        type=Path,
        nargs="*",
        default=[],
        help="sibling artifacts of the same build to record identities for",
    )
    parser.add_argument("--expected-api", type=int)
    parser.add_argument(
        "--builtin-runtime-data",
        action="store_true",
        help="require CA certificates to resolve with nothing set",
    )
    parser.add_argument("-o", "--output", type=Path, help="where to write the receipt")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.archive.is_file():
        print(f"no such archive: {args.archive}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="qualify-") as tmp:
        checks = qualify(args.archive, Path(tmp))

    verdict = evaluate(
        checks, args.expected_api, builtin_runtime_data=args.builtin_runtime_data
    )
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "receipt_kind": "android-device-qualification",
        "executed_artifact": {
            "filename": args.archive.name,
            "sha256": sha256_path(args.archive),
            "size_bytes": args.archive.stat().st_size,
        },
        "bound_artifacts": [
            {
                "filename": path.name,
                "sha256": sha256_path(path),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted(args.also_binds)
            if path.is_file()
        ],
        "device": device(),
        "expectations": {"builtin_runtime_data": args.builtin_runtime_data},
        "checks": checks,
        "verdict": verdict,
    }

    output = args.output or Path(f"{args.archive.name}.qualification.json")
    output.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{'PASS' if verdict['pass'] else 'FAIL'}  {output}")
    if not verdict["pass"]:
        print(f"failed checks: {', '.join(verdict['failures'])}", file=sys.stderr)
    return 0 if verdict["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
