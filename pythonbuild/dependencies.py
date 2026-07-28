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

import hashlib
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
from .toolchain import pkg_config_identity
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
        # Spliced by span rather than substituted: a replacement is literal text,
        # and `re.sub` would read backslashes and group references in it.
        start, end = matches[0].span()
        original = matches[0].group(0)
        target.write_text(text[:start] + self.replace + text[end:], encoding="utf-8")
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


def file_prefix_map_override(host_paths: tuple[tuple[str, str], ...]) -> Override:
    """Keep host directories out of compiled debug information.

    Two of them get in: the build tree, through the file names of everything
    compiled, and the NDK, through the sysroot include directories recorded in
    every object's line table. Neither is reachable by a text pass, so two hosts
    produce different bytes from the same input. The recipe environment assigns
    CFLAGS rather than appending to it, so the flags have to go in there rather
    than being passed through.
    """
    flags = " ".join(f"-ffile-prefix-map={path}={placeholder}" for path, placeholder in host_paths)
    return Override(
        path="android-env.sh",
        pattern=r'^export CFLAGS="-D__BIONIC_NO_PAGE_SIZE_MACRO"$',
        replace=f'export CFLAGS="-D__BIONIC_NO_PAGE_SIZE_MACRO {flags}"',
        reason=(
            "the build tree and the toolchain location would otherwise be recorded in "
            "every compiled object's debug information, which nothing downstream can rewrite"
        ),
    )


def bare_toolchain_override() -> Override:
    """Name the tools without the directory they happen to live in.

    A build records the command line it was given: OpenSSL writes the compiler
    invocation into libcrypto as a string, and configure writes it into
    ``CONFIG_ARGS``. An absolute toolchain path there belongs to the machine that
    built the distribution, and a string inside a shared object is not something
    a later pass can rewrite. Found on PATH instead, so the same build works
    wherever the NDK is installed.

    ``LD`` is left alone. It is the one tool whose bare name is also a host tool's,
    and it is not recorded anywhere, so making it ambiguous would buy nothing.
    """
    return Override(
        path="android-env.sh",
        pattern=r'^export CXXFLAGS="\$CFLAGS"$',
        replace="""export CXXFLAGS="$CFLAGS"

export PATH="$toolchain/bin:$PATH"
for _tool in AR AS CC CXX NM RANLIB READELF STRIP; do
    eval "export $_tool=\\${$_tool##*/}"
done
unset _tool""",
        reason=(
            "an absolute toolchain path is recorded in strings no later pass can "
            "rewrite: OpenSSL's compiler banner and configure's CONFIG_ARGS"
        ),
    )


