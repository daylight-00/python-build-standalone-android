# Contributing

## Scope

- **Belongs here** — build recipes and release machinery.
- **Does not** — design questions. Anything that needs an experiment goes to [cpython-android-cli][research] and arrives here as a recipe once settled.
- **Fixed** — distributions come from python.org's own sources or its official Android package, and the only target is `aarch64-linux-android`. See [`docs/technotes.md`](docs/technotes.md).

## Getting Set Up

- Toolchain, builds, and device qualification: [`docs/building.md`](docs/building.md).

```console
$ ./check.py            # lint, formatting, types, tests
$ ./build.py --target aarch64-linux-android --tag $(date -u +%Y%m%d)
```

## Invariants

The full list is in [`CLAUDE.md`](CLAUDE.md); each one has cost a bug. The ones that catch a first patch:

- **Reproducible** — two builds of the same input give byte-identical archives, across machines and umasks.
- **Host-path free** — nothing inside an archive names a directory of the machine that built it.
- **Derived, not transcribed** — a value computed from a pinned input cannot drift from it. Adding a table that is edited by hand needs a good argument.
- **Guards over conventions** — if something must not reach a distribution, make the build fail on it.
- **Claims sized to evidence** — "runs at API 24" and "was run on a device at API 24" are different statements; the docs say which one they mean.

## Following Upstream

- **Divergence** — from astral's contract, or a patched upstream recipe: record what and why next to it. An unrecorded divergence is a defect.
- **Tooling** — `ruff.toml` tracks upstream's settings; where it does not, the file says why.
- **Type checker** — upstream moved from mypy to `ty`; `mypy.ini` stays until this project follows.

## Commits

- **Subject** — `type(scope): summary`, Angular convention, imperative.
- **Body** — short bullets, one line each, no hard wrapping; GitHub renders a hard-wrapped body as broken lines.
- **Content** — what changed and why it was worth changing. For a fix that came from a diagnosis, lead with the diagnosis.

## Pull Requests

- **Description** — bullets: why, what changed, how it was verified.
- **Release-affecting changes** — say whether archive bytes change.

## Reporting Problems

- **Where** — the [issue tracker][issues].
- **Include** — build option, release tag, archive flavor, Android version, and runtime context.
- **Security** — follow [`SECURITY.md`](SECURITY.md).

[research]: https://github.com/daylight-00/cpython-android-cli
[issues]: https://github.com/daylight-00/python-build-standalone-android/issues
