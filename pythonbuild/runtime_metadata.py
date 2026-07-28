"""Consumer metadata overlay over the upstream CPython metadata.

The upstream producer records stay present and truthful — ``CONFIG_ARGS``,
``BUILD_GNU_TYPE``, ``HOST_GNU_TYPE``, ``SOABI``, ``MULTIARCH``, ``EXT_SUFFIX``,
and ``ANDROID_API_LEVEL`` are never rewritten. Only the consumer-facing paths
and compiler entry points are overlaid, so that a relocated prefix reports its
own locations and ``uv python install`` accepts the distribution.

The split between the literal mapping and the trailing code matters. uv parses
and rewrites only the literal ``build_time_vars = {...}`` mapping, so anything
that must survive a managed install has to live there as an ``/install``
placeholder. The trailing overlay resolves those placeholders for a directly
unpacked tree; uv discards it after substituting its own prefix.
"""

from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any

from .utils import read_json, sha256_path, sha256_text, write_json

CANONICAL_HEADER = "# system configuration generated and used by the sysconfig module"
PRODUCER_ROOTS = ("/Users/runner/", "/home/runner/", "/data/data/com.termux/", "/usr/local")
PROFILE = "upstream-preserved-minimal-consumer-overlay"

PRESERVED_PRODUCER_KEYS = (
    "CONFIG_ARGS",
    "BUILD_GNU_TYPE",
    "HOST_GNU_TYPE",
    "SOABI",
    "MULTIARCH",
    "EXT_SUFFIX",
    "ANDROID_API_LEVEL",
)

CFLAGS = (
    "-fno-strict-overflow -Wsign-compare -Wunreachable-code -DNDEBUG -O2 -Wall "
    "-D__BIONIC_NO_PAGE_SIZE_MACRO"
)
LDFLAGS = (
    "-Wl,--build-id=sha1 -Wl,--no-rosegment "
    "-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384"
)


class Layout:
    """The path vocabulary of one install prefix."""

    def __init__(self, python_mm: str, host_triple: str) -> None:
        self.python_mm = python_mm
        self.host_triple = host_triple
        self.stdlib = f"lib/python{python_mm}"
        self.config_dir = f"{self.stdlib}/config-{python_mm}-{host_triple}"
        self.include = f"include/python{python_mm}"
        self.libpython = f"lib/libpython{python_mm}.so"
        self.ext_suffix = f".cpython-{python_mm.replace('.', '')}-{host_triple}.so"


def _literal_build_time_vars(text: str) -> dict[str, Any]:
    """Read the literal mapping exactly the way uv's parser reads it."""
    tree = ast.parse(text)
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "build_time_vars":
            values = ast.literal_eval(node.value)
            if not isinstance(values, dict):
                break
            if not all(
                isinstance(key, str) and isinstance(value, str | int)
                for key, value in values.items()
            ):
                raise RuntimeError("sysconfig mapping holds values uv's parser cannot represent")
            return dict(values)
    raise RuntimeError("literal build_time_vars mapping missing")


def _execute_sysconfigdata(path: Path) -> dict[str, Any]:
    namespace: dict[str, Any] = {"__file__": str(path)}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    values = namespace.get("build_time_vars")
    if not isinstance(values, dict):
        raise RuntimeError(f"build_time_vars missing: {path}")
    return values


def _literal_updates(layout: Layout) -> dict[str, str]:
    """Values that must survive uv's rewrite, as ``/install`` placeholders."""
    ldshared = "clang -shared " + LDFLAGS
    return {
        "BINDIR": "/install/bin",
        "BINLIBDEST": f"/install/{layout.stdlib}",
        "LIBDEST": f"/install/{layout.stdlib}",
        "SCRIPTDIR": "/install/lib",
        "INCLUDEDIR": "/install/include",
        "CONFINCLUDEDIR": "/install/include",
        "INCLUDEPY": f"/install/{layout.include}",
        "CONFINCLUDEPY": f"/install/{layout.include}",
        "LIBDIR": "/install/lib",
        "LIBPL": f"/install/{layout.config_dir}",
        "DESTSHARED": f"/install/{layout.stdlib}/lib-dynload",
        "CC": "clang",
        "CXX": "clang++",
        "AR": "llvm-ar",
        "ARFLAGS": "rcs",
        "CCSHARED": "-fPIC",
        "CFLAGS": CFLAGS,
        "PY_CFLAGS": CFLAGS,
        "PY_STDMODULE_CFLAGS": CFLAGS + " -fPIC",
        "CPPFLAGS": "",
        "PY_CPPFLAGS": "",
        "LDFLAGS": LDFLAGS,
        "PY_LDFLAGS": LDFLAGS,
        "PY_CORE_LDFLAGS": LDFLAGS,
        "LDSHARED": ldshared,
        "BLDSHARED": ldshared,
        "LINKCC": "clang",
        "LDCXXSHARED": "clang++ -shared " + LDFLAGS,
        "BLDLIBRARY": f"-L /install/lib -lpython{layout.python_mm}",
        "LIBPYTHON": "",
        "SHELL": "sh -e",
        # Resolved from the build machine's PATH, so it names whichever mkdir that
        # machine happened to find. The Makefile overlay drops it for the same reason.
        "MKDIR_P": "mkdir -p",
        "ANDROID_METADATA_PROFILE": PROFILE,
        "ANDROID_CROSS_BUILD_SDK": "not-bundled",
    }


