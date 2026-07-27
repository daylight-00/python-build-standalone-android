"""Install the pip wheel the upstream package already carries.

pip comes from the distribution's own ``ensurepip/_bundled`` wheel, so no
network acquisition happens and the installed pip is exactly the one upstream
shipped. The ``bin/pip*`` entry points are shell wrappers rather than generated
console scripts, because a console script bakes in the absolute interpreter path
it was created with and the prefix has to stay relocatable.
"""

from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from .runtime_metadata import relative_shell_wrapper
from .utils import sha256_path


def _safe_wheel_path(name: str) -> str:
    if not name or name.startswith("/") or "\\" in name or "\x00" in name:
        raise ValueError(f"unsafe wheel member: {name!r}")
    parts = PurePosixPath(name).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe wheel member: {name!r}")
    return PurePosixPath(*parts).as_posix()


def install_bundled_pip(install: Path, python_mm: str) -> dict[str, Any]:
    bundled = install / f"lib/python{python_mm}/ensurepip/_bundled"
    wheels = sorted(bundled.glob("pip-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(
            f"expected exactly one bundled pip wheel, found {[path.name for path in wheels]}"
        )
    wheel = wheels[0]
    match = re.fullmatch(r"pip-([0-9][A-Za-z0-9_.-]*)-py3-none-any\.whl", wheel.name)
    if not match:
        raise RuntimeError(f"unexpected bundled pip wheel name: {wheel.name}")

    site = install / f"lib/python{python_mm}/site-packages"
    site.mkdir(parents=True, exist_ok=True)
    extracted: list[dict[str, Any]] = []
    seen: set[str] = set()
    with zipfile.ZipFile(wheel) as archive:
        for info in sorted(archive.infolist(), key=lambda row: row.filename):
            raw = info.filename.rstrip("/")
            if not raw:
                continue
            name = _safe_wheel_path(raw)
            if name in seen:
                raise RuntimeError(f"duplicate pip wheel member: {name}")
            seen.add(name)
            target = site / name
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            data = archive.read(info)
            target.write_bytes(data)
            os.chmod(target, ((info.external_attr >> 16) & 0o7777) or 0o644)
            extracted.append(
                {
                    "path": target.relative_to(install).as_posix(),
                    "sha256": sha256_path(target),
                    "size_bytes": len(data),
                }
            )

    (install / "bin").mkdir(parents=True, exist_ok=True)
    wrapper_text = relative_shell_wrapper(python_mm, "-m pip")
    wrappers: list[dict[str, Any]] = []
    for name in ("pip", "pip3", f"pip{python_mm}"):
        path = install / "bin" / name
        path.write_text(wrapper_text, encoding="utf-8")
        os.chmod(path, 0o755)
        wrappers.append(
            {
                "path": path.relative_to(install).as_posix(),
                "sha256": sha256_path(path),
                "launcher": f"relative bin/python{python_mm} -m pip",
            }
        )

    return {
        "schema_version": 1,
        "source": "the distribution's own ensurepip wheel",
        "wheel": {
            "path": wheel.relative_to(install).as_posix(),
            "filename": wheel.name,
            "version": match.group(1),
            "sha256": sha256_path(wheel),
            "size_bytes": wheel.stat().st_size,
        },
        "extracted_file_count": len(extracted),
        "extracted_files": extracted,
        "wrappers": wrappers,
        "network_acquisition": False,
    }
