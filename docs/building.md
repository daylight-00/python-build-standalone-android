# Building

Build a distribution yourself. Everything here runs on `linux-x86_64`, the only release host; see [Toolchain](technotes.md#toolchain).

## What You Need

- **[uv](https://docs.astral.sh/uv/)** — manages the Python and the pinned dependencies; nothing else is installed globally.
- **Android NDK** — at the revision `config/toolchain.lock.json` pins; the build prints the `sdkmanager` line to install it if it cannot find one.
- **Resources** — roughly 4 GB of disk and an hour or two of CPU for a source build.
- **`upstream`** — repackages an archive, so it needs neither the NDK's compiler nor that much time; it still uses the NDK's `readelf`, `strip`, and the pinned `patchelf`.

## Building

```console
$ ./build.py --target aarch64-linux-android --tag $(date -u +%Y%m%d)
$ ./build.py --target aarch64-linux-android:upstream --tag $(date -u +%Y%m%d)
```

- **Name** — `triple` or `triple:build-option`; the triple alone selects the flagship. `ci-targets.yaml` lists what exists, and `./ci-matrix.py` prints it.
- **Output** — three archives and a build receipt in `dist/`.
- **Receipt** — records the inputs, the toolchain, every mutation, and each archive's SHA-256; `check-qualification.py`, `generate-catalog.py`, and `release-notes.py` read it.
- **Intermediates** — in `build/`, emptied before each build so a result cannot depend on what was built before; the clone and download caches persist.

Upstream's `build.py` takes `--target-triple`, `--options` and `--python`. Here:

- **`--target`** — carries the build option, as `triple:build-option`, because `ci-targets.yaml` enumerates builds that way.
- **No `--python`** — the version is not an input; it comes from the input lock, which names it in its path and again in its contents.

## Checking What You Built

```console
$ ./validate-distribution.py dist/*.tar.zst dist/*.tar.gz
$ just build-reproducible aarch64-linux-android <tag>
```

- **Contract** — `validate-distribution.py` holds a finished archive to the `PYTHON.json` schema upstream's own reader enforces, the extension modules CPython says it built, the license texts against the manifest, and the member paths.
- **Where it runs** — CI runs it on every build; it works on a downloaded release archive too.
- **Reproducibility** — a property of the build, so proving it takes two; `build-reproducible` builds twice and compares.
- **Umask** — CI also runs the second build under a different umask; see [Reproducibility](distributions.md#reproducibility).

## Qualifying on a Device

CI has no Android runner, so the check that matters most happens out of band.

- **Procedure** — copy `qualify.py` and the archives to a device and run it there with any Python 3; the exact commands for each build are in [`qualification/README.md`](../qualification/README.md).
- **Receipt** — binds its findings to the exact archive bytes; commit it under `qualification/<tag>/`.
- **Gate** — the release workflow refuses to publish unless a receipt covers every artifact by SHA-256, or the release is made [without one](technotes.md#releasing-without-one).
- **Coverage** — `check-qualification.py` answers whether a committed receipt covers what you just built.

## Checks

```console
$ ./check.py          # lint, formatting, types, tests
$ ./check.py --fix    # apply what ruff can apply
```

- **Configuration** — `ruff.toml` and `mypy.ini` decide what is checked, so no command line has to be kept in step with them.

## Following a New CPython Patch

```console
$ ./update-pins.py            # report
$ ./update-pins.py --write    # move both builds to the newest patch
```

- **Inputs** — one python.org version directory serves both builds, and the dependency set is re-read from the new source, not carried over; see [Following Upstream](technotes.md#following-upstream).
- **Automation** — a weekly workflow does this and opens a pull request.

## The Flagship's API Floor

`ci-targets.yaml` declares it, and the rule it declares is measured rather than argued:

```console
$ ./resolve-api-level.py            # report what the rule selects
$ ./resolve-api-level.py --check    # fail if the declaration has gone stale
```

- **Method** — configures CPython at candidate levels and compares the generated `pyconfig.h`; needs the NDK and a build interpreter, and takes tens of minutes.
- **Not part of a build** — see [the API policy](technotes.md#the-android-api-policy).
- **CI** — runs it when the CPython or NDK pin changes, and weekly.

## Releasing

- **Manual and gated** — `workflow_dispatch` with an explicit tag and commit, the `release` environment, and `dry-run` defaulting to true; see [Release Model](technotes.md#release-model).
- **Exception** — [releasing unattended](technotes.md#releasing-unattended), off until opted into.
