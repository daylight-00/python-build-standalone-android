"""Agreement between the tables this repository keeps and what they describe.

These ran as Python embedded in the CI workflow, where nothing linted them and
nobody could run them without pushing. They are the same checks.
"""

from __future__ import annotations

import unittest

from pythonbuild.targets import DEFAULT_BUILD_OPTION, get_build, load_builds
from pythonbuild.utils import read_json_object
from tests.support import ROOT


class BuildTableTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builds = load_builds()

    def test_the_table_declares_builds(self) -> None:
        self.assertTrue(self.builds)

    def test_every_build_agrees_with_its_input_lock(self) -> None:
        # Two places state the same floor. If they disagree, one was edited alone.
        for name, build in sorted(self.builds.items()):
            with self.subTest(build=name):
                lock = read_json_object(build.input_lock_path())
                self.assertEqual(lock["target"]["android_api"], build.android_api.level)
                self.assertEqual(lock["target"]["triple"], build.triple)
                self.assertEqual(lock["target"]["build_option"], build.build_option)

    def test_every_input_lock_exists(self) -> None:
        for name, build in sorted(self.builds.items()):
            with self.subTest(build=name):
                self.assertTrue(build.input_lock_path().is_file(), build.input_lock)

    def test_exactly_one_build_is_the_flagship(self) -> None:
        flagships = [b for b in self.builds.values() if b.build_option == DEFAULT_BUILD_OPTION]
        self.assertEqual(len(flagships), 1)

    def test_the_flagship_carries_no_marker_and_the_others_do(self) -> None:
        for build in self.builds.values():
            with self.subTest(build=build.name):
                if build.build_option == DEFAULT_BUILD_OPTION:
                    self.assertEqual(build.name, build.triple)
                    self.assertEqual(build.artifact_infix, build.triple)
                    self.assertEqual(build.metadata_build_options, "")
                else:
                    self.assertEqual(build.name, f"{build.triple}:{build.build_option}")
                    self.assertEqual(build.artifact_infix, f"{build.triple}-{build.build_option}")
                    self.assertEqual(build.metadata_build_options, build.build_option)

    def test_build_options_matches_the_artifact_name_segment(self) -> None:
        # Upstream's invariant for PYTHON.json's build_options field.
        for build in self.builds.values():
            with self.subTest(build=build.name):
                stem = build.artifact_stem("3.14.6", "20260729")
                expected = build.metadata_build_options
                self.assertEqual(
                    stem.removeprefix(f"cpython-3.14.6+20260729-{build.triple}"),
                    f"-{expected}" if expected else "",
                )

    def test_each_build_has_its_own_catalog(self) -> None:
        # uv's key cannot tell two Android builds apart, so they must not share one.
        catalogs = [build.uv_catalog for build in self.builds.values()]
        self.assertEqual(len(catalogs), len(set(catalogs)))

    def test_an_unknown_build_names_the_known_ones(self) -> None:
        with self.assertRaises(KeyError) as caught:
            get_build("nonexistent")
        self.assertIn("known builds", str(caught.exception))


class LicenseManifestTest(unittest.TestCase):
    def test_the_manifest_and_the_shipped_texts_agree(self) -> None:
        # The assembler enforces this too, but only after a full build.
        root = ROOT / "licenses"
        manifest = read_json_object(root / "components.json")
        declared = {c["file"] for c in manifest["components"] if c.get("file")}
        shipped = {p.name for p in root.glob("LICENSE.*.txt")}
        self.assertEqual(declared, shipped)

    def test_every_component_says_what_it_is_and_where_its_text_came_from(self) -> None:
        manifest = read_json_object(ROOT / "licenses" / "components.json")
        for component in manifest["components"]:
            with self.subTest(component=component.get("component")):
                self.assertTrue(component.get("component"))
                self.assertTrue(component.get("origin"))
                # Either an SPDX identifier, or a stated reason there is none:
                # sqlite and liblzma 5.4.6 are public domain, and Android's own
                # libraries are linked against rather than distributed.
                self.assertTrue(
                    component.get("spdx") or component.get("classification"),
                    "states neither an SPDX identifier nor why it has none",
                )
                # Present even when empty: three components carry their licence
                # inside the payload or are only linked against, and the empty
                # value is how the manifest says so.
                self.assertIn("file", component)

    def test_no_two_components_claim_the_same_text(self) -> None:
        manifest = read_json_object(ROOT / "licenses" / "components.json")
        files = [c["file"] for c in manifest["components"] if c.get("file")]
        self.assertEqual(len(files), len(set(files)))


if __name__ == "__main__":
    unittest.main()