def _runtime_overlay(layout: Layout) -> str:
    """Code that resolves ``/install`` for a directly unpacked tree.

    Deliberately outside the literal mapping: direct execution evaluates it,
    while uv drops it once it has substituted the managed prefix.
    """
    return f"""

# BEGIN direct-runtime path resolution
import os as _pbsa_os
_pbsa_prefix = _pbsa_os.path.dirname(
    _pbsa_os.path.dirname(_pbsa_os.path.dirname(_pbsa_os.path.abspath(__file__)))
)
_pbsa_lib = _pbsa_os.path.join(_pbsa_prefix, "lib")
_pbsa_stdlib = _pbsa_os.path.join(_pbsa_lib, "python{layout.python_mm}")
_pbsa_include = _pbsa_os.path.join(_pbsa_prefix, "include", "python{layout.python_mm}")
_pbsa_config = _pbsa_os.path.join(
    _pbsa_stdlib, "config-{layout.python_mm}-{layout.host_triple}"
)
build_time_vars.update({{
    "BINDIR": _pbsa_os.path.join(_pbsa_prefix, "bin"),
    "BINLIBDEST": _pbsa_stdlib,
    "LIBDEST": _pbsa_stdlib,
    "SCRIPTDIR": _pbsa_lib,
    "INCLUDEDIR": _pbsa_os.path.join(_pbsa_prefix, "include"),
    "CONFINCLUDEDIR": _pbsa_os.path.join(_pbsa_prefix, "include"),
    "INCLUDEPY": _pbsa_include,
    "CONFINCLUDEPY": _pbsa_include,
    "LIBDIR": _pbsa_lib,
    "LIBPL": _pbsa_config,
    "DESTSHARED": _pbsa_os.path.join(_pbsa_stdlib, "lib-dynload"),
    "BLDLIBRARY": "-L" + _pbsa_lib + " -lpython{layout.python_mm}",
}})
del _pbsa_config, _pbsa_include, _pbsa_stdlib, _pbsa_lib, _pbsa_prefix, _pbsa_os
# END direct-runtime path resolution
"""


def _render_literal(values: dict[str, Any]) -> str:
    rows = [CANONICAL_HEADER, "build_time_vars = {"]
    for key in sorted(values):
        value = values[key]
        if not isinstance(key, str) or not isinstance(value, str | int):
            raise RuntimeError(f"unsupported sysconfig value: {key}={type(value).__name__}")
        rows.append(f"    {key!r}: {value!r},")
    rows.append("}")
    return "\n".join(rows) + "\n"


def _overlay_sysconfigdata(path: Path, layout: Layout) -> dict[str, Any]:
    before_text = path.read_text(encoding="utf-8")
    if not before_text.startswith(CANONICAL_HEADER):
        # uv requires the canonical header to recognise the file it must rewrite.
        raise RuntimeError("upstream sysconfigdata lacks its canonical header comment")
    before_vars = _execute_sysconfigdata(path)
    values = _literal_build_time_vars(before_text)
    updates = _literal_updates(layout)
    values.update(updates)
    rendered = _render_literal(values) + _runtime_overlay(layout)
    compile(rendered, str(path), "exec")
    path.write_text(rendered, encoding="utf-8")

    after_vars = _execute_sysconfigdata(path)
    preserved = {
        key: before_vars.get(key) == after_vars.get(key) for key in PRESERVED_PRODUCER_KEYS
    }
    if not all(preserved.values()):
        changed = sorted(key for key, ok in preserved.items() if not ok)
        raise RuntimeError(f"overlay changed producer or target identity: {changed}")
    managed_visible = _literal_build_time_vars(rendered)
    for key, expected in updates.items():
        if managed_visible.get(key) != expected:
            raise RuntimeError(f"value invisible to uv's rewrite: {key}")
    return {
        "path": path.name,
        "before_sha256": sha256_text(before_text),
        "after_sha256": sha256_path(path),
        "canonical_header_preserved": True,
        "producer_and_target_identity_preserved": preserved,
        "uv_managed_rewrite_compatible": True,
        "literal_mapping_mutated_keys": sorted(updates),
    }


