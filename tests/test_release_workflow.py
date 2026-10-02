"""The shell the release workflow runs to move the catalog branches.

It decides which of two branches an installer follows, so it is run here against
real temporary repositories rather than read and trusted. ``edge`` follows every
release; ``latest-release`` is what ``uv python install`` resolves and moves only
for a device-qualified one.
"""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from tests.support import ROOT

STEP = "Update the catalog branches"
CATALOGS = ("download-metadata.json", "download-metadata-upstream.json")
POINTER = "latest-release.json"


def release_step() -> str:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["publish"]["steps"]
    return str(next(step for step in steps if step.get("name") == STEP)["run"])


def git(cwd: Path, *args: str, env: dict[str, str]) -> str:
    done = subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


class CatalogBranchesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.origin = base / "origin.git"
        self.work = base / "work"
        # Nothing from the caller's git configuration may reach the run: signing
        # and hooks would make the result depend on whose machine it is.
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(base),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        git(base, "init", "-q", "--bare", "-b", "main", str(self.origin), env=self.env)
        git(base, "init", "-q", "-b", "main", str(self.work), env=self.env)
        git(self.work, "remote", "add", "origin", str(self.origin), env=self.env)
        (self.work / "README.md").write_text("the release's own tree\n")
        git(self.work, "add", ".", env=self.env)
        git(
            self.work,
            "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", "release tree",
            env=self.env,
        )  # fmt: skip
        git(self.work, "push", "-q", "origin", "main", env=self.env)

    def publish(self, tag: str, *, qualified: bool) -> None:
        dist = self.work / "dist"
        dist.mkdir(exist_ok=True)
        for name in (*CATALOGS, POINTER):
            (dist / name).write_text(f'{{"tag": "{tag}", "file": "{name}"}}\n')
        subprocess.run(
            ["bash", "-e", "-c", release_step()],
            cwd=self.work,
            env={
                **self.env,
                "TAG": tag,
                "QUALIFIED": "true" if qualified else "false",
            },
            check=True,
            capture_output=True,
            text=True,
        )

    def branches(self) -> set[str]:
        out = git(self.origin, "branch", "--format=%(refname:short)", env=self.env)
        return set(out.split()) - {"main"}

    def files(self, branch: str) -> set[str]:
        out = git(self.origin, "ls-tree", "--name-only", branch, env=self.env)
        return set(out.split())

    def tag_on(self, branch: str) -> str:
        out = git(self.origin, "show", f"{branch}:{POINTER}", env=self.env)
        return str(json.loads(out)["tag"])

    def test_a_release_without_a_receipt_reaches_only_edge(self) -> None:
        self.publish("20261002", qualified=False)
        self.assertEqual(self.branches(), {"edge"})
        self.assertEqual(self.tag_on("edge"), "20261002")

    def test_a_qualified_release_reaches_both(self) -> None:
        self.publish("20260729", qualified=True)
        self.assertEqual(self.branches(), {"edge", "latest-release"})
        self.assertEqual(self.tag_on("edge"), "20260729")
        self.assertEqual(self.tag_on("latest-release"), "20260729")

    def test_edge_moves_on_but_latest_release_stays_at_the_last_qualified(
        self,
    ) -> None:
        # The case the second channel exists for.
        self.publish("20260729", qualified=True)
        self.publish("20261002", qualified=False)
        self.assertEqual(self.tag_on("edge"), "20261002")
        self.assertEqual(self.tag_on("latest-release"), "20260729")

    def test_a_later_qualified_release_catches_latest_release_up(self) -> None:
        self.publish("20260729", qualified=True)
        self.publish("20261002", qualified=False)
        self.publish("20261015", qualified=True)
        self.assertEqual(self.tag_on("edge"), "20261015")
        self.assertEqual(self.tag_on("latest-release"), "20261015")

    def test_a_branch_carries_the_catalogs_and_nothing_else(self) -> None:
        self.publish("20260729", qualified=True)
        self.publish("20261002", qualified=False)
        for branch in ("edge", "latest-release"):
            with self.subTest(branch=branch):
                self.assertEqual(self.files(branch), {*CATALOGS, POINTER})

    def test_the_release_tree_is_not_left_in_a_catalog_branch(self) -> None:
        # Switching from one branch to the other must not carry files over.
        self.publish("20260729", qualified=True)
        self.assertNotIn("README.md", self.files("edge"))
        self.assertNotIn("README.md", self.files("latest-release"))

    def test_a_rejected_push_fails_the_step(self) -> None:
        # The remote answers and then refuses; swallowing that would report a
        # release as published to a channel it never reached.
        hook = self.origin / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish("20260729", qualified=True)

    def test_an_unreachable_remote_is_not_a_missing_branch(self) -> None:
        # `ls-remote` failing is not the same as the branch being absent: reading
        # it that way would start a second, unrelated history under the name.
        self.publish("20260729", qualified=True)
        git(self.work, "remote", "set-url", "origin", "/nonexistent", env=self.env)
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            self.publish("20261002", qualified=False)
        self.assertIn("cannot reach origin", caught.exception.stderr)


if __name__ == "__main__":
    unittest.main()
