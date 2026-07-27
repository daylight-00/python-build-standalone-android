# Device qualification receipts

CI cannot run these distributions — GitHub has no Android runner. The check that
matters most therefore happens on a device, out of band, and its result is
committed here.

```
qualification/<tag>/<triple>[-<build option>].json
```

The release workflow refuses to publish a build unless a receipt here covers
every artifact in the release by SHA-256. A receipt is evidence only for the
bytes it names.

## Producing one

Build the release candidate, then copy `qualify.py` and the archives to the
device:

```console
$ ./build.py --target aarch64-linux-android:upstream --tag 20260727
```

On the device, in Termux:

```console
$ python3 qualify.py \
    cpython-3.14.6+20260727-aarch64-linux-android-upstream-install_only_stripped.tar.gz \
    --also-binds \
        cpython-3.14.6+20260727-aarch64-linux-android-upstream-full.tar.zst \
        cpython-3.14.6+20260727-aarch64-linux-android-upstream-install_only.tar.gz \
    --expected-api 24 \
    -o aarch64-linux-android-upstream.json
```

`qualify.py` needs only the standard library. The archive named first is the one
actually executed — use the flavor the uv catalog points at. The others are
bound by hash so the gate can confirm the whole release was covered.

Commit the receipt under the release tag, then check it from the repository:

```console
$ ./check-qualification.py --target aarch64-linux-android:upstream --tag 20260727
```

## What it checks

| Check | What a failure would mean |
| --- | --- |
| interpreter identity | wrong version, ABI, or platform for this build |
| extension modules | an extension the archive ships cannot be imported |
| `dlopen` of shared libraries | the relative `RUNPATH` does not resolve |
| subprocess | the interpreter cannot re-exec itself |
| relocation | the prefix stops working when moved |
| `pip` | the bundled pip surface is broken |
| `venv` | virtual environments cannot be created from the prefix |

No `LD_LIBRARY_PATH` is set for any of it, so the relative `RUNPATH` has to do
the work on its own. The interpreter is given a caller-owned writable state root
and nothing else inherited from the shell, so a bug cannot hide behind the
device's environment.