def _patch_makefile(path: Path, layout: Layout) -> dict[str, Any]:
    original = path.read_text(encoding="utf-8")
    overrides = {
        "CC": "clang",
        "CXX": "clang++",
        "AR": "llvm-ar",
        "ARFLAGS": "rcs",
        "SHELL": "sh -e",
        # These name the tree the interpreter was built in, which no consumer of
        # a distribution has. Left as configure wrote them they publish the build
        # machine's layout — upstream's own package ships its release runner's
        # paths this way — and for a build of our own they would make two hosts
        # produce different bytes. Emptied rather than pointed somewhere
        # plausible, so a rule that needs them fails instead of silently reading
        # the wrong tree.
        "abs_srcdir": "",
        "abs_builddir": "",
        "srcdir": ".",
        # configure records the flags it was handed, absolute include paths and
        # all. The overlay already states the flags a consumer should use.
        "CONFIGURE_CFLAGS": "$(CFLAGS)",
        "CONFIGURE_CPPFLAGS": "",
        "CONFIGURE_LDFLAGS": "$(LDFLAGS)",
        # Resolved from the build machine's PATH, so it differs between hosts.
        "MKDIR_P": "mkdir -p",
        "CFLAGS": CFLAGS,
        "PY_CFLAGS": "$(CFLAGS)",
        "CPPFLAGS": "",
        "PY_CPPFLAGS": "",
        "LDFLAGS": LDFLAGS,
        "PY_LDFLAGS": "$(LDFLAGS)",
        "PY_CORE_LDFLAGS": "$(LDFLAGS)",
        "LDSHARED": "clang -shared $(LDFLAGS)",
        "BLDSHARED": "clang -shared $(LDFLAGS)",
        "BLDLIBRARY": f"-L$(LIBDIR) -lpython{layout.python_mm}",
    }
    output: list[str] = []
    seen: set[str] = set()
    for line in original.splitlines():
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if not match:
            output.append(line)
            continue
        key = match.group(1)
        if key == "prefix":
            output.append("prefix := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../..)")
            seen.add(key)
        elif key in overrides:
            output.append(f"{key}=\t\t{overrides[key]}")
            seen.add(key)
        else:
            output.append(line)
    output.extend(f"{key}=\t\t{value}" for key, value in overrides.items() if key not in seen)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    return {
        "path": path.name,
        "before_sha256": sha256_text(original),
        "after_sha256": sha256_path(path),
        "dynamic_prefix": True,
        "overridden_keys": sorted(overrides),
    }


def _patch_pkgconfig(pkgdir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not pkgdir.is_dir():
        return rows
    for path in sorted(pkgdir.glob("*.pc")):
        if path.is_symlink():
            continue
        before = path.read_text(encoding="utf-8")
        lines: list[str] = []
        for line in before.splitlines():
            if line.startswith("prefix="):
                lines.append("prefix=${pcfiledir}/../..")
            elif "$(BLDLIBRARY)" in line:
                lines.append(line.replace(" $(BLDLIBRARY)", ""))
            else:
                lines.append(line)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rows.append(
            {
                "path": path.name,
                "before_sha256": sha256_text(before),
                "after_sha256": sha256_path(path),
                "prefix": "${pcfiledir}/../..",
            }
        )
    return rows


def _patch_build_details(path: Path, layout: Layout) -> dict[str, Any]:
    before_text = path.read_text(encoding="utf-8")
    data = json.loads(before_text)
    data["base_interpreter"] = f"bin/python{layout.python_mm}"
    data["base_prefix"] = "."
    if isinstance(data.get("c_api"), dict):
        data["c_api"]["headers"] = layout.include
        data["c_api"]["pkgconfig_path"] = "lib/pkgconfig"
    if isinstance(data.get("suffixes"), dict):
        data["suffixes"]["extensions"] = [layout.ext_suffix, ".abi3.so", ".so"]
    if isinstance(data.get("libpython"), dict):
        data["libpython"]["dynamic"] = layout.libpython
        data["libpython"]["dynamic_stableabi"] = "lib/libpython3.so"
    data["path_semantics"] = "relative-to-runtime-root"
    write_json(path, data)
    return {
        "before_sha256": sha256_text(before_text),
        "after_sha256": sha256_path(path),
        "path_semantics": "relative-to-runtime-root",
    }


def _strip_shebang(path: Path) -> dict[str, Any]:
    before = path.read_text(encoding="utf-8")
    lines = before.splitlines()
    if lines and lines[0].startswith("#!"):
        lines = lines[1:]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o644)
    return {
        "path": path.name,
        "before_sha256": sha256_text(before),
        "after_sha256": sha256_path(path),
        "shebang": None,
    }


