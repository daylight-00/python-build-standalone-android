"""Read IANA TZif members directly from Android's packed tzdata file."""

from __future__ import annotations

import io
import pathlib
import struct

_TZDATA_PATH = pathlib.Path("/apex/com.android.tzdata/etc/tz/tzdata")
_HEADER_SIZE = 24
_INDEX_ENTRY_SIZE = 52


def _validate_key(key: str) -> None:
    if not isinstance(key, str):
        raise TypeError("key must be str")
    parts = pathlib.PurePosixPath(key).parts
    if not key or key.startswith("/") or "." in parts or ".." in parts:
        raise ValueError(f"invalid time zone key: {key!r}")


def _index() -> tuple[dict[str, tuple[int, int]], str]:
    with _TZDATA_PATH.open("rb") as packed:
        header = packed.read(_HEADER_SIZE)
        if len(header) != _HEADER_SIZE or not header.startswith(b"tzdata"):
            raise ValueError(f"not Android packed tzdata: {_TZDATA_PATH}")
        version = header[6:11].decode("ascii", errors="strict").rstrip("\x00")
        index_offset, data_offset, final_offset = struct.unpack(">III", header[12:24])
        if not (_HEADER_SIZE <= index_offset <= data_offset <= final_offset):
            raise ValueError("invalid Android tzdata offsets")
        index_size = data_offset - index_offset
        if index_size % _INDEX_ENTRY_SIZE:
            raise ValueError("invalid Android tzdata index size")

        packed.seek(index_offset)
        entries: dict[str, tuple[int, int]] = {}
        for _ in range(index_size // _INDEX_ENTRY_SIZE):
            record = packed.read(_INDEX_ENTRY_SIZE)
            if len(record) != _INDEX_ENTRY_SIZE:
                raise ValueError("truncated Android tzdata index")
            key_raw, relative, length, _unused = struct.unpack(">40sIII", record)
            key = key_raw.split(b"\x00", 1)[0].decode("ascii", errors="strict")
            absolute = data_offset + relative
            if (
                not key
                or key in entries
                or absolute < data_offset
                or absolute + length > final_offset
            ):
                raise ValueError("invalid Android tzdata member")
            entries[key] = (absolute, length)
        return entries, version


def load_tzdata(key: str):
    """Return one packed TZif member as a seekable binary file object."""
    _validate_key(key)
    entries, _version = _index()
    try:
        offset, length = entries[key]
    except KeyError as error:
        raise FileNotFoundError(key) from error

    with _TZDATA_PATH.open("rb") as packed:
        packed.seek(offset)
        data = packed.read(length)
    if len(data) != length or not data.startswith(b"TZif"):
        raise ValueError(f"invalid Android TZif member: {key}")
    return io.BytesIO(data)


def available_timezones() -> set[str]:
    """Return the exact set of keys in Android's packed tzdata index."""
    entries, _version = _index()
    return set(entries)
