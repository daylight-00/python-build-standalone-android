"""Build CPython's Android dependency set from source.

The upstream Android flow downloads prebuilt dependency archives. Those are
built with OpenSSL's default ``openssldir`` of ``/usr/local/ssl``, a path that
does not exist on Android, so the runtime they produce can never resolve a
trust store. ``openssldir`` is fixed when OpenSSL is compiled, so the only way
to change it is to be the one compiling.

The recipes are upstream's, pinned at one commit. Two overrides are applied and
both are recorded in the build: the NDK revision, so the dependencies and the
interpreter are built with one toolchain, and ``openssldir``.

One commit rather than each component's own release tag, because those tags are
not contemporaneous. The older ones read the API level from a lowercase
``api_level`` variable that a caller setting ``ANDROID_API_LEVEL`` never
reaches, and they pin different NDK revisions — which silently produced a
dependency set built at two different API levels.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .archive import safe_extract_tar
from .downloads import acquire
from .elf import android_note, elf_objects
from .targets import ROOT
from .utils import file_identity, read_json_object, run_checked, sha256_path

RECIPE_LOCK = ROOT / "config/source/dependency-recipes.lock.json"


@dataclass(frozen=True)
class Override:
    """A recorded, exact edit to an upstream recipe.

    The pattern must match exactly once. Pinned tags cannot change under us, so
    a miss means a tag was bumped without revisiting the override — which should
    stop the build rather than silently produce something else. The text that
    was replaced is recorded, so the build says what it changed and from what.
    """

    path: str
    pattern: str
    replace: str
    reason: str

    def apply(self, root: Path) -> dict[str, Any]:
        target = root / self.path
        text = target.read_text(encoding="utf-8")
        matches = list(re.finditer(self.pattern, text, re.M))
        if len(matches) != 1:
            raise RuntimeError(
                f"override for {self.path} matched {len(matches)} times, expected 1.\n"
                f"  pattern: {self.pattern}\n"
                f"  reason: {self.reason}\n"
                f"The pinned recipe changed; revisit the override."
            )
        original = matches[0].group(0)
        target.write_text(re.sub(self.pattern, self.replace, text, flags=re.M), encoding="utf-8")
        return {
            "path": self.path,
            "was": original,
            "now": self.replace,
            "reason": self.reason,
        }


def _ndk_override(revision: str) -> Override:
    # Matched by line, not by value: the recipe tags do not all pin the same
    # revision, and which one a given tag pinned is provenance worth recording
    # rather than a constant to hard-code.
    return Override(
        path="android-env.sh",
        pattern=r"^ndk_version=.*$",
        replace=f"ndk_version={revision}",
        reason=(
            "the recipe tags pin NDK revisions behind the one CPython pins, and not "
            "all the same one; building the dependencies and the interpreter with "
            "different toolchains is a difference nobody chose"
        ),
    )


def _openssldir_override(openssldir: str) -> Override:
    return Override(
        path="openssl/build.sh",
        pattern=r"^\./Configure android-python\$bits shared$",
        replace=f"./Configure android-python$bits shared --openssldir={openssldir}",
        reason=(
            "OpenSSL's default openssldir is /usr/local/ssl, which does not exist on "
            "Android, so the trust store can never resolve"
        ),
    )


def _acquire_recipes(repository: str, commit: str, destination: Path) -> str:
    if not (destination / ".git").is_dir():
        destination.parent.mkdir(parents=True, exist_ok=True)
        run_checked(
            ["git", "clone", "-q", repository, str(destination)],
            "cloning the recipe repository",
        )
    run_checked(["git", "-C", str(destination), "checkout", "-q", "--", "."], "recipe reset")
    run_checked(["git", "-C", str(destination), "checkout", "-q", commit], f"checking out {commit}")
    return run_checked(
        ["git", "-C", str(destination), "rev-parse", "HEAD"], "reading the recipe commit"
    ).stdout.strip()


def resolved_compiler(repo: Path, host: str, environment: dict[str, str]) -> str:
    """The compiler the recipe environment actually selects.

    The API level reaches the compiler only through the recipe's own environment
    script, and older revisions of that script read a differently named
    variable. Asking the script what it resolved is the only way to know the
    request landed.
    """
    result = run_checked(
        ["bash", "-c", f'set -eu; HOST={host}; . ./android-env.sh; echo "$CC"'],
        "resolving the recipe compiler",
        cwd=repo,
        env=environment,
    )
    return Path(result.stdout.strip()).name


def build_dependencies(
    *,
    workspace: Path,
    cache: Path,
    ndk_revision: str,
    android_api: int,
    host: str,
    readelf: str,
    lock_path: Path = RECIPE_LOCK,
) -> tuple[Path, dict[str, Any]]:
    """Build every dependency from source and merge them into one prefix."""
    lock = read_json_object(lock_path)
    repo = workspace / "recipes"
    commit = _acquire_recipes(lock["recipes"]["repository"], lock["recipes"]["commit"], repo)

    prefix = workspace / "prefix"
    prefix.mkdir(parents=True, exist_ok=True)

    environment = dict(os.environ)
    environment["ANDROID_API_LEVEL"] = str(android_api)

    # One revision, so the overrides are applied once and every component is
    # built the same way.
    openssldir = next((c["openssldir"] for c in lock["components"] if c.get("openssldir")), None)
    overrides = [_ndk_override(ndk_revision)]
    if openssldir:
        overrides.append(_openssldir_override(openssldir))
    applied = [override.apply(repo) for override in overrides]

    compiler = resolved_compiler(repo, host, environment)
    if compiler != f"{host}{android_api}-clang":
        raise RuntimeError(
            f"the recipe environment resolved CC to {compiler}, "
            f"not {host}{android_api}-clang; the API level did not reach the compiler"
        )

    records: list[dict[str, Any]] = []
    for component in lock["components"]:
        name, version = component["name"], component["version"]

        # The recipes fetch their sources with wget and no checksum. Placing the
        # verified file where the recipe expects it means wget finds it already
        # complete, and the identity below is the one that was actually built.
        source = acquire(component["source"], cache, what=f"{name} source")
        download_dir = repo / name / "build" / version
        download_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, download_dir / component["source"]["filename"])

        run_checked(
            [
                str(repo / "build.sh"),
                name,
                version,
                str(component["build"]),
                host,
            ],
            f"building {name} {version} from source",
            cwd=repo,
            env=environment,
        )

        produced = download_dir / host / f"{name}-{version}-{component['build']}-{host}.tar.gz"
        if not produced.is_file():
            raise RuntimeError(f"{name} recipe did not produce {produced}")
        safe_extract_tar(produced, prefix)

        records.append(
            {
                "name": name,
                "version": version,
                "build": component["build"],
                "source": file_identity(source),
                "produced": file_identity(produced),
            }
        )

    return prefix, {
        "schema_version": 1,
        "repository": lock["recipes"]["repository"],
        "recipe_commit": commit,
        "compiler": compiler,
        "overrides": applied,
        "android_api": android_api,
        "ndk_revision": ndk_revision,
        "host": host,
        "components": records,
        "objects": verify_prefix(prefix, android_api=android_api, readelf=readelf),
    }


def verify_prefix(prefix: Path, *, android_api: int, readelf: str) -> dict[str, Any]:
    """Every object must report the API level the build claims to target.

    The note comes from the binary rather than from the build that produced it,
    so a recipe that quietly ignored the environment is caught here.
    """
    objects = elf_objects(prefix)
    if not objects:
        raise RuntimeError(f"no ELF objects were built into {prefix}")

    mismatched: list[str] = []
    unstamped: list[str] = []
    for path in objects:
        rel = path.relative_to(prefix).as_posix()
        note = android_note(path, readelf)
        if note is None:
            unstamped.append(rel)
        elif note["api_level"] != android_api:
            mismatched.append(f"{rel} reports API {note['api_level']}")
    if mismatched:
        raise RuntimeError(
            f"objects were not built for API {android_api}: {', '.join(mismatched[:5])}"
        )

    sample = android_note(objects[0], readelf) or {}
    return {
        "object_count": len(objects),
        "api_level": android_api,
        "ndk_version": sample.get("ndk_version"),
        "ndk_build_number": sample.get("ndk_build_number"),
        "unstamped": unstamped,
        "sha256": {path.relative_to(prefix).as_posix(): sha256_path(path) for path in objects},
    }
