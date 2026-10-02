# Distribution Archives

The contract each archive keeps. Named for [upstream's document][pbs] so a consumer of those archives learns nothing new.

## Archive Contract

Layout and flavors follow [upstream's distribution archives][pbs-dist].

- **Assembly order** — fixed; each flavor derives from the verified one above it, so `install_only` can be rebuilt from `full` and compared member for member:

```
verified input -> full -> install_only -> install_only_stripped
```

- **Layout** — one `python/` root:

```
python/
├── PYTHON.json     Astral metadata, format 8
├── build/
└── install/        a normal relocatable POSIX prefix
```

- **Compression** — `full` is `.tar.zst`; the install-only flavors are `.tar.gz`.
- **Members** — deterministic ordering, normalized ownership and timestamps, no absolute or traversal paths, no hard links, only relative non-escaping symlinks.

### The Extension Modules

A distribution carries exactly the extension modules CPython decided to build, and the archive says which.

- **Record** — `configure` records its per-module decision in the `sysconfigdata` every distribution ships:

```
MODULE_<NAME>_STATE   yes | missing | disabled | n/a
MODSHARED_NAMES       the modules built as shared objects
MODBUILT_NAMES        the modules linked into the interpreter
```

- **Static check** — `validate-distribution.py` requires every module `MODSHARED_NAMES` names to be in `lib-dynload`, and nothing else.
- **Loading** — needs a device: the qualification receipt records every module `configure` said it built, builtins included, importing there. See [the device qualification gate](technotes.md#the-device-qualification-gate).

### Reproducibility

Two builds of the same input are byte-identical on any host, and no archive names the build tree, the toolchain, or the build user's home. Each item guards one way that breaks.

- **umask** — `build.py` sets a fixed umask; `mkdir`s and JSON records written without a mode take the caller's, and it lands in the archive.
- **Compressor** — the `zstandard` library pinned by `uv.lock`, single-threaded; host `zstd` versions and threaded work division change the bytes.
- **Host paths** — generated text is rewritten to a placeholder; compiled objects get `-ffile-prefix-map` for the build tree and the NDK, since line tables name the sysroot headers read.
- **Recorded command lines** — tools are named without their directory so OpenSSL's compiler banner and `CONFIG_ARGS` carry no path; a string inside a shared object cannot be rewritten afterward.
- **`pkg-config`** — pinned `pkgconf` goes on `PATH` under the name the builds call and `PKG_CONFIG_PATH` is dropped; implementations disagree on `.pc` resolution and flag spelling, and configure records the result.
- **Timestamps** — `SOURCE_DATE_EPOCH` is the newest mtime in the pinned CPython source archive, covering `__DATE__`, `__TIME__`, and OpenSSL's banner with no constant to keep in step.
- **Earlier runs** — every tree a build writes into starts empty; a workspace may persist for clones and downloads, but a leftover prefix makes output depend on earlier builds.
- **Proof** — CI builds twice, the second under a different umask; repeating a build under identical conditions proves much less.
- **`upstream` build records** — `python/build/` holds no producer object graph, since the project produced no objects. It carries upstream archive identity and retained input, extracted upstream metadata and licenses, the launcher build record, mutation manifests, and audit records, none naming a host path.

## PYTHON.json Conformance

Follows [upstream's format 8][pbs-json]; upstream's reader decides whether the file conforms.

- **Types** — `version` is the string `"8"`, `python_implementation_hex_version` is an integer, `python_abi_tag` is `sys.abiflags` (empty for a release build).
- **Platform tag** — `python_platform_tag` is `sysconfig.get_platform()`, `android-<api>-arm64_v8a`, not the wheel tag `android_<api>_arm64_v8a`.
- **Interpreter values** — from PEP 739 `build-details.json`, which the interpreter wrote, not guessed.
- **`python_bytecode_magic_number`** — rebuilt from the shipped `pycore_magic_number.h`: CPython 3.14 moved it into a C constant and no `.pyc` ships to read it from.
- **Required fields** — never omitted; `src/json.rs` is `#[serde(deny_unknown_fields)]` and leaves most fields outside `Option`, so unknown and missing required keys are both errors.
- **Optional fields** — omitted when upstream marks them optional and they would describe something absent.
- **Empty means none** — it is how the format says so; a plausible-looking value is never invented.
- **Guards** — `tests/test_python_json.py` and `validate-distribution.py` hold the file to the schema in `pythonbuild/conformance.py`.

Deliberate deviations:

- **`build_options`** — provenance (`upstream`), not an optimization profile; it still matches the segment between triple and flavor in the artifact name, as upstream requires.
- **`crt_features`** — `bionic-dynamic` and `bionic-api-level:N`, following upstream's platform vocabulary (`glibc-max-symbol-version:N`, `libSystem`, `vcruntime:140`).
- **`python_stdlib_test_packages`** — the test packages the distribution ships; upstream emits a fixed superset.
- **`python_config_vars`** — host paths removed and prefix-relative paths substituted, because the upstream package's values name the machine that built it.
- **`run_tests`** — `build/run_tests.py`, as upstream, a harness that re-executes the interpreter on a device against the shipped `test` package. It omits `--slow-ci`, which runs for hours on a device and much of which is unsupported on Android, so the caller chooses.
- **Producer object-graph fields** — empty, not absent: neither build ships core object files, a static libpython, or a relinkable inittab, so `objs` is `[]` and `inittab_object` is `""`.

## Artifact Naming

```
cpython-<version>+<tag>-<triple>[-<build option>]-<flavor>
```

```
cpython-<version>+<tag>-aarch64-linux-android-upstream-install_only.tar.gz
cpython-<version>+<tag>-aarch64-linux-android-install_only.tar.gz
```

- **`<tag>`** — the release date, as upstream.
- **`default` is omitted** — the flagship carries no marker in the name; see [`ci-targets.yaml`](../ci-targets.yaml).
- **Build option on install-only archives** — unlike upstream, because `upstream` and `default` differ markedly in startup time ([measured here](technotes.md#why-a-source-build-is-worth-having)) and a consumer should see it without opening the metadata.
- **Data products** — their own naming, on their own track:

```
android-data-ca-<certifi>-tzdata-<tzdata>-r<n>.tar.zst
```

## Licensing

The repository's own source — build recipes, tooling, workflows — is MIT. That license does not extend to the distributions, which carry third-party code under its own terms:

| Component | License |
| --- | --- |
| CPython | Python-2.0, CNRI-Python |
| OpenSSL | Apache-2.0 |
| SQLite | public domain |
| libffi | MIT |
| bzip2 | BSD-style |
| liblzma (xz) | public domain |
| zstd | BSD-3-Clause / GPL-2.0 dual; BSD applies |
| mpdecimal | BSD-2-Clause |
| Expat | MIT |
| HACL\* | MIT |
| pip and its vendored packages | MIT, Apache-2.0, BSD, MPL-2.0 |
| certifi CA payload (data track) | MPL-2.0 |

None conflicts with MIT for this repository's own code. Three place obligations on the release process rather than on the license choice:

- **Python-2.0 §3** — requires a brief summary of the changes made to Python; the launcher, the `DT_RUNPATH` mutation, and the metadata adaptations are each recorded with before/after identities under `python/build/`.
- **MPL-2.0** — file-level copyleft; certifi's CA payload is redistributed unmodified, with its license text, on the data track.
- **xz** — ships `COPYING.GPLv2` in its documentation because the xz command-line scripts are GPLv2. The distributions link only `liblzma`, public domain at the pinned version, and carry no `bin/` payload from the dependency set, so no GPL obligation attaches; the assembler rejects an upstream archive containing `prefix/bin`.

Two files here are not original; a third restates a format:

- **`cpython-android/python.c`** — modeled on CPython's `Programs/python.c`; covered by the Python license, as its header notes.
- **`check.py`** — upstream's, adapted; stays under MPL-2.0 with its notice.
- **`pythonbuild/conformance.py`** — restates the field list of upstream's `PYTHON.json` reader, a description of a format rather than its code.

### Where the License Texts Live

- **Texts** — committed at `licenses/` and copied into every archive, one plain-text file per component, as upstream does.
- **Manifest** — `licenses/components.json` records each component's version, SPDX identifier, shipped text, and the text's origin; the assembler fails if manifest and shipped set disagree.
- **Placement** — one directory off upstream, deliberately. Upstream's `python/licenses/` sits beside `python/install/`, which the install-only projection drops, so the flavor most consumers take would ship no third-party license text.
- **Fix** — the files sit inside the prefix, so the projection lands them at `python/licenses/`, upstream's relative path, in every flavor; `license_path` names them.
- **pip** — it and its vendored packages carry their own license files under `lib/python3.14/site-packages/pip-*.dist-info/licenses/`; no separate file ships.
- **Bionic libraries** — `libc`, `libdl`, `libm`, and `liblog` come from the device and are only linked against, never distributed; no file ships.
- **Version-true texts** — taken from the versions shipped, so several differ from upstream's: upstream's `LICENSE.liblzma.txt` carries the 0BSD terms XZ Utils adopted in 5.6, while the pinned xz is public domain.

[pbs]: https://github.com/astral-sh/python-build-standalone
[pbs-dist]: https://github.com/astral-sh/python-build-standalone/blob/main/docs/distributions.md
[pbs-json]: https://github.com/astral-sh/python-build-standalone/blob/main/docs/distributions.md#pythonjson-file
