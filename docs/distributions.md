# Distribution Archives

What this project publishes, and the contract each archive keeps. Named for
the [upstream document][pbs] of the same purpose, because a consumer that
already understands those archives should need to learn nothing new here.

## Archive contract

Assembly order is fixed and each flavor is derived from the verified one above
it, so `install_only` can always be reconstructed from `full` and compared
member for member:

```
verified input -> full -> install_only -> install_only_stripped
```

```
python/
├── PYTHON.json     Astral metadata, format 8
├── build/
└── install/        a normal relocatable POSIX prefix
```

`full` is `.tar.zst`; the install-only flavors are `.tar.gz`. All members share
one `python/` root with deterministic ordering, normalized ownership and
timestamps, no absolute or traversal paths, no hard links, and only relative
non-escaping symlinks.

### Reproducibility

Two builds of the same input produce byte-identical archives, on any host. Each
of the following would quietly break that, and is handled explicitly:

- **The caller's umask.** Every `mkdir` and every JSON record written without an
  explicit mode takes it, and those modes land in the archive. The build sets a
  fixed umask rather than trusting the one it inherited.
- **The compressor.** Two versions of zstd compress identical input to different
  bytes, and the `zstd` on a machine is whatever that machine has. Compression
  goes through the `zstandard` library, pinned by `uv.lock`, single-threaded
  because multi-threaded output depends on how the work was divided.
- **Host paths.** Nothing inside an archive names a directory of the machine that
  built it: not the build tree, not the toolchain, not the build user's home.
  Generated text is rewritten to a placeholder, compiled objects are given
  `-ffile-prefix-map` for both the build tree and the NDK, since an object's line
  table names the sysroot headers it read, and the tools are named without their
  directory so that the command lines a build records about itself — OpenSSL's
  compiler banner, configure's `CONFIG_ARGS` — carry no path at all. That last one
  cannot be fixed afterwards: a string inside a shared object is not rewritable.
- **The `pkg-config` on the machine.** Two implementations are in circulation and
  they disagree on which `.pc` file a dependency resolves to and on how the flags
  it yields are spelled. configure records what it was handed, so the
  disagreement reaches the Makefile, `sysconfigdata`, and the compile line of any
  module found this way. `pkgconf` is pinned by `uv.lock` and put on `PATH` under
  the name the builds call, and `PKG_CONFIG_PATH` is dropped from the
  environment.
- **Build timestamps.** A compiler stamps `__DATE__` and `__TIME__` into the
  interpreter, and OpenSSL stamps a build banner. `SOURCE_DATE_EPOCH` is set to
  the newest mtime inside the pinned CPython source archive — derived from an
  input rather than invented, so there is no constant to keep in step.
- **State from earlier runs.** Every tree a build writes into starts empty. A
  workspace kept between runs is worth having for clones and downloads, but a
  prefix left behind makes the result depend on what was built before.

CI builds twice and compares, and the second build deliberately runs under a
different umask — repeating a build under identical conditions proves much less
than it appears to.

For `upstream`, `python/build/` cannot contain a producer object graph, because
the project did not produce the objects. It carries the upstream archive
identity and retained input, extracted upstream metadata and licenses, the
launcher build record, mutation manifests, and audit records. Nothing recorded
there names a host path, both so the archive stays reproducible and so the build
machine's layout is not published.

## PYTHON.json conformance

The file follows upstream's format 8, including the parts that are easy to get
wrong: `version` is the string `"8"`, `python_implementation_hex_version` is an
integer, `python_abi_tag` is `sys.abiflags` (empty for a release build), and
`python_platform_tag` is `sysconfig.get_platform()` — `android-24-arm64_v8a`,
which is not the wheel platform tag `android_24_arm64_v8a`.

Values that upstream reads out of a running interpreter are taken from PEP 739
`build-details.json`, which the interpreter itself wrote, rather than guessed.
`python_bytecode_magic_number` is reconstructed from the internal
`pycore_magic_number.h` the distribution ships, because CPython 3.14 moved the
magic number into a C constant and the distribution contains no `.pyc` to read
it from.

Upstream's reader is the check that decides whether this file conforms.
`src/json.rs` is `#[serde(deny_unknown_fields)]` and leaves most fields outside
`Option`, so an unknown key and a missing required one are both errors. Seven
required fields were once left out here on the grounds that this project
produces no object graph, which made the file unreadable by upstream's own
tooling. Empty is how the format says *none*: no object files ship, so `objs` is
`[]`; no relinkable inittab exists, so `inittab_object` is `""`. Fields that
upstream marks optional and that would describe something absent are still
omitted, and `tests/test_python_json.py` holds the file to the schema.

Deliberate deviations:

- **`build_options` carries provenance** (`upstream`) rather than an
  optimization profile. Upstream's invariant is that this field matches the
  segment between the triple and the flavor in the artifact name, and it does.
