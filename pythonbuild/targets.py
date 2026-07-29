"""The target table from ci-targets.yaml.

A ``Build`` is one releasable thing: a triple plus a build option. The triple
says what the device must provide; the build option says how the distribution
was produced. ``default`` is the flagship and carries no marker in artifact
names, following upstream's treatment of its blessed build.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
TARGETS_FILE = ROOT / "ci-targets.yaml"

DEFAULT_BUILD_OPTION = "default"


@dataclass(frozen=True)
class AndroidApi:
    """The minimum API level, and the rule that produced it.

    Neither number is chosen by this project, which is why neither appears in a
    triple: ``upstream`` inherits whatever floor the official package was built
    with, and ``default`` follows CPython's own feature detection.
    """

    level: int
    policy: str
    rationale: str


@dataclass(frozen=True)
class Build:
    triple: str
    build_option: str
    arch: str
    abi: str
    libc: str
    ndk: str
    producer: str
    input_lock: str
    android_api: AndroidApi
    runtime_data: dict[str, Any]
    uv_catalog: str
    python_versions: tuple[str, ...]

    @property
    def name(self) -> str:
        """How this build is referred to on a command line."""
        if self.build_option == DEFAULT_BUILD_OPTION:
            return self.triple
        return f"{self.triple}:{self.build_option}"

    @property
    def artifact_infix(self) -> str:
        """The triple plus the build option, as it appears in artifact names."""
        if self.build_option == DEFAULT_BUILD_OPTION:
            return self.triple
        return f"{self.triple}-{self.build_option}"

    @property
    def metadata_build_options(self) -> str:
        """The value recorded in PYTHON.json's ``build_options``."""
        return "" if self.build_option == DEFAULT_BUILD_OPTION else self.build_option

    @property
    def clang(self) -> str:
        return f"{self.arch}-linux-android{self.android_api.level}-clang"

    @property
    def from_upstream_prebuilt(self) -> bool:
        return self.producer == "upstream-prebuilt"

    def artifact_stem(self, python_version: str, tag: str) -> str:
        return f"cpython-{python_version}+{tag}-{self.artifact_infix}"

    def input_lock_path(self, root: Path = ROOT) -> Path:
        return root / self.input_lock


def _build(
    triple: str, triple_entry: dict[str, Any], option: str, entry: dict[str, Any]
) -> Build:
    api = entry["android_api"]
    return Build(
        triple=triple,
        build_option=option,
        arch=triple_entry["arch"],
        abi=triple_entry["abi"],
        libc=triple_entry["libc"],
        ndk=str(triple_entry["ndk"]),
        producer=entry["producer"],
        input_lock=entry["input_lock"],
        android_api=AndroidApi(
            level=int(api["level"]),
            policy=api["policy"],
            rationale=" ".join(api["rationale"].split()),
        ),
        runtime_data=dict(entry["runtime_data"]),
        uv_catalog=entry["uv_catalog"],
        python_versions=tuple(triple_entry["python_versions"]),
    )


def load_builds(path: Path = TARGETS_FILE) -> dict[str, Build]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    builds: dict[str, Build] = {}
    for platform_entries in document.values():
        for triple, triple_entry in platform_entries.items():
            for option, entry in triple_entry["build_options"].items():
                build = _build(triple, triple_entry, option, entry)
                builds[build.name] = build
    return builds


def get_build(name: str, path: Path = TARGETS_FILE) -> Build:
    """Resolve ``triple`` or ``triple:option`` to a build."""
    builds = load_builds(path)
    if name in builds:
        return builds[name]
    known = ", ".join(sorted(builds))
    raise KeyError(f"unknown build {name!r}; known builds: {known}")