def relative_shell_wrapper(python_mm: str, arguments: str) -> str:
    """A wrapper that finds its sibling interpreter without any absolute path."""
    return (
        "#!/system/bin/sh\n"
        'case "$0" in /*) _script="$0" ;; *) _script="$(pwd)/$0" ;; esac\n'
        "_bindir=${_script%/*}\n"
        f'exec "$_bindir/python{python_mm}" {arguments} "$@"\n'
    )


HOST_DISCOVERED_VARS = {
    # configure resolved this by searching the build machine's PATH, so it names
    # whichever mkdir that machine happened to find first. The Makefile and
    # sysconfigdata overlays drop it for the same reason.
    "MKDIR_P": "mkdir -p",
    # The build interpreter's own user base, which is the build user's home.
    "userbase": "",
}


def drop_host_discovered_values(sysdata: Path, sysvars: Path, makefile: Path) -> dict[str, Any]:
    """Remove the values configure and the build interpreter took from this machine.

    ``MKDIR_P`` is whichever ``mkdir`` came first on the build machine's PATH, and
    ``userbase`` is the build user's home. ``sysconfig`` recomputes both at
    runtime, so nothing reads what is stored here, and they are the only values in
    these files that describe the machine rather than the target.

    Done before any of these files is hashed, so that what the overlay records
    about a file describes the file as it will ship, rather than a state that
    existed only on the machine that built it.
    """
    return {
        sysvars.name: _patch_sysconfig_vars_json(sysvars)["dropped_keys"],
        makefile.name: _drop_assignments(makefile, r"^{key}[ \t]*=[ \t]*(?P<value>.*)$"),
        sysdata.name: _drop_assignments(sysdata, r"'{key}': '(?P<value>[^']*)'"),
    }


def _drop_assignments(path: Path, pattern: str) -> list[str]:
    text = path.read_text(encoding="utf-8")
    dropped: list[str] = []
    for key, replacement in HOST_DISCOVERED_VARS.items():
        match = re.search(pattern.format(key=re.escape(key)), text, re.M)
        if match is None or match.group("value") == replacement:
            continue
        start, end = match.span("value")
        text = text[:start] + replacement + text[end:]
        dropped.append(key)
    if dropped:
        path.write_text(text, encoding="utf-8")
    return sorted(dropped)


def _patch_sysconfig_vars_json(path: Path) -> dict[str, Any]:
    """Drop what this file recorded about the machine that built it.

    Everything else is preserved byte for byte, which is checked rather than
    assumed: the payload is re-serialised untouched first and has to reproduce
    the file. If CPython ever writes it differently, that fails here instead of
    silently reformatting a file consumers read.
    """
    before = path.read_bytes()
    payload = json.loads(before)
    if _dump_sysconfig_vars(payload) != before:
        raise RuntimeError(f"unexpected serialisation of {path.name}; cannot patch it in place")

    values = payload.get("build_time_vars", payload)
    dropped = {
        key: values[key]
        for key, replacement in HOST_DISCOVERED_VARS.items()
        if key in values and values[key] != replacement
    }
    for key in dropped:
        values[key] = HOST_DISCOVERED_VARS[key]
    path.write_bytes(_dump_sysconfig_vars(payload))
    return {
        "mutation": "host-discovered values dropped, everything else byte-exact",
        "dropped_keys": sorted(dropped),
    }


def _dump_sysconfig_vars(payload: Any) -> bytes:
    # How CPython writes the file: two-space indent, insertion order, no trailing
    # newline. Asserted against the input rather than trusted.
    return json.dumps(payload, indent=2).encode()


