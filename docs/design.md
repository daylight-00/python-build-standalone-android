# Design

## What this repository is

`python-build-standalone-android` produces and publishes standalone,
redistributable CPython distributions for Android/Bionic.

It follows the distribution contract of
[astral-sh/python-build-standalone][pbs] — archive roots, flavor relationships,
`PYTHON.json` metadata, artifact naming, and the release model — wherever the
Android input makes that truthful. The goal is that a consumer which already
understands python-build-standalone needs to learn nothing new.

It is not a CPython fork, not a Termux package, and not a research repository.
Design questions are settled in [cpython-android-cli][research]; this repository
holds the build recipes and the release machinery.

## Targets and build options

Two axes, matching upstream's own split:

```
triple          what a device must provide      aarch64-linux-android
build option    how the distribution was made   default | upstream | extended
flavor          packaging                       full | install_only | install_only_stripped
```

The triple is `aarch64-linux-android` for everything — upstream defines
`target_triple` as "Rust's set of defined targets", and that is Rust's Android
target. It carries no API level; see [Why the triple has no API
level](#why-the-triple-has-no-api-level).

| Build option | Produced from | Minimum API | Status |
| --- | --- | --- | --- |
| `upstream` | the official Python.org Android package, re-assembled | 24 | released |
| `default` | CPython source with all six pinned dependency recipes | 34 | in development |
| `extended` | `default` plus the additional dependencies upstream ships | 34 | planned |

`default` is the flagship and carries no marker in artifact names, the way
upstream's blessed build does. `upstream` is not a stepping stone that gets
retired — it is a permanent baseline whose device coverage is inherited from,
and is the responsibility of, the official package.

`extended` covers what upstream's Linux distributions have and the official
Android package does not: readline and ncurses for an editable REPL, Tk, uuid,
and Berkeley DB.

## The Android API policy

**Neither API level is chosen by this project.** Each follows a stated rule, and
that is what makes the numbers defensible rather than arbitrary.

```
upstream    whatever floor the official package was built with
default     the last API level whose Bionic additions change the CPython build
```

For `default` the rule resolves by checking [Bionic's per-API function
lists][bionic-status] against `AC_CHECK_FUNCS` in the pinned CPython source:

| API | Bionic adds | Detected by CPython `configure` |
| --- | --- | --- |
| 34 | `close_range`, `copy_file_range`, `memset_explicit`, `__freadahead`, `posix_spawn_file_actions_add{,f}chdir_np` | **`close_range`, `copy_file_range`** |
| 35 | `tcgetwinsize`, `tcsetwinsize`, `_Fork`, crash-detail and time zone functions | none |
| 36 | `qsort_r`, `sig2str`/`str2sig`, `lchmod`, pthread affinity functions, `mseal` | none — `lchmod` is checked, but only under `if test "$MACHDEP" != linux`, which excludes Android |

Above API 34 the build makes identical decisions, so raising the level would
only cost device coverage. Of the two functions, `close_range` carries the
runtime weight: `_posixsubprocess` uses it to close inherited descriptors before
`exec` instead of walking `/proc/self/fd`.

API 34 also stays inside the stable NDK the official CPython Android release
already pins, which compiles up to API 35.

### Why the triple has no API level

An Android API level is a minimum-version floor, not an ABI split. Upstream
encodes ABI splits in the triple (`musl` versus `gnu`) and CPU requirements
(`x86_64_v2`, `v3`), but keeps its minimum glibc version in the docs. The API
level is the same kind of thing as that glibc floor.

Both of our numbers are also *derived*, so encoding a snapshot of one into a
permanent identifier would rename artifacts for reasons nobody decided: if
upstream raises its floor, or a future CPython adds a configure check for an API
36 function, every URL and catalog key would churn.

CPython itself uses the unversioned form throughout its own metadata —
`SOABI cpython-314-aarch64-linux-android`, `MULTIARCH aarch64-linux-android`,
`config-3.14-aarch64-linux-android` — so the unversioned triple also matches how
the runtime describes itself.

The floor is published where a consumer will look for it: `PYTHON.json`
(`crt_features`, `python_platform_tag`, `python_config_vars.ANDROID_API_LEVEL`),
the documentation, and the release notes. Because it can move without a decision
here, a floor change is called out prominently in the release notes.

### Why a source build is worth having

Controlled measurement on one device of the same CPython 3.14.6 sources at
different compile API levels:

| Class | API | Startup (median) | Loop | SHA-256 / 1 MiB |
| --- | --- | --- | --- | --- |
| official prebuilt | 24 | 331 ms | 1690 ms | 13.87 ms |
| source-built, prebuilt deps | 36 | 55 ms | 362 ms | 10.31 ms |
| source-built, source deps | 36 | 31 ms | 161 ms | 4.67 ms |

Source: `experiments/epoch2-upstream-thin-api36-controlled-comparison` in the
research repository. Two caveats are recorded there and repeated so the numbers
are not over-read: the API-36 classes also changed NDK revision, because API 36
was not buildable with the stable NDK at the time, so the delta is not
attributable to the API level alone; and that experiment selected no minimum
API — that decision is made here.

## Toolchain

One NDK revision, `27.3.13750724` (r27d), serves every build. It is the revision
the official CPython 3.14.6 Android release pins, and `Android/android-env.sh`
hardcodes it, so no patch is needed to use it.

Release builds run on `linux-x86_64` with the NDK Google publishes. Google ships
no `aarch64` Linux/Android host NDK, so on-device builds — used during research,
never for releases — use the community rebuild at
[HomuHomu833/android-ndk-custom][ndk-custom].

`patchelf` is pinned too: setting a single relative `DT_RUNPATH` requires its
`--page-size` support so the 16 KiB alignment survives the rewrite.

## Runtime data: CA certificates and time zones

Bionic provides neither of the two things a POSIX CPython assumes:

- no `/etc/ssl/certs`, so `ssl.create_default_context()` has an empty trust
  store and every HTTPS call fails, including `pip` and `uv`;
- no `/usr/share/zoneinfo`, so `zoneinfo.ZoneInfo("Asia/Seoul")` fails. Android's
  own tz database uses a private merged format CPython cannot read.

### `upstream` — external data product

The official package is consumed as-is, so no compiled-in default can be
changed. CA and time zone payloads ship as a **separate release track**:
`certifi` plus a raw `zoneinfo` tree, installed into an external `DATA_ROOT`
with an atomic `current` symlink and rollback.

Separating the track is deliberate: `certifi` and `tzdata` expire on their own
schedule, and a 227 KiB data refresh must not require republishing a 24 MiB
Python archive.

### `default` — compiled-in defaults

The source build sets Termux's absolute paths as build defaults, so the standard
discovery mechanism works the way it does in an upstream Linux build:

```
CPython   --with-tzpath=/data/data/com.termux/files/usr/share/zoneinfo
OpenSSL   --openssldir=/data/data/com.termux/files/usr/etc/tls
```

Both stay overridable at runtime (`SSL_CERT_FILE`, `SSL_CERT_DIR`,
`PYTHONTZPATH`), the external data product still works, and the runtime requires
no Termux prefix and no Termux native library. This is a courtesy to the
realistic user base, not a dependency — which is also why it is not named in the
artifact.

The two halves are configured in different places, and that decides the build's
scope. `--with-tzpath` is a CPython configure argument, free for a source build.
`--openssldir` is an *OpenSSL* configure argument, fixed when OpenSSL is built —
and upstream's `Android/android.py` downloads prebuilt BeeWare dependency
archives built with OpenSSL's default:

```
/usr/local/ssl/cert.pem
/usr/local/ssl/certs
```

Neither path exists on Android, which is the root cause of the empty trust
store. So `default` builds all six dependency recipes from source rather than
unpacking them. That is also the configuration the measurement above found
fastest.

Using Android's own system CA and tz databases belongs to `extended` or beyond,
and is still under research.

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
non-escaping symlinks. Two builds of the same input produce byte-identical
archives; CI checks this by building twice.

For `upstream`, `python/build/` cannot contain a producer object graph, because
the project did not produce the objects. It carries the upstream archive
identity and retained input, extracted upstream metadata and licenses, the
launcher build record, mutation manifests, and audit records. Nothing recorded
there names a host path, both so the archive stays reproducible and so the build
machine's layout is not published.

### Android adaptations

The official Android package is embedding-oriented and ships no interpreter
executable, so the project supplies one: the POSIX-equivalent
`Programs/python.c` `Py_BytesMain` frontend, with no loader bootstrap, no CA
policy, and no custom argument handling.

Every ELF object receives one relative `DT_RUNPATH` from its own directory to
the install `lib` directory, preserving `DT_NEEDED`, SONAME, architecture, ELF
kind, and the 16 KiB program-segment alignment contract. A project-required
`LD_LIBRARY_PATH` and bootstrap self-re-execution are both forbidden.

`bin/pip*` and `bin/python3.14-config` are shell wrappers that locate their
sibling interpreter relatively, because a generated console script bakes in the
absolute interpreter path it was created with and the prefix must stay
relocatable.

Writable state follows a three-root model:

```
INSTALL_ROOT   immutable, relocatable
DATA_ROOT      independently updateable CA and time zone payloads
STATE_ROOT     caller-owned cache, temp, user-site, and venv state
```

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
- **`run_tests` is omitted.** Upstream points it at a real test harness; this
  project has none yet, and naming a file that does not exist would be worse
  than leaving the field out.
- **Producer fields are omitted, not invented.** For `upstream` there are no
  core object files, no static libpython, and no relinkable inittab.

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

## Release model

Releases are manual, as upstream: `workflow_dispatch` with an explicit tag and
commit, gated on a protected environment. There is no automatic release on
green.

Every release carries `SHA256SUMS`, third-party notices, build provenance
attestations, and a `download-metadata.json` catalog per build option. The
`latest-release` branch publishes the catalogs and a `latest-release.json`
pointer at stable raw URLs.

One thing CI cannot do is run the distribution on a real device. Device
qualification is produced out of band and committed as a receipt; the release
workflow refuses to publish a build whose receipt is missing or does not match
the artifacts being released.

## uv integration

uv's managed-Python key is `{implementation}-{version}-{os}-{arch}-{libc}`, and
both `os` and `libc` are closed enumerations. `libc` accepts `gnu`, `gnueabi`,
`gnueabihf`, `musl`, `musleabi`, `musleabihf`, and `none` — `android` is not a
value it takes. More decisively, the key must match what uv detects on the
device, and there uv reports `linux` with no libc:

```
cpython-3.14.6-linux-aarch64-none
```

Every build option collides on that one key, so each publishes its own catalog:

```
download-metadata.json            the flagship build
download-metadata-upstream.json   the baseline build
```

```console
$ uv python install cpython-3.14.6-linux-aarch64-none \
    --python-downloads-json-url https://raw.githubusercontent.com/daylight-00/python-build-standalone-android/latest-release/download-metadata.json
```

`UV_PYTHON_DOWNLOADS_JSON_URL` and the `python-downloads-json-url` key in
`uv.toml` work equally well. Because the catalog claims `linux`, an installed
interpreter should be re-probed to confirm Android identity; it reports
`SOABI cpython-314-aarch64-linux-android`, `MULTIARCH aarch64-linux-android`,
and the `android-{api}-arm64_v8a` platform.

Upstream uv has no built-in Android catalog and this project does not claim one.

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

Upstream places per-component license texts in a `python/licenses/` root inside
every archive and points `license_path` at
`licenses/LICENSE.cpython.txt`. That root is not assembled yet, so `license_path`
currently names the license text the distribution already carries. **Assembling
it is a release blocker: no release may be published without it.**

## Out of scope

- Android ABIs other than `arm64-v8a`
- PGO, LTO, BOLT, debug, free-threaded, and JIT build variants
- Detached symbols or a separate debug distribution
- A bundled cross-build NDK, SDK, or sysroot
- APK/JNI packaging
- General `multiprocessing` support
- Portability and repair of user-built native wheels

[pbs]: https://github.com/astral-sh/python-build-standalone
[research]: https://github.com/daylight-00/cpython-android-cli
[ndk-custom]: https://github.com/HomuHomu833/android-ndk-custom
[bionic-status]: https://android.googlesource.com/platform/bionic/+/HEAD/docs/status.md