- **`crt_features`** uses `bionic-dynamic` and `bionic-api-level:N`, following
  upstream's own platform-specific vocabulary (`glibc-max-symbol-version:N`,
  `libSystem`, `vcruntime:140`).
- **`python_stdlib_test_packages`** lists the test packages the distribution
  actually ships, where upstream emits a fixed superset.
- **`python_config_vars`** has host paths removed and prefix-relative paths
  substituted, because the upstream package's values name the machine that built
  it.
- **`run_tests` names a harness that runs on a device.** It points at
  `build/run_tests.py`, the path upstream uses, and the script there re-executes
  the interpreter against the `test` package the distribution ships. Upstream
  passes `--slow-ci`; this does not, because on a device that profile runs for
  hours and much of it is unsupported on Android, so the caller chooses.
- **Producer object-graph fields are empty rather than absent.** Neither build
  ships core object files, a static libpython, or a relinkable inittab. Saying
  so with an empty list is a fact about the distribution; leaving the field out
  said the same thing to a reader and nothing at all to a parser.

## Artifact naming

```
cpython-{version}+{tag}-{triple}[-{build option}]-{flavor}
```

```
cpython-3.14.6+20260727-aarch64-linux-android-upstream-install_only.tar.gz
cpython-3.14.6+20260727-aarch64-linux-android-install_only.tar.gz
cpython-3.14.6+20260727-aarch64-linux-android-extended-install_only.tar.gz
```

`{tag}` is the release date, as upstream. `default` is omitted from the name.
Unlike upstream, the build option appears on install-only archives too, because
the difference between `upstream` and `default` is a six-fold startup difference
and a consumer should see it without opening the metadata.

Data products use their own naming on their own track:

```
android-data-ca-{certifi}-tzdata-{tzdata}-r{n}.tar.zst
```

## Licensing

The repository's own source — build recipes, tooling, workflows — is MIT.

That license does not extend to the distributions this repository publishes.
Those archives carry third-party code under its own terms:

| Component | License |
| --- | --- |
| CPython | Python-2.0, CNRI-Python |
| OpenSSL 3.5.7 | Apache-2.0 |
| SQLite | public domain |
| libffi | MIT |
| bzip2 | BSD-style |
| liblzma (xz 5.4.6) | public domain |
| zstd | BSD-3-Clause / GPL-2.0 dual; BSD applies |
| mpdecimal | BSD-2-Clause |
| Expat | MIT |
| HACL\* | Apache-2.0 / MIT dual |
| pip and its vendored packages | MIT, Apache-2.0, BSD, MPL-2.0 |
| certifi CA payload (data track) | MPL-2.0 |

None of these conflict with MIT for this repository's own code. Three place
obligations on the release process rather than on the license choice:

- **Python-2.0 §3** requires a brief summary of the changes made to Python. The
  launcher, the `DT_RUNPATH` mutation, and the metadata adaptations are each
  recorded with before/after identities under `python/build/`.
- **MPL-2.0** is file-level copyleft. certifi's CA payload is redistributed
  unmodified, with its license text, on the data track.
- **xz** ships `COPYING.GPLv2` in its documentation because the xz command-line
  scripts are GPLv2. The distributions link `liblzma` only — public domain in
  5.4.6 — and carry no `bin/` payload from the dependency set, so no GPL
  obligation attaches. The assembler rejects an upstream archive that
  unexpectedly contains `prefix/bin`.

One file here is not original: `cpython-android/python.c` is modelled on
CPython's `Programs/python.c` and is covered by the Python license, as noted in
its header.

### Where the license texts live

Per-component license texts are committed at `licenses/` and copied into every
archive, one plain-text file per component, as upstream does. `licenses/components.json`
records, for each component, its version, its SPDX identifier, which text ships
for it, and where that text came from; the assembler fails if the manifest and
the shipped set disagree.

The placement deviates from upstream by one directory, deliberately. Upstream
copies its texts into `python/licenses/`, which is a sibling of
`python/install/` — and the install-only projection carries forward only what is
under `python/install/`, so the flavor most consumers actually take ships
without any third-party license text. Putting the same files inside the prefix
instead means the projection lands them at `python/licenses/`, the same relative
path upstream uses, in every flavor. `license_path` names them there.

Two components ship no separate file. pip and all of its vendored packages carry
their own license files inside the payload, under
`lib/python3.14/site-packages/pip-*.dist-info/licenses/`. Android's `libc`,
`libdl`, `libm`, and `liblog` are provided by the device and only linked
against, never distributed.

Texts are taken from the versions this project actually ships, which is why
several differ from upstream's copy of the same component: upstream's
`LICENSE.liblzma.txt` carries the 0BSD terms that XZ Utils adopted in 5.6, while
the 5.4.6 this project ships is public domain.


[pbs]: https://github.com/astral-sh/python-build-standalone
[research]: https://github.com/daylight-00/cpython-android-cli
