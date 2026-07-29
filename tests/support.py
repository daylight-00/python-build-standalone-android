"""Shared fixtures.

Builds are constructed here rather than read from ``ci-targets.yaml`` wherever a
test is about behaviour rather than about the table, so editing the table cannot
quietly change what a test asserts.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from pythonbuild.targets import AndroidApi, Build

ROOT = Path(__file__).resolve().parent.parent


def make_build(
    build_option: str = "default",
    *,
    api_level: int = 34,
    runtime_data: dict[str, Any] | None = None,
) -> Build:
    return Build(
        triple="aarch64-linux-android",
        build_option=build_option,
        arch="aarch64",
        abi="arm64-v8a",
        libc="bionic",
        ndk="27.3.13750724",
        producer="cpython-source" if build_option == "default" else "upstream-prebuilt",
        input_lock="config/source/cpython-3.14.6.lock.json",
        android_api=AndroidApi(
            level=api_level, policy="a-stated-rule", rationale="because"
        ),
        runtime_data={"mechanism": "build-default"}
        if runtime_data is None
        else runtime_data,
        uv_catalog="download-metadata.json",
        python_versions=("3.14",),
    )


def load_script(name: str) -> ModuleType:
    """Import one of the hyphenated entry-point scripts.

    ``release-notes.py`` is not a legal module name, so it cannot be imported the
    ordinary way. Upstream has the same shape of script and does not test them;
    here the floor callout is worth holding onto, so it is loaded by path.
    """
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), ROOT / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
