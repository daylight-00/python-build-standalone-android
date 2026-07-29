# Contributing

## What belongs here

Build recipes and release machinery. This repository does not settle design
questions — if answering one needs an experiment, it belongs in
[cpython-android-cli][research] and arrives here as a recipe once it is settled.

Two constraints are fixed and are not up for change in a patch: distributions
are produced from python.org's own sources or its official Android package, and
the only target is `aarch64-linux-android`. What follows from them is described
in [`docs/technotes.md`](docs/technotes.md).

## Getting set up

[`docs/building.md`](docs/building.md) covers the toolchain, a build, and the
device qualification step. In short:

```console
$ ./check.py            # lint, formatting, types, tests
$ ./build.py --target aarch64-linux-android --tag $(date -u +%Y%m%d)
```

## What a change has to keep true

The invariants are listed in [`CLAUDE.md`](CLAUDE.md) and each one has cost this
project a bug at least once. The ones that most often catch a first patch:

- **Archives are byte-reproducible on any host.** Two builds of the same input
  agree, across machines and umasks. Anything written without an explicit mode,
  any timestamp a compiler stamps in, and any unpinned tool breaks this.
- **Nothing inside an archive names a directory of the machine that built it.**
- **Derive rather than transcribe.** A value computed from a pinned input cannot
  drift out of step with it. The expected extension modules, the build matrix,
  and `SOURCE_DATE_EPOCH` are all derived for this reason; adding a table that
  has to be edited by hand needs a good argument.
- **Guards over conventions.** If something must not reach a distribution, make
  the build fail on it rather than writing it down.
- **Claims are sized to evidence.** "Runs at API 24" and "was run on a device at
  API 24" are different statements, and the documentation says which it means.

## Following upstream

Where this project diverges from astral's contract or patches an upstream
recipe, the divergence and its justification are written down next to it. A
divergence with no recorded reason is treated as a defect. The same applies to
the tooling: `ruff.toml` and `mypy.ini` track upstream's settings, and where
they do not, the file says why.

## Commits

Angular convention: `type(scope): summary` in the imperative. Write body
paragraphs as single lines with blank lines between them — GitHub renders a
hard-wrapped body as broken lines. Say what changed and why it was worth
changing; if a fix came from a diagnosis, the diagnosis is the interesting part.

## Reporting problems

Use the [issue tracker][issues]. A useful report states the build option, the
release tag, the archive flavor, the Android version, and the runtime context.
Security issues follow [`SECURITY.md`](SECURITY.md).

[research]: https://github.com/daylight-00/cpython-android-cli
[issues]: https://github.com/daylight-00/python-build-standalone-android/issues
