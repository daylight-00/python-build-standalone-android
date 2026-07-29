"""``PYTHON.json`` must satisfy the schema upstream's own reader enforces.

The schema itself lives in ``pythonbuild.conformance``, because
``validate-distribution.py`` holds finished archives to the same one. Seven
required fields were once missing here, which made the file unreadable by
upstream's tooling; these tests are what keep them from going missing again.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pythonbuild.conformance import check_python_json
from pythonbuild.python_json import RUN_TESTS, RUN_TESTS_SOURCE, build_python_json
from pythonbuild.runtime_metadata import Layout
from tests.support import make_build

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

    def test_default_build_conforms(self) -> None:
        self.assertEqual(check_python_json(self.build()), [])

    def test_upstream_build_conforms(self) -> None:
        self.assertEqual(check_python_json(self.build("upstream")), [])

    def test_a_missing_required_field_is_caught(self) -> None:
        # Without this the schema check could pass by never looking.
        document = self.build()
        del document["run_tests"]
        del document["build_info"]["core"]["objs"]
        self.assertEqual(
            sorted(check_python_json(document)),
            ["missing required $.build_info.core.objs", "missing required $.run_tests"],
        )

    def test_an_unknown_field_is_caught(self) -> None:
        document = self.build()
        document["invented"] = 1
        self.assertIn("unknown field $.invented", check_python_json(document))

    def test_run_tests_names_a_file_the_build_ships(self) -> None:
        self.assertEqual(self.build()["run_tests"], RUN_TESTS)
        self.assertTrue(
            RUN_TESTS_SOURCE.is_file(), f"{RUN_TESTS_SOURCE} does not exist"
        )

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
