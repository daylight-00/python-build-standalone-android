"""Upstream's ``PYTHON.json`` schema, as its own reader enforces it.

Transcribed from ``src/json.rs`` in astral-sh/python-build-standalone. The struct
is ``#[serde(deny_unknown_fields)]``, so an unknown key is an error, and every
field not wrapped in ``Option`` is required.

This lives here rather than in the tests because two callers need it: the tests,
which hold the generator to it, and ``validate-distribution.py``, which holds a
finished archive to it. A schema that only the tests knew about could pass while
the thing actually published did not.
"""

from __future__ import annotations

from typing import Any

# field -> required?  False means Option<...> upstream.
MAIN: dict[str, bool] = {
    "apple_sdk_canonical_name": False,
    "apple_sdk_deployment_target": False,
    "apple_sdk_platform": False,
    "apple_sdk_version": False,
    "build_info": True,
    "build_options": True,
    "crt_features": True,
    "libpython_link_mode": True,
    "licenses": False,
    "license_path": False,
    "optimizations": True,
    "python_abi_tag": False,
    "python_bytecode_magic_number": True,
    "python_config_vars": True,
    "python_exe": True,
    "python_extension_module_loading": True,
    "python_implementation_cache_tag": True,
    "python_implementation_hex_version": True,
    "python_implementation_name": True,
    "python_implementation_version": True,
    "python_major_minor_version": True,
    "python_paths_abstract": True,
    "python_paths": True,
    "python_platform_tag": True,
    "python_stdlib_platform_config": False,
    "python_stdlib_test_packages": True,
    "python_suffixes": True,
    "python_symbol_visibility": True,
    "python_tag": True,
    "python_version": True,
    "target_triple": True,
    "run_tests": True,
    "tcl_library_path": False,
    "tcl_library_paths": False,
    "version": True,
}
BUILD_INFO: dict[str, bool] = {
    "core": True,
    "extensions": True,
    "inittab_object": True,
    "inittab_source": True,
    "inittab_cflags": True,
    "object_file_format": True,
}
CORE: dict[str, bool] = {
    "objs": True,
    "links": True,
    "shared_lib": False,
    "static_lib": False,
}
EXTENSION: dict[str, bool] = {
    "in_core": True,
    "init_fn": True,
    "licenses": False,
    "license_paths": False,
    "license_public_domain": False,
    "links": True,
    "objs": True,
    "required": True,
    "static_lib": False,
    "shared_lib": False,
    "variant": True,
}
LINK: dict[str, bool] = {
    "name": True,
    "path_static": False,
    "path_dynamic": False,
    "framework": False,
    "system": False,
}

FORMAT_VERSION = "8"


def check_fields(obj: dict[str, Any], spec: dict[str, bool], where: str) -> list[str]:
    problems = [
        f"missing required {where}.{key}"
        for key, required in spec.items()
        if required and key not in obj
    ]
    problems += [f"unknown field {where}.{key}" for key in obj if key not in spec]
    return problems


def check_python_json(document: dict[str, Any]) -> list[str]:
    """Every way upstream's reader would reject this document."""
    problems = check_fields(document, MAIN, "$")
    info = document.get("build_info")
    if not isinstance(info, dict):
        return problems
    problems += check_fields(info, BUILD_INFO, "$.build_info")

    core = info.get("core")
    if isinstance(core, dict):
        problems += check_fields(core, CORE, "$.build_info.core")
        for link in core.get("links") or []:
            problems += check_fields(link, LINK, "$.build_info.core.links[]")

    # Collapsed across extensions. A field missing from one entry is almost
    # always missing from all seventy, and seventy identical lines bury whatever
    # else is wrong.
    extensions = info.get("extensions") or {}
    per_field: dict[str, int] = {}
    for entries in extensions.values():
        for entry in entries:
            for problem in check_fields(entry, EXTENSION, "$.build_info.extensions[*]"):
                per_field[problem] = per_field.get(problem, 0) + 1
            for link in entry.get("links") or []:
                for problem in check_fields(
                    link, LINK, "$.build_info.extensions[*].links[]"
                ):
                    per_field[problem] = per_field.get(problem, 0) + 1
    total = sum(len(entries) for entries in extensions.values())
    problems += [
        f"{problem} ({count} of {total} entries)"
        for problem, count in sorted(per_field.items())
    ]

    # The parts upstream validates beyond the shape.
    if document.get("version") != FORMAT_VERSION:
        problems.append(
            f"$.version is {document.get('version')!r}, not {FORMAT_VERSION!r}"
        )
    if not isinstance(document.get("python_implementation_hex_version"), int):
        problems.append("$.python_implementation_hex_version is not an integer")
    return problems


__all__ = [
    "BUILD_INFO",
    "CORE",
    "EXTENSION",
    "FORMAT_VERSION",
    "LINK",
    "MAIN",
    "check_fields",
    "check_python_json",
]
