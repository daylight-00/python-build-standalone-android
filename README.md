# Python Standalone Builds for Android

Standalone, redistributable CPython for Android (Bionic), published in the shape of [astral-sh/python-build-standalone][pbs].

## Highlights

- **Upstream-compatible** — same archive roots, flavors, `PYTHON.json` metadata, artifact naming, and release model; existing consumers work unchanged.
- **Portable** — a prefix relocates to any path.
- **Reproducible** — archives are byte-identical across hosts.
- **Gated** — a release is device-qualified by a receipt, or says it is not and stays off the default catalog. An opt-in `edge` channel follows the newest of either; see [Channels](docs/running.md#channels).
- **Two builds** — a flagship compiled from source, and an `upstream` baseline for wider device coverage.

## Getting Started

With [uv](https://docs.astral.sh/uv/), where `<version>` is a CPython version the catalog lists:

```console
$ uv python install cpython-<version>-linux-aarch64-none \
    --python-downloads-json-url \
    https://raw.githubusercontent.com/daylight-00/python-build-standalone-android/latest-release/download-metadata.json
```

Or extract an archive from the [releases page][releases]:

```console
$ tar -xzf cpython-<version>+<tag>-aarch64-linux-android-install_only.tar.gz
$ ./python/bin/python3
```

## Builds

One triple, `aarch64-linux-android` (`arm64-v8a`), with a build option per distribution:

| Build Option | Produced From | Minimum Android | uv Catalog |
| --- | --- | --- | --- |
| *(none)* — flagship | CPython source | 14 (API 34) | `download-metadata.json` |
| `upstream` — baseline | the official Python.org Android package | 7.0 (API 24) | `download-metadata-upstream.json` |

- **Minimums** — neither is chosen here; each follows a stated rule, in [the API policy](docs/technotes.md#the-android-api-policy).
- **Choosing** — [Choosing a Build](docs/running.md#choosing-a-build) says which to want.

## Documentation

- [`docs/running.md`](docs/running.md) — obtaining and running distributions
- [`docs/building.md`](docs/building.md) — building, checking, and qualifying
- [`docs/quirks.md`](docs/quirks.md) — where Android differs from a POSIX host
- [`docs/technotes.md`](docs/technotes.md) — why the build is the way it is
- [`docs/distributions.md`](docs/distributions.md) — the archive contract and its metadata
- [`docs/status.md`](docs/status.md) — what is supported, and what deliberately is not

## License

- **This repository** — MIT, except two files that say where they came from.
- **Distributions** — carry third-party code under its own terms, such as CPython and OpenSSL; see [Licensing](docs/distributions.md#licensing).

[pbs]: https://github.com/astral-sh/python-build-standalone
[releases]: https://github.com/daylight-00/python-build-standalone-android/releases
