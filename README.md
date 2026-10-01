# Python Standalone Builds for Android

Standalone, redistributable builds of CPython for Android (Bionic), published
in the shape of [astral-sh/python-build-standalone][pbs]: the same archive
roots, flavor relationships, `PYTHON.json` metadata, artifact naming, and
release model, so existing consumers work unchanged.

## Quick start

Install a distribution with `uv`:

```console
$ uv python install cpython-3.14.6-linux-aarch64-none \
    --python-downloads-json-url \
    https://raw.githubusercontent.com/daylight-00/python-build-standalone-android/latest-release/download-metadata.json
```

That is the flagship build, which needs Android 14. For wider device coverage
substitute `download-metadata-upstream.json`, the baseline, which needs Android 7
and is slower — see [Choosing a build](docs/running.md#choosing-a-build).

Or download an archive from the [releases page][releases] and extract it:

```console
$ tar -xzf cpython-3.14.6+<tag>-aarch64-linux-android-install_only.tar.gz
$ ./python/bin/python3
```

## Builds

One triple, `aarch64-linux-android`, with a build option per distribution:

| Build option | Produced from | Minimum Android | Status |
| --- | --- | --- | --- |
| `upstream` | the official Python.org Android package | 7.0 (API 24) | published |
| *(none)* | CPython source | 14 (API 34) | published |
| `extended` | CPython source, plus readline, Tk, uuid, Berkeley DB | 14 (API 34) | planned |

The unmarked build is the flagship. Neither API level is chosen here; each
follows a stated rule, described in
[the API policy](docs/technotes.md#the-android-api-policy).

An earlier release, `20260728`, carries the `upstream` build alone. It is
superseded and left in place; see
[Targets and build options](docs/technotes.md#targets-and-build-options).

## Documentation

- [`docs/running.md`](docs/running.md) — obtaining and running distributions
- [`docs/building.md`](docs/building.md) — building, checking, and qualifying one
  yourself
- [`docs/quirks.md`](docs/quirks.md) — where Android differs from a POSIX host
- [`docs/technotes.md`](docs/technotes.md) — why the build is the way it is
- [`docs/distributions.md`](docs/distributions.md) — the archive contract and its
  metadata
- [`docs/status.md`](docs/status.md) — what is supported, and what deliberately
  is not

Design questions are settled in [cpython-android-cli][research] and land here
only as build recipes.

## Licensing

This repository's own source is MIT, except for two files that say where they
came from. The distributions it publishes contain third-party code under its own
terms — CPython under the Python license, OpenSSL under Apache-2.0, and others.
[`docs/distributions.md`](docs/distributions.md#licensing) has both.

[pbs]: https://github.com/astral-sh/python-build-standalone
[releases]: https://github.com/daylight-00/python-build-standalone-android/releases
[research]: https://github.com/daylight-00/cpython-android-cli
