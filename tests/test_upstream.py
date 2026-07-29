"""Following python.org, and what follows from whichever version is pinned.

Discovery is one policy here where upstream has one per package, because this
project builds none of its dependencies by its own choice: the set is whatever
the pinned CPython names.
"""

from __future__ import annotations

import unittest

from pythonbuild.upstream import (
    android_package,
    components_differ,
    dependency_components,
    newest_patch,
    patch_versions,
    source_archive,
)

# python.org's autoindex, trimmed to the shape that matters.
LISTING = """
<a href="3.13.14/">3.13.14/</a>
<a href="3.14.0/">3.14.0/</a>
<a href="3.14.2/">3.14.2/</a>
<a href="3.14.10/">3.14.10/</a>
<a href="3.14.6/">3.14.6/</a>
<a href="3.15.0/">3.15.0/</a>
"""

ANDROID_PY = """
def unpack_deps(host, prefix_dir, cache_dir):
    os.chdir(prefix_dir)
    deps_url = "https://github.com/beeware/cpython-android-source-deps/releases/download"
    for name_ver in [
        "bzip2-1.0.8-3",
        "libffi-3.4.4-3",
        "openssl-3.5.7-0",
        "sqlite-3.50.4-0",
        "xz-5.4.6-1",
        "zstd-1.5.7-2"
    ]:
        filename = f"{name_ver}-{host}.tar.gz"
"""


class DiscoveryTest(unittest.TestCase):
    def test_patches_are_ordered_by_number_not_by_text(self) -> None:
        # "3.14.10" sorts before "3.14.6" as text and after it as a release.
        self.assertEqual(
            patch_versions(LISTING, "3.14"),
            ["3.14.0", "3.14.2", "3.14.6", "3.14.10"],
        )

    def test_the_newest_patch_is_the_highest_number(self) -> None:
        self.assertEqual(newest_patch(LISTING, "3.14"), "3.14.10")

    def test_a_series_is_not_confused_with_another(self) -> None:
        self.assertEqual(newest_patch(LISTING, "3.13"), "3.13.14")
        self.assertEqual(newest_patch(LISTING, "3.15"), "3.15.0")

    def test_an_unlisted_series_has_no_newest(self) -> None:
        self.assertIsNone(newest_patch(LISTING, "3.99"))

    def test_both_builds_read_from_one_version_directory(self) -> None:
        # One discovery covers both, which is why only CPython's version is watched.
        source = source_archive("3.14.7")
        package = android_package("3.14.7")
        self.assertEqual(source["filename"], "Python-3.14.7.tar.xz")
        self.assertEqual(
            package["filename"], "python-3.14.7-aarch64-linux-android.tar.gz"
        )
        self.assertTrue(source["url"].endswith("/3.14.7/Python-3.14.7.tar.xz"))
        self.assertIn("/3.14.7/", package["url"])


class DependencySetTest(unittest.TestCase):
    def test_the_set_is_read_out_of_the_pinned_source(self) -> None:
        found = dependency_components(ANDROID_PY)
        self.assertEqual(
            [(c.name, c.version, c.build) for c in found],
            [
                ("bzip2", "1.0.8", "3"),
                ("libffi", "3.4.4", "3"),
                ("openssl", "3.5.7", "0"),
                ("sqlite", "3.50.4", "0"),
                ("xz", "5.4.6", "1"),
                ("zstd", "1.5.7", "2"),
            ],
        )

    def test_a_source_without_unpack_deps_is_an_error(self) -> None:
        with self.assertRaises(RuntimeError):
            dependency_components("def something_else(): pass")

    def test_an_empty_dependency_list_is_an_error(self) -> None:
        with self.assertRaises(RuntimeError):
            dependency_components(
                "def unpack_deps():\n    for x in [\n    ]:\n        pass"
            )

    def test_an_agreeing_lock_reports_nothing(self) -> None:
        derived = dependency_components(ANDROID_PY)
        declared = [
            {"name": c.name, "version": c.version, "build": c.build} for c in derived
        ]
        self.assertEqual(components_differ(declared, derived), [])

    def test_a_version_this_project_bumped_on_its_own_is_reported(self) -> None:
        # The mistake the derivation exists to prevent: a newer OpenSSL than the
        # interpreter expects.
        derived = dependency_components(ANDROID_PY)
        declared = [
            {
                "name": c.name,
                "version": "9.9.9" if c.name == "openssl" else c.version,
                "build": c.build,
            }
            for c in derived
        ]
        problems = components_differ(declared, derived)
        self.assertEqual(len(problems), 1)
        self.assertIn("openssl", problems[0])

    def test_a_component_appearing_or_disappearing_is_reported(self) -> None:
        derived = dependency_components(ANDROID_PY)
        declared = [
            {"name": c.name, "version": c.version, "build": c.build}
            for c in derived
            if c.name != "zstd"
        ] + [{"name": "ncurses", "version": "6.5", "build": "0"}]
        problems = components_differ(declared, derived)
        self.assertIn("zstd: named by CPython, not pinned here", problems)
        self.assertIn("ncurses: pinned here, not named by CPython", problems)


if __name__ == "__main__":
    unittest.main()
