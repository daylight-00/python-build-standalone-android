# Working in this repository

Standalone CPython distributions for Android, published in the shape of
[astral-sh/python-build-standalone][pbs]. This repository holds build recipes
and release machinery. Design questions get settled in
[cpython-android-cli][research] and arrive here as recipes — if a question needs
an experiment to answer, it does not belong in this repository.

## Where the facts are

Nothing here restates what a file already says, so that this document does not
go stale. Read the file.

| Question | File |
| --- | --- |
| What builds exist, their API levels, what each compiles in | `ci-targets.yaml` |
| Exact inputs and their checksums | `config/**/*.lock.json` |
| Why anything is the way it is | `docs/technotes.md` |
| What an archive contains and promises | `docs/distributions.md` |
| What is supported, and what deliberately is not | `docs/status.md` |
| What each component's license is and where its text came from | `licenses/components.json` |

When code and one of these disagree, the file is not automatically right —
but one of them is wrong, and both should not be left standing.

## Invariants

These hold for every build. Breaking one is a bug even when tests pass.

- **Archives are byte-reproducible on any host.** Two builds of the same input
  agree, across machines and umasks. Anything a build writes without an explicit
  mode, any timestamp a compiler stamps in, and any tool whose version is not
  pinned will break this.
- **Nothing inside an archive names a directory of the machine that built it.**
  Not a build tree, not a workspace, not the toolchain's location, not the build
  user's home. Upstream's own paths, where a repackaged build recorded them, stay:
  there they are the producer's provenance and every consumer of that package sees
  the same ones. Text is rewritten to a placeholder; a compiled object needs
  `-ffile-prefix-map`; a string a build recorded about itself can only be fixed by
  building it differently.
- **Every tree a build writes into starts empty.** Workspaces may persist for
  clones and downloads; a tree left behind makes the result depend on what was
  built before. This one has bitten three times.
- **A qualification receipt is evidence only for the bytes it names.** It binds
  artifacts by SHA-256. Never widen a receipt to cover a build it did not run.
- **Metadata is never invented, and is omitted only where the format allows.**
  A field describing something this project did not produce is left out when it
  is optional and made empty when it is required — an empty list of object files
  is a fact about the distribution, a plausible-looking path is not. Omitting a
  required field is not honesty, it is a file upstream's own reader rejects.
- **A build is held only to what it declares.** `ci-targets.yaml` says what a
  build compiles in; the gate requires exactly that and no more.

## How to work here

Real defects here have come from running the invariants, not from reading the
code. When something looks wrong, reach for a diff before a hypothesis: build
twice and compare, extract both archives and compare member by member, read the
ELF note rather than trusting the build that claims to have set it.

- **Follow upstream unless there is a reason not to, and record the reason.**
  When this project diverges from astral's contract or patches an upstream
  recipe, the divergence and its justification are written down next to it.
- **Derive constants from pinned inputs.** A value computed from a lock file
  cannot drift out of step with one; a value typed into the source can. The
  same reasoning covers anything upstream already decided: the expected
  extension modules come out of CPython's own configure record rather than a
  table here, as the dependency set and the `upstream` API floor do.
- **Guards over conventions.** If something must not reach a distribution, make
  the build fail on it. Several of these exist and each has caught something.
- **Claims are sized to evidence.** "Runs on a given API level" and "was run on
  a device at that level" are different statements, and a build floor is the
  first, not the second. The documentation says which one it means.

## Commands

```console
$ ./build.py --target <triple[:option]> --tag <YYYYMMDD>   # build one distribution
$ ./check-qualification.py --target <…> --tag <…>          # does a receipt cover it
$ ./validate-distribution.py <archive>…                    # hold finished bytes to the contract
$ ./generate-catalog.py --target <…> --tag <…>             # uv download metadata
$ python3 qualify.py <archive> --expected-api <n>          # on a device, stdlib only
$ ./check.py [--fix]                                       # lint, types, tests
$ ./ci-matrix.py                                           # the CI build matrix
```

`just` recipes wrap these; `just --list` shows them. Releases are manual,
gated, and default to a dry run — see `.github/workflows/release.yml`.

Building from source needs an Android NDK at the pinned revision; the build
prints how to install it if it cannot find one.

## Commits

Angular convention: `type(scope): summary` in the imperative. Write body
paragraphs as single lines with blank lines between them — GitHub renders a
hard-wrapped body as broken lines. Say what changed and why it was worth
changing; if a fix came from a diagnosis, the diagnosis is the interesting part.

[pbs]: https://github.com/astral-sh/python-build-standalone
[research]: https://github.com/daylight-00/cpython-android-cli
