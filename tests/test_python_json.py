"""``PYTHON.json`` must satisfy the schema upstream's own reader enforces.

Transcribed from ``src/json.rs`` in astral-sh/python-build-standalone: the struct
is ``#[serde(deny_unknown_fields)]``, so an unknown key is an error, and every
field not wrapped in ``Option`` is required. Seven required fields were once
missing here, which made the file unreadable by upstream's tooling; this test is
what keeps them from going missing again.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pythonbuild.python_json import RUN_TESTS, build_python_json
from pythonbuild.runtime_metadata import Layout
from tests.support import make_build

# field -> required?  (False means Option<...> in src/json.rs)
MAIN = {
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
BUILD_INFO = {
    "core": True,
    "extensions": True,
    "inittab_object": True,
    "inittab_source": True,
    "inittab_cflags": True,
    "object_file_format": True,
}
CORE = {"objs": True, "links": True, "shared_lib": False, "static_lib": False}
EXTENSION = {
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
LINK = {
    "name": True,
    "path_static": False,
    "path_dynamic": False,
    "framework": False,
    "system": False,
}

PYTHON_MM = "3.14"
MAGIC = 3621


def make_prefix(root: Path) -> Path:
    """The smallest install prefix ``build_python_json`` will read.

    No ELF objects, so nothing here needs a toolchain: the extension and link
    tables come out empty, which is the case that used to hide a missing
    required field rather than expose it.
    """
    layout = Layout(PYTHON_MM, "aarch64-linux-android")
    install = root / "install"
    (install / layout.stdlib).mkdir(parents=True)
    (install / f"{layout.include}/internal").mkdir(parents=True)
    (install / f"{layout.include}/internal/pycore_magic_number.h").write_text(
        f"#define PYC_MAGIC_NUMBER {MAGIC}\n", encoding="utf-8"
    )
    return install


def check(obj: dict[str, Any], spec: dict[str, bool], where: str) -> list[str]:
    problems = [
        f"missing required {where}.{key}" for key, req in spec.items() if req and key not in obj
    ]
    problems += [f"unknown field {where}.{key}" for key in obj if key not in spec]
    return problems


class PythonJsonSchemaTest(unittest.TestCase):
    def build(self, build_option: str = "default") -> dict[str, Any]:
        with TemporaryDirectory() as tmp:
            install = make_prefix(Path(tmp))
            return build_python_json(
                install,
                make_build(build_option),
                python_version="3.14.6",
                python_mm=PYTHON_MM,
                config_vars_source={"abiflags": ""},
            )

    def assert_conforms(self, document: dict[str, Any]) -> None:
        problems = check(document, MAIN, "$")
        info = document.get("build_info", {})
        problems += check(info, BUILD_INFO, "$.build_info")
        problems += check(info.get("core", {}), CORE, "$.build_info.core")
        for link in info.get("core", {}).get("links", []):
            problems += check(link, LINK, "$.build_info.core.links[]")
        for name, entries in info.get("extensions", {}).items():
            for entry in entries:
                problems += check(entry, EXTENSION, f"$.build_info.extensions.{name}[]")
                for link in entry.get("links", []):
                    problems += check(link, LINK, f"$.build_info.extensions.{name}[].links[]")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_default_build_conforms(self) -> None:
        self.assert_conforms(self.build())

    def test_upstream_build_conforms(self) -> None:
        self.assert_conforms(self.build("upstream"))

    def test_run_tests_names_a_file_the_build_ships(self) -> None:
        from pythonbuild.python_json import RUN_TESTS_SOURCE

        self.assertEqual(self.build()["run_tests"], RUN_TESTS)
        self.assertTrue(RUN_TESTS_SOURCE.is_file(), f"{RUN_TESTS_SOURCE} does not exist")

    def test_version_is_the_string_eight(self) -> None:
        # Upstream emits the format version as a string and validates it as one.
        self.assertEqual(self.build()["version"], "8")

    def test_hex_version_is_an_integer(self) -> None:
        self.assertIsInstance(self.build()["python_implementation_hex_version"], int)

    def test_build_options_matches_the_artifact_name_segment(self) -> None:
        # Upstream's invariant: build_options is the segment between the triple
        # and the flavor. The flagship carries none, so the field is empty.
        self.assertEqual(self.build()["build_options"], "")
        self.assertEqual(self.build("upstream")["build_options"], "upstream")

    def test_bytecode_magic_number_is_reconstructed_from_the_header(self) -> None:
        token = MAGIC | (ord("\r") << 16) | (ord("\n") << 24)
        expected = token.to_bytes(4, "little").hex()
        self.assertEqual(self.build()["python_bytecode_magic_number"], expected)


if __name__ == "__main__":
    unittest.main()
