# Building

Building a distribution yourself. Everything here runs on `linux-x86_64`; see
[Toolchain](technotes.md#toolchain) for why that is the only release host.

## What you need

- [uv](https://docs.astral.sh/uv/), which manages the Python and the pinned
  dependencies. Nothing else is installed globally.
- An Android NDK at the pinned revision. `config/toolchain.lock.json` states
  which, and the build prints the `sdkmanager` line to install it if it cannot
  find one.
- Roughly 4 GB of disk for a source build, and an hour or two of CPU.

The `upstream` build needs neither the NDK's compiler nor that much time — it
repackages an archive rather than compiling one — but it does use the NDK's
`readelf`, `strip`, and the pinned `patchelf`.

## Building

```console
$ ./build.py --target aarch64-linux-android --tag $(date -u +%Y%m%d)
$ ./build.py --target aarch64-linux-android:upstream --tag $(date -u +%Y%m%d)
```

A build is named `triple` or `triple:build-option`; naming the triple alone
selects the flagship. `ci-targets.yaml` is the list of what exists, and
`./ci-matrix.py` prints it.

Three archives and a build receipt land in `dist/`. The receipt records the
inputs, the toolchain, every mutation, and the SHA-256 of each archive; it is
what `check-qualification.py`, `generate-catalog.py`, and `release-notes.py`
read.

Intermediates live in `build/`. The tree for a given build is emptied before it
is written into — a prefix left over from an earlier run would make the result
depend on what was built before — but the clone and download caches persist.

## Checking what you built

```console
$ ./validate-distribution.py dist/*.tar.zst dist/*.tar.gz
```

This holds a finished archive to the distribution contract: the `PYTHON.json`
schema upstream's own reader enforces, the extension modules CPython says it
built, the licence texts, and the member paths. CI runs it on every build, and
it works just as well on an archive downloaded from a release.

Reproducibility is a property of the build, so proving it takes two:

```console
$ just build-reproducible aarch64-linux-android 20260729
```

CI additionally runs the second build under a different umask, because repeating
a build under identical conditions proves much less than it appears to.

## Qualifying on a device

CI has no Android runner, so the check that matters most happens out of band.
Copy `qualify.py` and an archive to a device and run them there with any
Python 3:

```console
$ python3 qualify.py cpython-3.14.6+20260729-…-install_only_stripped.tar.gz \
    --expected-api 34 -o aarch64-linux-android.json
```

The receipt it writes binds its findings to the exact archive bytes. Commit it
under `qualification/<tag>/<build>.json`; the release workflow refuses to
publish unless one covers every artifact by SHA-256. `check-qualification.py`
answers whether a committed receipt covers what you just built.

## Checks

```console
$ ./check.py          # lint, formatting, types, tests
$ ./check.py --fix    # apply what ruff can apply
```

`ruff.toml` and `mypy.ini` decide what is checked, so no command line has to be
kept in step with them.

## Releasing

Releases are manual and gated: `workflow_dispatch` with an explicit tag and
commit, a protected environment, and `dry-run` defaulting to true. See
[Release model](technotes.md#release-model).
