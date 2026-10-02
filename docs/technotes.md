# Technical Notes

Why this repository builds what it builds, and how.

## What This Repository Is

- **Purpose** — standalone, redistributable CPython distributions for Android/Bionic.
- **Contract** — follows [astral-sh/python-build-standalone][pbs] (archive roots, flavor relationships, `PYTHON.json`, artifact naming, release model) wherever the Android input makes that truthful.
- **Goal** — a consumer that already understands python-build-standalone learns nothing new.
- **Not** — a CPython fork, a Termux package, or a research repository.
- **Design questions** — settled in [cpython-android-cli][research]; this repository holds the build recipes and release machinery.

## Targets and Build Options

Matches upstream's own split:

```
triple          what a device must provide      aarch64-linux-android
build option    how the distribution was made   default | upstream | extended
flavor          packaging                       full | install_only | install_only_stripped
```

- **Triple** — `aarch64-linux-android` for everything: upstream defines `target_triple` as "Rust's set of defined targets", and that is Rust's Android target. It carries no API level; see [Why the Triple Has No API Level](#why-the-triple-has-no-api-level).

| Build option | Produced from | Minimum API | Status |
| --- | --- | --- | --- |
| `upstream` | the official Python.org Android package, re-assembled | 24 | published |
| `default` | CPython source with all six pinned dependency recipes | 34 | published |
| `extended` | `default` plus the additional dependencies upstream ships | 34 | planned |

- **`default`** — the flagship; carries no marker in artifact names, as upstream's blessed build does.
- **`upstream`** — a permanent baseline, not a stepping stone; its device coverage is inherited from, and is the responsibility of, the official package.
- **`extended`** — what upstream's Linux distributions have and the official Android package does not: readline and ncurses for an editable REPL, Tk, uuid, Berkeley DB.

## The Android API Policy

Neither API level is chosen by this project. Each follows a stated rule, which is what makes the numbers defensible rather than arbitrary.

```
upstream    whatever floor the official package was built with
default     the last API level whose Bionic additions change the CPython build
```

- **Measured** — `./resolve-api-level.py` configures CPython at candidate levels and compares the `pyconfig.h` each produces. The answer is the lowest level whose decisions match the highest level the pinned NDK can compile for.
- **Why `pyconfig.h`** — reading `AC_CHECK_FUNCS` against Bionic's [per-API lists][bionic-status] means interpreting configure's shell conditionals to know which probes run. Comparing generated files needs no such judgment and covers every kind of decision, not only function probes.

| API | Bionic adds | Reaches the build |
| --- | --- | --- |
| 34 | `close_range`, `copy_file_range`, `memset_explicit`, `__freadahead`, `posix_spawn_file_actions_add{,f}chdir_np` | **`HAVE_CLOSE_RANGE`, `HAVE_COPY_FILE_RANGE`** |
| 35 | `tcgetwinsize`, `tcsetwinsize`, `_Fork`, crash-detail and time zone functions | nothing |
| 36 | `qsort_r`, `sig2str`/`str2sig`, `lchmod`, pthread affinity functions, `mseal` | `lchmod` would, but the pinned NDK compiles no higher than 35 |

The latest measurement, against the pinned CPython and NDK r27d (the `api-level` workflow repeats it weekly):

```
measured floor       API 34
NDK compiles up to   API 35
levels configured    28, 32, 33, 34, 35
evidence             API 33 -> 34 changes HAVE_CLOSE_RANGE, HAVE_COPY_FILE_RANGE
```

- **Runtime weight** — `close_range` carries it: `_posixsubprocess` closes inherited descriptors before `exec` with it instead of walking `/proc/self/fd`.
- **Floor is 34 because of the NDK** — the pinned NDK cannot compile above 35. The `lchmod` probe does run on Android (`MACHDEP` is `android`) and fails only because Bionic added `lchmod` at 36.
- **The floor can move** — an NDK that compiles for 36 would move it, which is why the number is measured, not argued.

### Why the Triple Has No API Level

- **Floor, not ABI split** — upstream encodes ABI splits in the triple (`musl` versus `gnu`) and CPU requirements (`x86_64_v2`, `v3`), but keeps its minimum glibc version in the docs. An API level is the same kind of thing as that glibc floor.
- **Derived values** — both floors are derived, so encoding a snapshot into a permanent identifier would rename artifacts for reasons nobody decided. If upstream raises its floor, or a future CPython adds a check for an API 36 function, every URL and catalog key would churn.
- **Matches CPython** — its own metadata is unversioned: `SOABI cpython-314-aarch64-linux-android`, `MULTIARCH aarch64-linux-android`, `config-3.14-aarch64-linux-android`.
- **Where the floor is published** — `PYTHON.json` (`crt_features`, `python_platform_tag`, `python_config_vars.ANDROID_API_LEVEL`), the documentation, and the release notes. It can move without a decision here, so a change is called out prominently in the notes.

