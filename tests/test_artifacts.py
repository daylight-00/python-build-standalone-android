"""Reading an artifact name back into what it describes.

Every name this project publishes has to parse, because the qualification gate
identifies a receipt by the artifact it ran against rather than by its filename.
A name that does not parse is a receipt that cannot be found.
"""

from __future__ import annotations

import unittest

from pythonbuild.artifacts import parse
from pythonbuild.targets import load_builds

TAG = "20260730"
VERSION = "3.14.6"


class ParseTest(unittest.TestCase):
    def test_every_name_this_project_publishes_parses(self) -> None:
        for build in load_builds().values():
            stem = build.artifact_stem(VERSION, TAG)
            for flavor, suffix in (
                ("full", "tar.zst"),
                ("install_only", "tar.gz"),
                ("install_only_stripped", "tar.gz"),
            ):
                name = f"{stem}-{flavor}.{suffix}"
                with self.subTest(name=name):
                    found = parse(name)
                    self.assertIsNotNone(found)
                    assert found is not None
                    self.assertEqual(found.version, VERSION)
                    self.assertEqual(found.tag, TAG)
                    self.assertEqual(found.flavor, flavor)
                    self.assertEqual(found.artifact_infix, build.artifact_infix)
                    self.assertEqual(found.build_option, build.build_option)

    def test_the_flagship_is_recognised_by_carrying_no_marker(self) -> None:
        found = parse(f"cpython-{VERSION}+{TAG}-aarch64-linux-android-full.tar.zst")
        assert found is not None
        self.assertEqual(found.build_option, "default")
        self.assertEqual(found.artifact_infix, "aarch64-linux-android")

    def test_a_build_option_is_read_off_the_name(self) -> None:
        found = parse(
            f"cpython-{VERSION}+{TAG}-aarch64-linux-android-upstream-install_only.tar.gz"
        )
        assert found is not None
        self.assertEqual(found.build_option, "upstream")
        self.assertEqual(found.artifact_infix, "aarch64-linux-android-upstream")

    def test_the_stripped_flavor_is_not_read_as_install_only(self) -> None:
        found = parse(
            f"cpython-{VERSION}+{TAG}-aarch64-linux-android-install_only_stripped.tar.gz"
        )
        assert found is not None
        self.assertEqual(found.flavor, "install_only_stripped")

    def test_a_prerelease_version_parses(self) -> None:
        # python.org publishes an Android package for prereleases too, so a name
        # carrying one has to be readable even before this project builds any.
        found = parse(
            f"cpython-3.15.0a1+{TAG}-aarch64-linux-android-extended-full.tar.zst"
        )
        assert found is not None
        self.assertEqual(found.version, "3.15.0a1")
        self.assertEqual(found.build_option, "extended")

    def test_two_series_of_one_build_option_are_told_apart(self) -> None:
        # The collision the version in the name exists to prevent.
        a = parse(f"cpython-3.14.6+{TAG}-aarch64-linux-android-full.tar.zst")
        b = parse(f"cpython-3.15.0+{TAG}-aarch64-linux-android-full.tar.zst")
        assert a is not None and b is not None
        self.assertEqual(a.artifact_infix, b.artifact_infix)
        self.assertNotEqual(a.version, b.version)

    def test_something_else_is_not_a_name(self) -> None:
        for name in (
            "cpython-full.tar.zst",
            "python-3.14.6-aarch64-linux-android.tar.gz",
            f"cpython-{VERSION}+{TAG}-aarch64-linux-android.tar.gz",
            f"cpython-{VERSION}+{TAG}-aarch64-linux-android-full.zip",
            "",
        ):
            with self.subTest(name=name):
                self.assertIsNone(parse(name))


if __name__ == "__main__":
    unittest.main()
