# Support Status

## Status

Two releases are published. `20260729` is current and carries both builds;
`20260728` carries `upstream` alone and is superseded, but left in place; see
[Targets and build options](technotes.md#targets-and-build-options).

Publishing is gated on a device qualification receipt covering every artifact in
the release by SHA-256, and the receipts are committed under
`qualification/<tag>/cpython-<version>-<build>.json`. A receipt is evidence only
for the bytes it names, so what follows describes the artifacts a release
actually shipped rather than the project in general.

A release may also be published without a receipt, so that following a new
CPython does not wait for a device. It is then a prerelease, and the top of its
notes says what it stands on: only the pinned CPython input differing from the
last release a device ran, anything beyond it differing, or no device ever
having run the build. The catalogs keep pointing at the last qualified release,
so `uv python install` never resolves to it. The scope below describes qualified
releases; a prerelease is what its own notes say. See
[releasing without one](technotes.md#releasing-without-one).

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
[`technotes.md`](technotes.md) describe is planned and unpublished. Nothing here
covers it, and this table gains a row when it ships.

`upstream` is a permanent baseline, not a stepping stone. It exists so there is
always a build whose device coverage is upstream's responsibility rather than
this project's, and it stays as long as the official package does.

Neither minimum is chosen here, so either can move without a decision in this
repository: upstream may raise its floor, or a future CPython may add a
configure check for a higher-API function. The release notes call a floor change
out prominently.

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
- **Build variants.** No PGO, LTO, BOLT, debug, free-threaded, or JIT build.
  One build option per provenance is the whole axis.
- **Detached symbols or a separate debug distribution.** The stripped flavor
  drops them; nothing republishes them.
- **A bundled cross-build NDK, SDK, or sysroot.** The build resolves a pinned
  NDK and says how to install it; it does not carry one.

## Runtime contexts

Termux on `arm64-v8a` is the context the distributions are designed for and the
one every device qualification runs against. The flagship build compiles in
Termux's CA and time zone paths as overridable defaults for that reason.

That is a convenience, not a dependency: the runtime needs no Termux prefix and
links no Termux native library. Other Android contexts — an app-UID native
shell, `adb shell`, an emulator — are neither qualified nor excluded. They may
work. They are not checked, so nothing is promised.

## Reporting

Report problems on the [issue tracker][issues]. A useful report states the build
option, the release tag, the archive flavor, the Android version, and the
runtime context.

Security issues follow [`SECURITY.md`](../SECURITY.md), which also says who owns
which surface.

[issues]: https://github.com/daylight-00/python-build-standalone-android/issues