### Why a Source Build Is Worth Having

Controlled measurement on one device of the same CPython 3.14.6 sources at different compile API levels:

| Class | API | Startup (median) | Loop | SHA-256 / 1 MiB |
| --- | --- | --- | --- | --- |
| official prebuilt | 24 | 331 ms | 1690 ms | 13.87 ms |
| source-built, prebuilt deps | 36 | 55 ms | 362 ms | 10.31 ms |
| source-built, source deps | 36 | 31 ms | 161 ms | 4.67 ms |

- **Source** — `experiments/epoch2-upstream-thin-api36-controlled-comparison` in the research repository, which records two caveats.
- **Not API alone** — the API 36 classes also changed NDK revision, because API 36 was not buildable with the stable NDK then, so the delta is not attributable to the API level.
- **No minimum selected** — that experiment chose no minimum API; this repository does.

## Toolchain

- **NDK** — one revision, `27.3.13750724` (r27d), serves every build. The official CPython 3.14.6 Android release pins it and `Android/android-env.sh` hardcodes it, so no patch is needed.
- **Release host** — `linux-x86_64`, with the NDK Google publishes.
- **On-device builds** — research only, never releases. Google ships no `aarch64` Linux/Android host NDK, so these use the community rebuild at [HomuHomu833/android-ndk-custom][ndk-custom].
- **`patchelf`** — pinned too: setting a single relative `DT_RUNPATH` needs its `--page-size` support so the 16 KiB alignment survives the rewrite.

## How the Source Build Works

