"""Apply Android-native CA and timezone source integrations."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

ANDROID_ZONEINFO_SOURCE = ROOT / "patches/cpython/zoneinfo/_android.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_path(path: Path) -> str:
    parts = path.parts
    if "Lib" in parts:
        return Path(*parts[parts.index("Lib") :]).as_posix()
    return path.name


def _replace_once(path: Path, old: str, new: str, reason: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Android native-data patch for {path} matched {count} times, expected 1; "
            f"the pinned CPython source changed: {reason}"
        )
    before = _sha256(path)
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return {
        "path": _record_path(path),
        "before_sha256": before,
        "after_sha256": _sha256(path),
        "reason": reason,
    }


def _replace_block(
    path: Path,
    start_marker: str,
    end_marker: str,
    replacement: str,
    reason: str,
) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if text.count(start_marker) != 1 or text.count(end_marker) != 1:
        raise RuntimeError(
            f"Android native-data block markers changed in {path}: {reason}"
        )
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    before = _sha256(path)
    path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
    return {
        "path": _record_path(path),
        "before_sha256": before,
        "after_sha256": _sha256(path),
        "reason": reason,
    }


def apply_cpython_android_native_data(source: Path) -> list[dict[str, Any]]:
    """Add packed-tzdata fallback while retaining CPython's ZoneInfo object."""
    zoneinfo = source / "Lib/zoneinfo"
    destination = zoneinfo / "_android.py"
    if destination.exists():
        raise RuntimeError(f"unexpected existing Android zoneinfo loader: {destination}")
    shutil.copyfile(ANDROID_ZONEINFO_SOURCE, destination)
    records: list[dict[str, Any]] = [
        {
            "path": destination.relative_to(source).as_posix(),
            "before_sha256": None,
            "after_sha256": _sha256(destination),
            "reason": (
                "read one TZif member from Android's packed tzdata in place, without "
                "extracting a zoneinfo tree or creating a persistent cache"
            ),
        }
    ]

    common = zoneinfo / "_common.py"
    new_loader = '''def load_tzdata(key):
    from importlib import resources

    from . import _android, _tzpath

    if _tzpath._ANDROID_NATIVE_FALLBACK:
        try:
            return _android.load_tzdata(key)
        except FileNotFoundError:
            pass

    if _tzpath._EXPLICIT_TZPATH:
        raise ZoneInfoNotFoundError(f"No time zone found with key {key}")

    components = key.split("/")
    package_name = ".".join(["tzdata.zoneinfo"] + components[:-1])
    resource_name = components[-1]

    try:
        path = resources.files(package_name).joinpath(resource_name)
        # gh-85702: Prevent PermissionError on Windows
        if path.is_dir():
            raise IsADirectoryError
        return path.open("rb")
    except (ImportError, FileNotFoundError, UnicodeEncodeError, IsADirectoryError):
        raise ZoneInfoNotFoundError(f"No time zone found with key {key}")


'''
    records.append(
        _replace_block(
            common,
            "def load_tzdata(key):\n",
            "def load_data(fobj):\n",
            new_loader,
            "fall back to Android packed tzdata only after ordinary TZPATH lookup",
        )
    )

    tzpath = zoneinfo / "_tzpath.py"
    new_reset = '''def _reset_tzpath(to=None, stacklevel=4):
    global TZPATH, _ANDROID_NATIVE_FALLBACK, _EXPLICIT_TZPATH

    explicit = to is not None or "PYTHONTZPATH" in os.environ
    tzpaths = to
    if tzpaths is not None:
        if isinstance(tzpaths, (str, bytes)):
            raise TypeError(
                f"tzpaths must be a list or tuple, "
                + f"not {type(tzpaths)}: {tzpaths!r}"
            )

        tzpaths = [os.fspath(p) for p in tzpaths]
        if not all(isinstance(p, str) for p in tzpaths):
            raise TypeError(
                "All elements of a tzpath sequence must be strings or "
                "os.PathLike objects which convert to strings."
            )

        if not all(map(os.path.isabs, tzpaths)):
            raise ValueError(_get_invalid_paths_message(tzpaths))
        base_tzpath = tzpaths
    else:
        env_var = os.environ.get("PYTHONTZPATH", None)
        if env_var is None:
            env_var = sysconfig.get_config_var("TZPATH")
        base_tzpath = _parse_python_tzpath(env_var, stacklevel)

    TZPATH = tuple(base_tzpath)
    _EXPLICIT_TZPATH = explicit
    _ANDROID_NATIVE_FALLBACK = not explicit


'''
    records.append(
        _replace_block(
            tzpath,
            "def _reset_tzpath(to=None, stacklevel=4):\n",
            "def reset_tzpath(to=None):\n",
            new_reset,
            "explicit PYTHONTZPATH/reset_tzpath remains authoritative and fail-closed",
        )
    )

    new_available = '''def available_timezones():
    """Returns a set containing all available time zones."""
    from importlib import resources

    valid_zones = set()
    if _ANDROID_NATIVE_FALLBACK:
        from . import _android

        try:
            valid_zones.update(_android.available_timezones())
        except FileNotFoundError:
            pass

    if not _EXPLICIT_TZPATH:
        try:
            zones_file = resources.files("tzdata").joinpath("zones")
            with zones_file.open("r", encoding="utf-8") as f:
                for zone in f:
                    zone = zone.strip()
                    if zone:
                        valid_zones.add(zone)
        except (ImportError, FileNotFoundError):
            pass

    def valid_key(fpath):
        try:
            with open(fpath, "rb") as f:
                return f.read(4) == b"TZif"
        except Exception:  # pragma: nocover
            return False

    for tz_root in TZPATH:
        if not os.path.exists(tz_root):
            continue

        for root, dirnames, files in os.walk(tz_root):
            if root == tz_root:
                if "right" in dirnames:
                    dirnames.remove("right")
                if "posix" in dirnames:
                    dirnames.remove("posix")

            for file in files:
                fpath = os.path.join(root, file)
                key = os.path.relpath(fpath, start=tz_root)
                if os.sep != "/":  # pragma: nocover
                    key = key.replace(os.sep, "/")
                if not key or key in valid_zones:
                    continue
                if valid_key(fpath):
                    valid_zones.add(key)

    valid_zones.discard("posixrules")
    return valid_zones


'''
    records.append(
        _replace_block(
            tzpath,
            "def available_timezones():\n",
            "class InvalidTZPathWarning(RuntimeWarning):\n",
            new_available,
            "enumerate Android's packed index without extraction when fallback is active",
        )
    )

    records.append(
        _replace_once(
            tzpath,
            "TZPATH = ()\n_reset_tzpath(stacklevel=5)\n",
            "TZPATH = ()\n_ANDROID_NATIVE_FALLBACK = False\n"
            "_EXPLICIT_TZPATH = False\n_reset_tzpath(stacklevel=5)\n",
            "initialize Android fallback state before module-level path resolution",
        )
    )
    return records