def apply_consumer_overlay(install: Path, *, python_mm: str, host_triple: str) -> dict[str, Any]:
    """Overlay consumer metadata on an install prefix, in place."""
    layout = Layout(python_mm, host_triple)
    stdlib = install / layout.stdlib
    sysdata_candidates = sorted(stdlib.glob("_sysconfigdata_*.py"))
    sysvars_candidates = sorted(stdlib.glob("_sysconfig_vars_*.json"))
    if len(sysdata_candidates) != 1 or len(sysvars_candidates) != 1:
        raise RuntimeError("expected exactly one sysconfigdata and one sysconfig vars file")
    sysdata, sysvars = sysdata_candidates[0], sysvars_candidates[0]
    config_dir = install / layout.config_dir
    makefile = config_dir / "Makefile"
    python_config = config_dir / "python-config.py"
    build_details = stdlib / "build-details.json"
    missing = [
        path.name
        for path in (sysdata, sysvars, makefile, python_config, build_details)
        if not path.is_file()
    ]
    if missing:
        raise RuntimeError(f"upstream consumer metadata is incomplete: {missing}")

    host_discovered = drop_host_discovered_values(sysdata, sysvars, makefile)
    sysvars_before = sha256_path(sysvars)
    sysdata_row = _overlay_sysconfigdata(sysdata, layout)
    makefile_row = _patch_makefile(makefile, layout)
    python_config_row = _strip_shebang(python_config)
    pkgconfig_rows = _patch_pkgconfig(install / "lib/pkgconfig")
    build_details_row = _patch_build_details(build_details, layout)

    entry = install / f"bin/python{python_mm}-config"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(
        relative_shell_wrapper(python_mm, f'"$_bindir/../{layout.config_dir}/python-config.py"'),
        encoding="utf-8",
    )
    os.chmod(entry, 0o755)

    effective = _execute_sysconfigdata(sysdata)
    expected_paths = {
        "BINDIR": install / "bin",
        "LIBDIR": install / "lib",
        "LIBDEST": install / layout.stdlib,
        "INCLUDEPY": install / layout.include,
        "LIBPL": config_dir,
        "DESTSHARED": install / layout.stdlib / "lib-dynload",
    }
    for key, expected in expected_paths.items():
        if effective.get(key) != str(expected):
            raise RuntimeError(
                f"effective consumer path mismatch: {key}={effective.get(key)!r} "
                f"expected={str(expected)!r}"
            )
    if effective.get("ANDROID_METADATA_PROFILE") != PROFILE:
        raise RuntimeError("consumer overlay did not become effective")

    for path in [entry, *(install / "lib/pkgconfig" / row["path"] for row in pkgconfig_rows)]:
        text = path.read_text(encoding="utf-8")
        if any(root in text for root in PRODUCER_ROOTS):
            raise RuntimeError(f"consumer surface still carries a producer path: {path}")

    return {
        "schema_version": 1,
        "profile": PROFILE,
        "producer_provenance_preserved": True,
        "sysconfigdata": {"path": sysdata.relative_to(install).as_posix(), **sysdata_row},
        "host_discovered_values_dropped": host_discovered,
        "sysconfig_vars_json": {
            "path": sysvars.relative_to(install).as_posix(),
            "before_sha256": sysvars_before,
            "after_sha256": sha256_path(sysvars),
            "mutation": "preserved byte-exact",
        },
        "makefile": makefile_row,
        "python_config": python_config_row,
        "python_config_entry": {
            "path": entry.relative_to(install).as_posix(),
            "sha256": sha256_path(entry),
        },
        "pkgconfig": pkgconfig_rows,
        "build_details": build_details_row,
        "effective_consumer": {
            "paths": {
                key: "<install>/" + value.relative_to(install).as_posix()
                for key, value in expected_paths.items()
            },
            **{key: effective.get(key) for key in ("CC", "CXX", "AR", "CFLAGS", "LDFLAGS")},
        },
        "preserved_producer": {key: effective.get(key) for key in PRESERVED_PRODUCER_KEYS},
    }


def sysconfig_vars_json(install: Path, python_mm: str) -> dict[str, Any]:
    """The upstream ``_sysconfig_vars_*.json`` payload, byte-preserved."""
    stdlib = install / f"lib/python{python_mm}"
    candidates = sorted(stdlib.glob("_sysconfig_vars_*.json"))
    if len(candidates) != 1:
        raise RuntimeError("expected exactly one sysconfig vars file")
    raw = read_json(candidates[0])
    if isinstance(raw, dict) and "build_time_vars" in raw:
        raw = raw["build_time_vars"]
    if not isinstance(raw, dict):
        raise ValueError("sysconfig vars payload is not an object")
    return raw
