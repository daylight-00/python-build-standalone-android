# Running Distributions

## Obtaining a distribution

Releases are published on the [releases page][releases]. Each build carries
three archive flavors:

| Flavor | Format | Contents |
| --- | --- | --- |
| `install_only_stripped` | `.tar.gz` | the runtime prefix, native debug symbols removed |
| `install_only` | `.tar.gz` | the runtime prefix as assembled |
| `full` | `.tar.zst` | the runtime prefix plus `PYTHON.json` and the build records |

Most consumers want `install_only_stripped`. Reach for `full` when you need the
metadata, the retained upstream input, or the mutation and audit records.

Machines can resolve the newest release from the `latest-release` branch:

```
https://raw.githubusercontent.com/daylight-00/python-build-standalone-android/latest-release/latest-release.json
```

## Choosing a build

| Build option | Minimum Android | Notes |
| --- | --- | --- |
| `upstream` | 7.0 (API 24) | widest device coverage; the permanent baseline |
| *(none)* | 14 (API 34) | the flagship: faster, and HTTPS works out of the box |

Both are `arm64-v8a`. See [`design.md`](design.md#the-android-api-policy) for
why each minimum is what it is, and
[why a source build is worth having](design.md#why-a-source-build-is-worth-having)
for the measured difference.

## With uv

Each build option publishes its own catalog, because uv's key format cannot tell
two Android builds apart:

```console
$ uv python install cpython-3.14.6-linux-aarch64-none \
    --python-downloads-json-url \
    https://raw.githubusercontent.com/daylight-00/python-build-standalone-android/latest-release/download-metadata-upstream.json
```

```
download-metadata.json            the flagship build
download-metadata-upstream.json   the baseline build
```

The same URL works through `UV_PYTHON_DOWNLOADS_JSON_URL` or the
`python-downloads-json-url` key in `uv.toml`.

The catalog says `linux` because uv has no Android key. The installed
interpreter reports its real identity:

```console
$ python -c "import sysconfig; print(sysconfig.get_config_var('SOABI'))"
cpython-314-aarch64-linux-android
$ python -c "import sysconfig; print(sysconfig.get_platform())"
android-24-arm64_v8a
```

## Directly

```console
$ tar -xzf cpython-3.14.6+<tag>-aarch64-linux-android-upstream-install_only.tar.gz
$ ./python/bin/python3 -V
```

The prefix relocates: move it anywhere and it keeps working. Every shared object
carries a relative `RUNPATH`, so no `LD_LIBRARY_PATH` is needed and nothing
re-executes itself at startup.

## Writable state

The prefix is immutable. Point the interpreter at writable locations you own:

```sh
export TMPDIR="$STATE/tmp"
export XDG_CACHE_HOME="$STATE/cache"
export PYTHONPYCACHEPREFIX="$STATE/pycache"
export PYTHONNOUSERSITE=1
```

Without a writable `TMPDIR` the interpreter fails closed rather than falling back
to a host-private directory.

## CA certificates and time zones

Bionic has no `/etc/ssl/certs` and no `/usr/share/zoneinfo`, so a stock CPython
finds an empty trust store and no time zone database.

The flagship build compiles in Termux's trust store, so HTTPS works out of the
box under Termux, overridable with `SSL_CERT_FILE` and `SSL_CERT_DIR`.

It leaves the time zone path at CPython's default, as upstream does, because
Termux ships no zoneinfo tree. `zoneinfo` falls back to the `tzdata` package the
same way it does on a Linux host without system zoneinfo, so install `tzdata`,
set `PYTHONTZPATH`, or use the data product.

The `upstream` build cannot compile anything in — the official package is
consumed as-is. Install the data product from the `android-data-*` release track
and point the interpreter at it:

```sh
export SSL_CERT_FILE="$DATA/current/ssl/cert.pem"
export PYTHONTZPATH="$DATA/current/zoneinfo"
```

[releases]: https://github.com/daylight-00/python-build-standalone-android/releases
