# Support Scope

## Status

Two releases are published. `20260729` is current and carries both builds;
`20260728` carries `upstream` alone. The earlier one is superseded and left in
place — a published name has to keep serving the bytes it was published with,
because the uv catalog pins them by hash.

Publishing is gated on a device qualification receipt covering every artifact in
the release by SHA-256, and the receipts are committed under
`qualification/<tag>/<build>.json`. A receipt is evidence only for the bytes it
names, so what follows describes the artifacts a release actually shipped rather
than the project in general.

The predecessor research repository qualified equivalent artifacts on real
hardware, but those receipts are bound to bytes produced by a different
toolchain on a different host. They do not carry over.

## Builds

One triple, `aarch64-linux-android`, `arm64-v8a` only.

| Build option | Minimum Android | Where the minimum comes from |
| --- | --- | --- |
| `upstream` | 7.0 (API 24) | inherited from the official Python.org package |
| *(none)* | 14 (API 34) | the last API level that changes the CPython build |

The `extended` build that the [README](../README.md) and
[`design.md`](design.md) describe is planned and unpublished. Nothing here
covers it, and this table gains a row when it ships.

`upstream` is a permanent baseline, not a stepping stone. It exists so there is
always a build whose device coverage is upstream's responsibility rather than
this project's, and it stays as long as the official package does.

Neither minimum is chosen here, which means either can move without a decision
in this repository — if upstream raises its floor, or a future CPython adds a
configure check for a higher-API function. A floor change is called out
prominently in the release notes.

A minimum API is a build floor. A build floor is not a device validation: a
distribution compiled for API 24 is expected to run on Android 7, but that is a
property of the toolchain contract until a device says otherwise.

## Not supported

These are deliberate boundaries, not gaps waiting to be filled:

- **Android ABIs other than `arm64-v8a`.** No `armeabi-v7a`, no `x86_64`.
- **16 KiB page-size devices at runtime.** Every ELF is built and checked for
  16 KiB program-segment alignment, so the distributions are statically
  compatible. That is a static property. Running under a 16 KiB kernel is not
  supported and not qualified.
- **General `multiprocessing`.** Android's process and IPC restrictions make the
  general case unsupportable; specific patterns may work and are not promised.
- **Portability or repair of user-built native wheels.** A wheel built on one
  device against this distribution is not promised to load on another. Wheel
  repair is an external tool's responsibility.
- **APK and JNI packaging.** The distributions are a command-line runtime.

## Runtime contexts

Termux on `arm64-v8a` is the context the distributions are designed for and the
one the release process will qualify against. The flagship build compiles in
Termux's CA and time zone paths as overridable defaults for that reason.

That is a convenience, not a dependency: the runtime needs no Termux prefix and
links no Termux native library. Other Android contexts — an app-UID native
shell, `adb shell`, an emulator — are neither qualified nor excluded. They may
work. They are not checked, so nothing is promised.

## Reporting

Report problems on the [issue tracker][issues]. A useful report states the build
option, the release tag, the archive flavor, the Android version, and the
runtime context.

Security issues follow [`SECURITY.md`](../SECURITY.md).

CPython security fixes are upstream's; this project consumes them by rebuilding
from a new upstream release. The project owns the packaging, the loader
normalization, and the release integrity.

[issues]: https://github.com/daylight-00/python-build-standalone-android/issues
