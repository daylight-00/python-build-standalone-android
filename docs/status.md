# Project Status

## Qualification

- **Gate** — publishing needs a device qualification receipt covering every artifact by SHA-256, committed under `qualification/<tag>/`.
- **Evidence** — a receipt covers only the bytes it names, so this page describes what a release shipped, not the project in general.
- **Without a receipt** — allowed, so a new CPython need not wait for a device; see [Releasing Without One](technotes.md#releasing-without-one).
  - It is a prerelease; the top of its notes says what it stands on.
  - The catalogs keep pointing at the last qualified release, so `uv python install` never resolves to it.
  - The scope below describes qualified releases; a prerelease is what its own notes say.

## Builds

One triple, `aarch64-linux-android`, `arm64-v8a` only.

| Build Option | Minimum Android | Where the Minimum Comes From |
| --- | --- | --- |
| `upstream` | 7.0 (API 24) | inherited from the official Python.org package |
| *(none)* | 14 (API 34) | the last API level that changes the CPython build |

- **`upstream` is permanent** — a baseline, not a stepping stone: one build whose device coverage is upstream's responsibility, kept as long as the official package exists.
- **Neither minimum is chosen here** — either can move without a decision in this repository: upstream may raise its floor, or a future CPython may add a configure check for a higher-API function. See [the API policy](technotes.md#the-android-api-policy).
- **Floor changes** — the release notes call them out prominently.
- **A floor is not a validation** — a distribution compiled for API 24 is expected to run on Android 7, but that is a toolchain-contract property until a device says otherwise.

## Not Supported

Deliberate boundaries, not gaps waiting to be filled:

- **Android ABIs other than `arm64-v8a`** — no `armeabi-v7a`, no `x86_64`.
- **16 KiB page-size devices at runtime** — every ELF is built and checked for 16 KiB program-segment alignment, so distributions are statically compatible; running under a 16 KiB kernel is neither supported nor qualified.
- **General `multiprocessing`** — Android's process and IPC restrictions make the general case unsupportable; specific patterns may work and are not promised.
- **Portability or repair of user-built native wheels** — a wheel built on one device against this distribution is not promised to load on another; wheel repair is an external tool's responsibility.
- **APK and JNI packaging** — the distributions are a command-line runtime.
- **Build variants** — no PGO, LTO, BOLT, debug, free-threaded, or JIT build; one build option per provenance is the whole axis.
- **Detached symbols or a separate debug distribution** — the stripped flavor drops them; nothing republishes them.
- **A bundled cross-build NDK, SDK, or sysroot** — the build resolves a pinned NDK and says how to install it; it does not carry one.

## Runtime Contexts

- **Termux on `arm64-v8a`** — the context the distributions are designed for and the one every device qualification runs against.
- **Compiled-in default** — for that reason the flagship build compiles in Termux's CA path, overridable; the time zone path stays at CPython's default.
- **No Termux dependency** — the runtime needs no Termux prefix and links no Termux native library.
- **Other contexts** — an app-UID native shell, `adb shell`, an emulator: neither qualified nor excluded. They may work; nothing is promised.

## Reporting

- **Problems** — the [issue tracker][issues]; state the build option, release tag, archive flavor, Android version, and runtime context.
- **Security** — [`SECURITY.md`](../SECURITY.md), which also says who owns which surface.

[issues]: https://github.com/daylight-00/python-build-standalone-android/issues
