# Technical Notes

Why this repository builds what it builds, and how. Design questions are
settled in [cpython-android-cli][research] and arrive here as recipes.

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
| `upstream` | the official Python.org Android package, re-assembled | 24 | published |
| `default` | CPython source with all six pinned dependency recipes | 34 | published |
| `extended` | `default` plus the additional dependencies upstream ships | 34 | planned |

An earlier release, `20260728`, carries the `upstream` build alone. It was cut
before the archives were byte-reproducible across machines and its assets match
nothing built here today. It is left in place rather than replaced: a published
name must keep serving the bytes it was published with, and the uv catalog pins
those bytes by hash.

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

For `default` the rule is measured rather than reasoned about, by
`./resolve-api-level.py`: CPython is configured at candidate levels and the
`pyconfig.h` each produces is compared, and the answer is the lowest level whose
decisions already match the highest level the pinned NDK can compile for.

| API | Bionic adds | Reaches the build |
| --- | --- | --- |
| 34 | `close_range`, `copy_file_range`, `memset_explicit`, `__freadahead`, `posix_spawn_file_actions_add{,f}chdir_np` | **`HAVE_CLOSE_RANGE`, `HAVE_COPY_FILE_RANGE`** |
| 35 | `tcgetwinsize`, `tcsetwinsize`, `_Fork`, crash-detail and time zone functions | nothing |
| 36 | `qsort_r`, `sig2str`/`str2sig`, `lchmod`, pthread affinity functions, `mseal` | `lchmod` would, but the pinned NDK compiles no higher than 35 |

Measured against CPython 3.14.6 and NDK r27d:

```
measured floor       API 34
NDK compiles up to   API 35
levels configured    28, 32, 33, 34, 35
evidence             API 33 -> 34 changes HAVE_CLOSE_RANGE, HAVE_COPY_FILE_RANGE
```

So the answer today is 34, and `close_range` carries the runtime weight of it:
`_posixsubprocess` uses it to close inherited descriptors before `exec` instead
of walking `/proc/self/fd`.

Note what the API 36 row does *not* say. An earlier version of this document
recorded that `lchmod` is checked only under `if test "$MACHDEP" != linux`,
"which excludes Android". It does not: `MACHDEP` is `android`, the probe runs,
and it comes back negative only because Bionic introduced `lchmod` at 36 and the
NDK cannot target that yet. The floor is 34 because of the NDK ceiling, not
because nothing above 34 would register. An NDK that compiles for 36 would move
it — which is the whole reason the number is measured now instead of argued.

Reading `AC_CHECK_FUNCS` and looking each name up in Bionic's [per-API
lists][bionic-status] is the obvious cheaper method and is the one that produced
that error: knowing which probes actually run means interpreting configure's
shell conditionals. Comparing generated `pyconfig.h` files needs no such
judgement, and covers every kind of decision configure makes rather than
function probes alone.

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

## How the source build works

Upstream's `Android/android.py` does the cross-compilation; this project steers
it rather than reimplementing it. The one thing it steers is the dependency
prefix, which is populated before `configure` runs so the flow skips its own
download of the prebuilt archives, through the guard it already has for a prefix
that exists. Everything the interpreter build itself does is upstream's.

