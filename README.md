# Python Standalone Builds for Android

This project produces standalone, redistributable builds of CPython for
Android (Bionic), published in the shape of
[astral-sh/python-build-standalone][pbs].

Distributions follow the python-build-standalone archive contract — the same
archive roots, flavor relationships, `PYTHON.json` metadata, artifact naming,
and release model — so existing consumers work unchanged.

## Quick start

Install a distribution with `uv`:

```console
$ uv python install cpython-3.14.6-linux-aarch64-none \
    --python-downloads-json-url \
    https://raw.githubusercontent.com/daylight-00/python-build-standalone-android/latest-release/download-metadata-upstream.json
```

Or download an archive from the [releases page][releases] and extract it:

```console
$ tar -xzf cpython-3.14.6+<tag>-aarch64-linux-android-upstream-install_only.tar.gz
$ ./python/bin/python3
```

## Builds

One triple, `aarch64-linux-android`, with a build option per distribution:

| Build option | Produced from | Minimum Android | Status |
| --- | --- | --- | --- |
| `upstream` | the official Python.org Android package | 7.0 (API 24) | published |
| *(none)* | CPython source | 14 (API 34) | published |
| `extended` | CPython source, plus readline, Tk, uuid, Berkeley DB | 14 (API 34) | planned |

An earlier release, `20260728`, carries the `upstream` build alone and was cut
before the archives were byte-reproducible across machines. It is superseded and
left in place: a published name has to keep serving the bytes it was published
with, since the catalog pins them by hash.

The unmarked build is the flagship. Neither API level is chosen here — each
follows a stated rule, described in the design document.

## Documentation

- [`docs/design.md`](docs/design.md) — what this repository builds and why
- [`docs/running.md`](docs/running.md) — obtaining and running distributions
- [`docs/support.md`](docs/support.md) — the supported runtime scope, and what
  is explicitly not supported

Design questions are settled in [cpython-android-cli][research] and land here
only as build recipes.

## Licensing

This repository's own source is MIT. The distributions it publishes contain
third-party code under its own terms — CPython under the Python license, OpenSSL
under Apache-2.0, and others. See
[`docs/design.md`](docs/design.md#licensing) for the full picture.

[pbs]: https://github.com/astral-sh/python-build-standalone
[releases]: https://github.com/daylight-00/python-build-standalone-android/releases
[research]: https://github.com/daylight-00/cpython-android-cli
