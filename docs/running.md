# Running Distributions

## Obtaining a Distribution

Releases are published on the [releases page][releases]. Each build carries three archive flavors:

| Flavor | Format | Contents |
| --- | --- | --- |
| `install_only_stripped` | `.tar.gz` | the runtime prefix, native debug symbols removed |
| `install_only` | `.tar.gz` | the runtime prefix as assembled |
| `full` | `.tar.zst` | the runtime prefix plus `PYTHON.json` and the build records |

- **Most consumers** — `install_only_stripped`; take `full` for the metadata, the retained upstream input, or the mutation and audit records.
- **Machines** — the `latest-release` branch publishes the newest release at `https://raw.githubusercontent.com/daylight-00/python-build-standalone-android/latest-release/latest-release.json`.
- **Validation** — `./validate-distribution.py <archive>` holds an archive to the distribution contract, with no build needed; see [Checking What You Built](building.md#checking-what-you-built).

## Choosing a Build

Both are `arm64-v8a`:

| Build Option | Minimum Android | Notes |
| --- | --- | --- |
| `upstream` | 7.0 (API 24) | widest device coverage; the permanent baseline |
| *(none)* | 14 (API 34) | the flagship: faster, and HTTPS works out of the box |

- **Minimums** — [the API policy](technotes.md#the-android-api-policy) explains why each is what it is.
- **Speed** — [why a source build is worth having](technotes.md#why-a-source-build-is-worth-having) gives the measured difference.

## With uv

Each build option publishes its own catalog, because uv's key format cannot tell two Android builds apart:

```console
$ uv python install cpython-<version>-linux-aarch64-none \
    --python-downloads-json-url \
    https://raw.githubusercontent.com/daylight-00/python-build-standalone-android/latest-release/download-metadata.json
```

- **Catalogs** — `download-metadata.json` is the flagship; `download-metadata-upstream.json` is the baseline.
- **Resolves to** — the newest device-qualified release.
- **Prereleases** — one published without a receipt is left out, so `uv python install` never lands on bytes no device ran; see [Releasing Without One](technotes.md#releasing-without-one).
- **Other ways to set it** — `UV_PYTHON_DOWNLOADS_JSON_URL`, or the `python-downloads-json-url` key in `uv.toml`.
- **Identity** — the catalog says `linux` because uv has no Android key; the installed interpreter reports its real identity:

```console
$ python -c "import sysconfig; print(sysconfig.get_config_var('SOABI'))"
cpython-314-aarch64-linux-android
$ python -c "import sysconfig; print(sysconfig.get_platform())"
android-<api>-arm64_v8a
```

## Directly

```console
$ tar -xzf cpython-<version>+<tag>-aarch64-linux-android-upstream-install_only.tar.gz
$ ./python/bin/python3 -V
```

- **Relocatable** — move the prefix anywhere and it keeps working.
- **No loader setup** — every shared object carries a relative `RUNPATH`, so no `LD_LIBRARY_PATH` is needed and nothing re-executes itself at startup.

## Writable State

The prefix is immutable. Point the interpreter at writable locations you own; without a writable `TMPDIR` it fails closed rather than falling back to a host-private directory:

```sh
export TMPDIR="$STATE/tmp"
export XDG_CACHE_HOME="$STATE/cache"
export PYTHONPYCACHEPREFIX="$STATE/pycache"
export PYTHONNOUSERSITE=1
```

## CA Certificates and Time Zones

Bionic has no `/etc/ssl/certs` and no `/usr/share/zoneinfo`, so a stock CPython finds an empty trust store and no time zone database. [Android Quirks](quirks.md#runtime-data-ca-certificates-and-time-zones) says why, and what each build does.

- **Flagship trust store** — compiled in from Termux's, so HTTPS works out of the box under Termux; override with `SSL_CERT_FILE` and `SSL_CERT_DIR`.
- **Flagship time zones** — the path stays at CPython's default: install `tzdata`, set `PYTHONTZPATH`, or use the data product.
- **`upstream`** — cannot compile anything in, since the official package is consumed as-is; install the data product from the `android-data-*` release track and point the interpreter at it:

```sh
export SSL_CERT_FILE="$DATA/current/ssl/cert.pem"
export PYTHONTZPATH="$DATA/current/zoneinfo"
```

[releases]: https://github.com/daylight-00/python-build-standalone-android/releases