def relocate_pkgconfig(prefix: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make each ``.pc`` file describe the prefix it is in.

    A component writes the directory it was configured in, and not only into
    ``prefix``: xz writes ``includedir`` and ``libdir`` out in full as well. Those
    are paths on this machine, they decide which include and library directories
    pkg-config hands to configure, and they made the merged prefix depend on where
    the build ran. Every use of the recorded prefix is expressed relative to it,
    and the prefix itself relative to the file — the form the shipped ``.pc`` files
    already use.

    Done before the component's contents are recorded, so the record describes
    what is in the prefix.
    """
    updated: list[dict[str, Any]] = []
    for row in rows:
        path = prefix / row["path"]
        if row["type"] != "file" or not row["path"].endswith(".pc") or path.is_symlink():
            updated.append(row)
            continue
        text = path.read_text(encoding="utf-8")
        rewritten = _relocate_pc(text)
        if rewritten == text:
            updated.append(row)
            continue
        path.write_text(rewritten, encoding="utf-8")
        updated.append({**row, "size": path.stat().st_size, "sha256": sha256_path(path)})
    return updated


def drop_libtool_archives(prefix: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove libtool's bookkeeping from the merged prefix.

    A ``.la`` file records the absolute directory its library was installed to,
    and there is no relocatable way to write that. Nothing here reads them — the
    interpreter links through pkg-config — and they are curated out of every
    distribution, so all they contribute is a record of where the build ran.
    """
    kept: list[dict[str, Any]] = []
    for row in rows:
        if row["type"] == "file" and row["path"].endswith(".la"):
            (prefix / row["path"]).unlink()
            continue
        kept.append(row)
    return kept


def _relocate_pc(text: str) -> str:
    recorded = next(
        (line[len("prefix=") :] for line in text.splitlines() if line.startswith("prefix=")), ""
    )
    if recorded.startswith("/"):
        text = text.replace(recorded, "${prefix}")
    return (
        "\n".join(
            "prefix=${pcfiledir}/../.." if line.startswith("prefix=") else line
            for line in text.splitlines()
        )
        + "\n"
    )


def _acquire_recipes(repository: str, commit: str, destination: Path) -> str:
    if not (destination / ".git").is_dir():
        destination.parent.mkdir(parents=True, exist_ok=True)
        run_checked(
            ["git", "clone", "-q", repository, str(destination)],
            "cloning the recipe repository",
        )
    _reset(destination)
    run_checked(["git", "-C", str(destination), "checkout", "-q", commit], f"checking out {commit}")
    return run_checked(
        ["git", "-C", str(destination), "rev-parse", "HEAD"], "reading the recipe commit"
    ).stdout.strip()


def _reset(repo: Path) -> None:
    run_checked(["git", "-C", str(repo), "checkout", "-q", "--", "."], "recipe reset")


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


def content_digest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """A digest over what an archive contained, independent of how it was packed."""
    files = sorted((row["path"], row["sha256"]) for row in rows if row["type"] == "file")
    digest = hashlib.sha256()
    for path, sha256 in files:
        digest.update(f"{path}\0{sha256}\0".encode())
    return {"file_count": len(files), "sha256": digest.hexdigest()}


def build_dependencies(
    *,
    workspace: Path,
    cache: Path,
    ndk_revision: str,
    android_api: int,
    host: str,
    readelf: str,
    source_date_epoch: int,
    host_paths: tuple[tuple[str, str], ...],
    pkg_config_bin: Path,
    lock_path: Path = RECIPE_LOCK,
) -> tuple[Path, dict[str, Any]]:
    """Build every dependency from source and merge them into one prefix."""
    lock = read_json_object(lock_path)
    repo = workspace / "recipes"
    commit = _acquire_recipes(lock["recipes"]["repository"], lock["recipes"]["commit"], repo)

    # From scratch every time. The workspace persists between runs so the clone
    # and the downloads are reused, but a prefix left behind would merge with
    # this one and make the result depend on what was built before.
    prefix = workspace / "prefix"
    shutil.rmtree(prefix, ignore_errors=True)
    prefix.mkdir(parents=True)

    environment = dict(os.environ)
    environment["ANDROID_API_LEVEL"] = str(android_api)
    environment["SOURCE_DATE_EPOCH"] = str(source_date_epoch)
    environment["PATH"] = os.pathsep.join([str(pkg_config_bin), environment.get("PATH", "")])
    # A search path inherited from the host would decide which .pc file is read.
    environment.pop("PKG_CONFIG_PATH", None)

    # One recipe revision, so every component is built the same way. The
    # overrides are not identical for every component: OpenSSL needs one the
    # others do not.
    openssldir = next((c["openssldir"] for c in lock["components"] if c.get("openssldir")), None)
    prefix_map = file_prefix_map_override(host_paths)

    def overrides_for(name: str) -> list[Override]:
        overrides = [_ndk_override(ndk_revision), bare_toolchain_override()]
        # Every component but OpenSSL: their static objects are linked into
        # extension modules and carry host directories in their debug
        # information. OpenSSL writes the whole compiler command line into
        # libcrypto as a string, so a flag naming the path it exists to hide
        # would put that path into the binary, where nothing can rewrite it.
        # Its own objects carry no debug information to protect.
        if name != "openssl":
            overrides.append(prefix_map)
        elif openssldir:
            overrides.append(_openssldir_override(openssldir))
        return overrides

    # The compiler is resolved from the patched environment script, since the NDK
    # revision it names is one of the things being overridden.
    for override in overrides_for("probe"):
        override.apply(repo)
    compiler = resolved_compiler(repo, host, environment)
    if compiler != f"{host}{android_api}-clang":
        raise RuntimeError(
            f"the recipe environment resolved CC to {compiler}, "
            f"not {host}{android_api}-clang; the API level did not reach the compiler"
        )

    records: list[dict[str, Any]] = []
    applied: dict[str, list[dict[str, Any]]] = {}
    for component in lock["components"]:
        name, version = component["name"], component["version"]
        # Reset and re-apply per component: the overrides differ for OpenSSL, and
        # the exactly-once guard would not match an already-patched file.
        _reset(repo)
        applied[name] = [override.apply(repo) for override in overrides_for(name)]

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
        rows = relocate_pkgconfig(prefix, safe_extract_tar(produced, prefix))
        rows = drop_libtool_archives(prefix, rows)

        # The identity of what the component contributed, not of the tarball the
        # recipe wrapped it in: that wrapper is written with `tar -czf`, whose
        # gzip header carries the time it ran, so its hash changes every build
        # while the contents do not.
        records.append(
            {
                "name": name,
                "version": version,
                "build": component["build"],
                "source": file_identity(source),
                "content": content_digest(rows),
            }
        )

    return prefix, {
        "schema_version": 1,
        "repository": lock["recipes"]["repository"],
        "recipe_commit": commit,
        "compiler": compiler,
        "pkg_config": pkg_config_identity(),
        "overrides": applied,
        "android_api": android_api,
        "ndk_revision": ndk_revision,
        "source_date_epoch": source_date_epoch,
        "host": host,
        "components": records,
        "objects": verify_dependency_prefix(prefix, android_api=android_api, readelf=readelf),
    }


def verify_dependency_prefix(prefix: Path, *, android_api: int, readelf: str) -> dict[str, Any]:
    """Every object must report the API level the build claims to target.

    The note comes from the binary rather than from the build that produced it,
    so a recipe that quietly ignored the environment is caught here.

    This records more than its counterpart for the finished prefix does: which
    objects carry no note at all, because a component's static archives do not,
    and a hash per object, because nothing else in the build pins what a
    component contributed. A distribution's members are pinned by its manifest.
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
