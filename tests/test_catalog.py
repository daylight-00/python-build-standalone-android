"""The uv download-metadata catalog."""

from __future__ import annotations

import unittest

from pythonbuild.catalog import (
    CATALOG_FLAVOR,
    asset_url,
    build_catalog,
    catalog_entry,
    catalog_key,
    latest_release,
    merge_catalog,
)
from tests.support import make_build

REPOSITORY = "daylight-00/python-build-standalone-android"


class CatalogTest(unittest.TestCase):
    def test_key_claims_linux_with_no_libc(self) -> None:
        # uv's key format has no Android component, and on the device uv reports
        # linux with no libc. The key has to match what uv detects, not what the
        # distribution is.
        self.assertEqual(
            catalog_key("cpython", "3.14.6", make_build()),
            "cpython-3.14.6-linux-aarch64-none",
        )

    def test_both_build_options_collide_on_one_key(self) -> None:
        # This collision is the whole reason each build gets its own catalog file.
        self.assertEqual(
            catalog_key("cpython", "3.14.6", make_build()),
            catalog_key("cpython", "3.14.6", make_build("upstream")),
        )

    def test_asset_url_quotes_the_filename(self) -> None:
        self.assertEqual(
            asset_url(REPOSITORY, "20260729", "a b+c.tar.gz"),
            f"https://github.com/{REPOSITORY}/releases/download/20260729/a%20b%2Bc.tar.gz",
        )

    def test_entry_carries_the_version_split_into_integers(self) -> None:
        _, entry = catalog_entry(
            make_build(),
            python_version="3.14.6",
            tag="20260729",
            filename="x.tar.gz",
            sha256="abc",
            repository=REPOSITORY,
        )
        self.assertEqual((entry["major"], entry["minor"], entry["patch"]), (3, 14, 6))
        self.assertEqual(entry["build"], "20260729")
        self.assertEqual(entry["sha256"], "abc")
        self.assertEqual(entry["arch"], {"family": "aarch64", "variant": None})

    def test_merge_keeps_older_versions_and_lets_the_newest_win(self) -> None:
        old = build_catalog(
            make_build(),
            python_version="3.13.1",
            tag="20260101",
            filename="old.tar.gz",
            sha256="old",
            repository=REPOSITORY,
        )
        same_version_newer = build_catalog(
            make_build(),
            python_version="3.13.1",
            tag="20260729",
            filename="new.tar.gz",
            sha256="new",
            repository=REPOSITORY,
        )
        other_version = build_catalog(
            make_build(),
            python_version="3.14.6",
            tag="20260729",
            filename="other.tar.gz",
            sha256="other",
            repository=REPOSITORY,
        )
        merged = merge_catalog(merge_catalog(old, same_version_newer), other_version)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged["cpython-3.13.1-linux-aarch64-none"]["sha256"], "new")
        self.assertEqual(sorted(merged), list(merged), "merged catalogs are sorted")

    def test_the_catalogued_flavor_is_the_stripped_one(self) -> None:
        # Most consumers want the smallest archive; uv installs this one.
        self.assertEqual(CATALOG_FLAVOR, "install_only_stripped")

    def test_latest_release_matches_upstreams_pointer_schema(self) -> None:
        # Byte-for-byte the shape upstream's Justfile writes, so a machine that
        # already reads theirs reads this one.
        self.assertEqual(
            latest_release(REPOSITORY, "20260729"),
            {
                "version": 1,
                "tag": "20260729",
                "release_url": f"https://github.com/{REPOSITORY}/releases/tag/20260729",
                "asset_url_prefix": f"https://github.com/{REPOSITORY}/releases/download/20260729",
            },
        )


if __name__ == "__main__":
    unittest.main()