- **Steering** — upstream's `Android/android.py` does the cross-compilation; this project steers it rather than reimplementing it. Everything the interpreter build does is upstream's.
- **Dependency prefix** — the one thing steered. It is populated before `configure` runs, so the flow skips its download of prebuilt archives through its own guard for an existing prefix.
- **Dependencies** — built from upstream's own recipes, pinned at one commit, with two recorded overrides: the NDK revision, so dependencies and interpreter share a toolchain, and `openssldir`.
- **Reproducibility overrides** — two more, covered under [Reproducibility](distributions.md#reproducibility): the file prefix map, and naming tools without their directory.
- **Installed files** — each component's output is taken as it comes, except its pkg-config file.
- **pkg-config rewrite** — a file records the directory its component was configured in (`libffi`, `xz`, `zstd`; `xz` writes `includedir` and `libdir` in full, not only `prefix`). Merged into one prefix it describes somewhere it is not and misleads `configure`'s include and library directories, so each is rewritten to its own prefix before its contents are recorded.
- **One commit, not release tags** — component tags are not contemporaneous: older ones read the API level from a lowercase `api_level` variable that a caller setting `ANDROID_API_LEVEL` never reaches, and they pin three different NDK revisions.
- **Mixed levels** — building from those tags yields dependencies at two API levels: visibly for `xz`, invisibly for `libffi`, which is statically linked into `_ctypes` and carries no ELF note.
- **API level checked twice** — the visible check alone misses mixed levels.
  - **Recipe environment** — evaluated; its resolved compiler must name the requested level. Catches the request never arriving, and is the only check that covers static archives.
  - **ELF note** — every executable and shared object must report that level in the `.note.android.ident` the NDK stamps into it. Catches the request arriving and being ignored.

### What the Source Build Ships

- **Whitelist** — the build prefix is not a distribution. It carries dependency command-line tools, which CPython does not link and some of which are the GPLv2 scripts this project's licensing position depends on not shipping, and static archives that are build inputs. A whitelist shaped like upstream's own packaging step reduces it.
- **Guard** — a dependency tool or a static archive reaching the distribution fails the build.
- **No `__pycache__`** — `make install` compiles the standard library three times over. Upstream deletes every `__pycache__` from its install tree and the official package carries none, so this does too. Timestamp-invalidated bytecode embeds the source mtime and can never reproduce.
- **No launcher** — the build produces CPython's own `bin/python3.14`, so unlike the upstream-derived build it needs none from this project.
- **Stripped flavor** — `install_only_stripped` is meaningfully smaller than `install_only`. The upstream-derived pair differ by a few kilobytes because the official package arrives already stripped.

## What a Build Must Carry

Upstream validates every distribution against a hand-written table of expected extension modules. This project leaves that class of decision to python.org, as it does the dependency set and the `upstream` API floor.

- **Derived expectation** — CPython's `configure` records its per-module decision in the `sysconfigdata` the distribution ships, and both halves of the check read it:

```
build    every module built as a shared object is in the distribution, and no other
device   every module configure said it built imports, builtins included
```

- **No list to keep** — an `extended` build is held to readline and Tk the moment `configure` says `yes` to them.
- **Why not probe `lib-dynload`** — importing whatever shipped proves that what shipped works; it cannot notice a module that stopped being built. The gate refuses a receipt that predates the derived probe for the same reason.

## Following Upstream

- **Only CPython's version is watched** — everything else follows from the pinned version, so there is one discovery policy here where upstream keeps one per package.
- **One listing** — the official Android package lives in the same python.org directory as the source tarball.
- **Dependency set is derived** — `Android/android.py` names the exact release assets its build unpacks and the source build compiles those versions, so the set is read out of the pinned source. Bumping OpenSSL because a newer one exists would leave the interpreter built against a set CPython does not expect. `update-pins.py` re-reads the derivation on every bump.

```console
$ ./update-pins.py            # what is pinned, and what python.org has
$ ./update-pins.py --write    # move the pins to the newest patch of the series
```

- **Weekly workflow** — runs it and opens a pull request when the series has moved. It opens a request rather than committing, because the automation exists to notice, not to decide.
- **On the pull request** — the build workflow builds and validates it; the api-level workflow re-measures the floor because `config/**` changed.
- **After merge** — [Releasing Unattended](#releasing-unattended) carries on if turned on. Only taking the release out of prerelease needs a device.
- **Patch bumps** — exactly the case [the waiver](#releasing-without-one) covers: the pinned bytes move and nothing this project owns does.
- **New series** — a separate decision, not followed. `upstream` cannot exist before 3.14, because python.org publishes no Android package for earlier series, and every added series costs a device qualification per release.

## Release Model

- **Manual, as upstream** — `workflow_dispatch` with an explicit tag and commit, through the `release` environment, which asks a person to approve once it has required reviewers. No automatic release on green.
- **One opt-in exception** — [Releasing Unattended](#releasing-unattended).
- **Dry run** — `dry-run` defaults to true: a release is the one action in this repository that cannot be taken back.
- **Tags are immutable** — a published tag's assets are never replaced, because the uv catalog pins them by hash.
- **Contents** — `SHA256SUMS`, per-component license texts inside each archive, build provenance attestations, generated release notes, and a `download-metadata.json` catalog per build option.
- **Draft first** — the release is created as a draft and published once every asset is uploaded, so a catalog never points at an empty release.
- **`latest-release`** — for a qualified release, this branch publishes the catalogs and a `latest-release.json` pointer at stable raw URLs.
- **Notes are generated** — from the build receipts, because they state the minimum Android API per build. The floor can move without anyone deciding to move it; the notes are where that becomes visible.

### The Device Qualification Gate

- **Why a device** — CI has no Android runner, so "does this actually run?" cannot be answered there.
- **`qualify.py`** — runs on a device against a built archive and writes a receipt. Standard library only, because a device is not guaranteed to have anything else.
- **Never raises** — a probe that cannot start is recorded as a failure rather than losing the receipt.
- **The receipt records** — interpreter identity; every module `configure` said it built, importing; every shared library `dlopen`ed; a subprocess spawned; `pip` and `venv` exercised; the whole prefix copied to a deeper path and re-checked.
- **Location** — `qualification/<tag>/cpython-<version>-<triple>[-<build option>].json`, named after the artifact stem so a directory says which Python each receipt qualified.
- **The gate** — the release workflow refuses to publish unless a receipt covers **every artifact in the release by SHA-256**, or the waiver is allowed and the release goes out as a prerelease that says it has none ([below](#releasing-without-one)).
- **Evidence for bytes only** — a receipt names the bytes it covers, so one produced against an earlier build cannot be carried forward silently.
- **Also checked** — the device's ABI is one this project releases for, and the interpreter reported the API level the build declares.

### Releasing Without One

A device receipt cannot be produced unattended, so the gate is the one thing between this project and a release that follows a new CPython on its own. `allow-waiver` opens it without weakening what a receipt means: nothing claims an older one covers newer bytes.

- **What it does** — publishes on a claim sized to what is known, and says which. The gate records one of three footings, strongest first, and the release notes open with the matching caution.

| Footing | When | What the notes claim |
| --- | --- | --- |
| `upstream-only` | the only difference from the last build a device ran is the pinned CPython input | the rest of the code is the code a device ran; what is unverified is what came with the new upstream |
| `changed` | anything else differs — a file of this project's own, a toolchain bump, or a moved API floor | nothing about a device; only what CI checks |
| `never-run` | no device ever ran this build | nothing about a device; only what CI checks |

- **Only `upstream-only` rests on an earlier receipt** — the launcher, loader normalization, metadata overlay, curation, and license set are the code that was qualified, so the residual risk belongs to upstream.
- **`changed` and `never-run`** — the risk may be this project's own, and the notes say the code that assembled the interpreter is not known to be the code a device ran.
- **What CI checks** — the same in all three: every archive is byte-reproducible and holds to the distribution contract.
- **No refusals** — `changed` and `never-run` publish rather than refuse. A refusal would end unattended releases at the first commit touching anything but a pin, and protect nobody the prerelease channel does not: those bytes stay out of what `uv python install` resolves either way.
- **`pythonbuild/waiver.py`** — decides between the first two. Its polarity is deliberate: it names what is *allowed* to differ and drops the claim on everything else, so a file nobody considered fails closed.
- **Deliberately outside the allowance** — `config/toolchain.lock.json` is upstream in origin but not in effect: an NDK bump changes every compiled byte and can move the API floor.
- **A moved floor** — drops the allowance by itself: a different floor is a different set of devices, which unchanged packaging does not stand in for.
- **Prerelease** — a release without a receipt never becomes the default. Its notes open with the fact, and `latest-release` and the uv catalogs stay at the last qualified release, so `uv python install` keeps resolving to bytes a device ran and taking one is an explicit act.
- **Promotion** — a published tag cannot be released again, so promoting means qualifying a build of the same inputs on a device under a fresh tag, committing the receipt, and releasing that tag without the waiver.
- **Verdict file** — `<build>.qualification.json` travels with the artifacts, footing and reason included, rather than being inferred from what the operator asked for.
- **Release-level verdict** — a release is qualified when every build in it was; otherwise the notes take their wording from the weakest build's footing.

### Releasing Unattended

- **Trigger** — `auto-release.yml` runs when a push to `main` touches `config/**` and once a day. It dispatches the release workflow with the waiver allowed when some pinned CPython version has no published release.
- **Effect** — a bump merged on Monday is released without anyone choosing a tag or a commit.
- **Idempotent** — which lets the daily run double as a retry. It does nothing while every pinned version has a release, while a release is already running, or once today's tag is taken; a failed release is attempted again the next morning.
- **First brake, `AUTO_RELEASE`** — a release cannot be taken back, so the repository variable has to be `true`. Until it is, the workflow does nothing at all.

```console
$ gh variable set AUTO_RELEASE --body true
```

- **Second brake, `release` environment** — gates the release workflow itself. It has no required reviewers today, so it asks nobody; giving it some puts a person back in the loop without touching anything else.
- **Still manual** — merging the pull request `update-pins` opens, and everything that needs a device: a release this produces is a prerelease until somebody qualifies its bytes.

## uv Integration

- **Key** — uv's managed-Python key is `{implementation}-{version}-{os}-{arch}-{libc}`, and both `os` and `libc` are closed enumerations.
- **`libc`** — accepts `gnu`, `gnueabi`, `gnueabihf`, `musl`, `musleabi`, `musleabihf`, and `none`; `android` is not a value.
- **Detection decides** — the key must match what uv detects on the device, and there uv reports `linux` with no libc:

```
cpython-<version>-linux-aarch64-none
```

- **One catalog per build option** — every build option collides on that one key, so each publishes its own: `download-metadata.json` for the flagship, `download-metadata-upstream.json` for the baseline. [Running](running.md#with-uv) has the command.
- **Re-probe** — the catalog claims `linux`, so an installed interpreter should be re-probed to confirm Android identity: `SOABI cpython-314-aarch64-linux-android`, `MULTIARCH aarch64-linux-android`, and the `android-{api}-arm64_v8a` platform.
- **No built-in catalog** — upstream uv has none, and this project does not claim one.

[pbs]: https://github.com/astral-sh/python-build-standalone
[research]: https://github.com/daylight-00/cpython-android-cli
[bionic-status]: https://android.googlesource.com/platform/bionic/+/refs/heads/main/docs/status.md
[ndk-custom]: https://github.com/HomuHomu833/android-ndk-custom