The dependencies are built from upstream's own recipes, pinned at one commit,
with two recorded overrides: the NDK revision, so the dependencies and the
interpreter share a toolchain, and `openssldir`. Two more overrides exist for
reproducibility rather than for behaviour, and are covered under
[reproducibility](distributions.md#reproducibility): the file prefix map, and naming the tools
without their directory.

What each component installs is taken as it comes, with one exception. A
component's pkg-config file records the directory that component was configured
in — `libffi`, `xz` and `zstd` do, and `xz` writes `includedir` and `libdir` out
in full, not only `prefix`. Merged into one prefix those files describe somewhere
they are not, which decides which include and library directories `configure` is
handed, so each is rewritten to describe the prefix it is in before its contents
are recorded.

One commit rather than each component's own release tag. Those tags are not
contemporaneous: the older ones read the API level from a lowercase `api_level`
variable that a caller setting `ANDROID_API_LEVEL` never reaches, and they pin
three different NDK revisions between them. Building from them produced a
dependency set at two different API levels — visibly for `xz`, and invisibly for
`libffi`, which is statically linked into `_ctypes` and carries no ELF note to
give it away.

So the API level is checked twice, because the visible check alone would have
missed that. The recipe environment is evaluated and its resolved compiler must
name the requested API level, which catches the request never arriving and is
the only check that covers static archives. Then every executable and shared
object must report that level in the `.note.android.ident` the NDK stamps into
it, which catches the request arriving and being ignored.

### What the source build ships

The build prefix is not a distribution. It carries the dependency command-line
tools, which are not what CPython links and some of which are the GPLv2 scripts
this project's licensing position depends on not shipping, and it carries static
archives that are build inputs. A whitelist of the same shape as upstream's own
packaging step reduces it, and the result is checked: a dependency tool or a
static archive reaching the distribution fails the build.

`make install` also compiles the standard library three times over. Upstream
deletes every `__pycache__` from its install tree and the official Android
package carries none, so this does too — and it would have to regardless,
because timestamp-invalidated bytecode embeds the mtime of the source it was
compiled from and can never reproduce.

Two consequences worth knowing. The source build produces CPython's own
`bin/python3.14`, so unlike the upstream-derived build it needs no launcher from
this project. And its `install_only_stripped` archive is meaningfully smaller
than its `install_only`, where the upstream-derived pair differ by a few
kilobytes — the official package arrives already stripped, so for that build the
stripped flavor is close to a formality.

## Release model

Releases are manual, as upstream: `workflow_dispatch` with an explicit tag and
commit, gated on a protected environment. There is no automatic release on
green.

`dry-run` defaults to true. A release is the one action in this repository that
cannot be taken back, so publishing has to be asked for explicitly.

Every release carries `SHA256SUMS`, per-component license texts inside each
archive, build provenance attestations, generated release notes, and a
`download-metadata.json` catalog per build option. The release is created as a
draft and only published once every asset is uploaded, so a catalog never points
at an empty release. The `latest-release` branch then publishes the catalogs and
a `latest-release.json` pointer at stable raw URLs.

Release notes are generated from the build receipts rather than written by hand,
because they have to state the minimum Android API per build. That floor is
derived rather than chosen and can therefore move without anyone deciding to
move it; the notes are where that becomes visible.

### The device qualification gate

CI has no Android runner, so the check that matters most — does this actually
run? — cannot happen there. `qualify.py` runs on a device against a built
archive and writes a receipt recording what it found: interpreter identity,
every extension module imported, every shared library `dlopen`ed, a subprocess
spawned, `pip` and `venv` exercised, and the whole prefix copied to a deeper path
and re-checked. It uses only the standard library, because a device is not
guaranteed to have anything else, and it never raises: a probe that cannot even
start is recorded as a failure rather than losing the receipt.

Receipts are committed under `qualification/<tag>/<build>.json`, and the release
workflow refuses to publish unless one covers **every artifact in the release by
SHA-256**. A receipt is evidence only for the bytes it names, so one produced
against an earlier build cannot be carried forward silently. The gate also
checks that the device's ABI is one this project releases for and that the
interpreter reported the API level the build declares.

### Releasing without one

A device receipt cannot be produced unattended, and that makes the gate the one
thing standing between this project and a release that follows a new CPython on
its own. `allow-waiver` opens it, and does so without weakening what a receipt
means — nothing claims an older one covers newer bytes.

The claim it makes instead is weaker and true. If the only difference between the
last build a device ran and this one is the pinned CPython input, then the
launcher, the loader normalization, the metadata overlay, the curation and the
licence set are the same code that was qualified, and the residual risk belongs
to upstream. That is a risk an unattended release can reasonably take. If
anything else differs, the risk is this project's own and the receipt is
required.

`pythonbuild/waiver.py` decides it, and the polarity is deliberate: it names what
is *allowed* to differ and blocks on everything else, so a file nobody considered
fails closed. Two things sit outside the allowance on purpose.
`config/toolchain.lock.json` is upstream in origin but not in effect — an NDK
bump changes every compiled byte and can move the API floor. And a floor that
moved blocks a waiver by itself, because a different floor means a different set
of devices, which no amount of unchanged packaging stands in for.

What a waived release is not is the default. It is published as a prerelease, its
notes open with the fact, and `latest-release` and the uv catalogs are left
pointing at the last qualified release — so `uv python install` keeps resolving
to bytes a device ran, and taking a waived build is an explicit act. Promoting
one means qualifying those exact artifacts, committing the receipt, and
re-releasing without the waiver.

The verdict travels with the artifacts as
`<build>.qualification.json` rather than being inferred from what the operator
asked for: a release is qualified when every build in it was.

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


[pbs]: https://github.com/astral-sh/python-build-standalone
[research]: https://github.com/daylight-00/cpython-android-cli
