# Device Qualification Receipts

CI has no Android runner, so the check that matters most happens on a device and its result is committed here.

```
qualification/<tag>/cpython-<version>-<triple>[-<build option>].json
```

- **Gate** — the release workflow refuses to publish a build unless a receipt here covers every artifact in the release by SHA-256, or the release is made [without one](../docs/technotes.md#releasing-without-one) and says so.
- **Binding** — a receipt is evidence only for the bytes it names.
- **Lookup** — the gate finds a receipt by the artifact it records having run against, not by filename, so a receipt cannot claim a build by being named after one. The name mirrors the artifact stem, minus the tag the directory carries.
- **Unreleased candidates** — a tag here may hold receipts for bytes that were never released. They stay valid for whatever tag those bytes are published under; the tag is not inside the archive.

## Producing One

1. Build the release candidate for each build option.
2. Copy `qualify.py` and the archives to the device. It needs only the standard library.
3. Run it once per build, in Termux. The archive named first is the one executed; use the flavor the uv catalog points at. The rest are bound by hash.

```console
$ ./build.py --target aarch64-linux-android --tag <tag>
$ ./build.py --target aarch64-linux-android:upstream --tag <tag>
```

```console
$ python3 qualify.py \
    cpython-<version>+<tag>-aarch64-linux-android-install_only_stripped.tar.gz \
    --also-binds \
        cpython-<version>+<tag>-aarch64-linux-android-full.tar.zst \
        cpython-<version>+<tag>-aarch64-linux-android-install_only.tar.gz \
    --expected-api 34 --builtin-runtime-data \
    -o cpython-<version>-aarch64-linux-android.json

$ python3 qualify.py \
    cpython-<version>+<tag>-aarch64-linux-android-upstream-install_only_stripped.tar.gz \
    --also-binds \
        cpython-<version>+<tag>-aarch64-linux-android-upstream-full.tar.zst \
        cpython-<version>+<tag>-aarch64-linux-android-upstream-install_only.tar.gz \
    --expected-api 24 \
    -o cpython-<version>-aarch64-linux-android-upstream.json
```

- **Flagship** — compiles its trust store in, so `--builtin-runtime-data` asks it to resolve one with nothing set.
- **Baseline** — gets its certificates from the data track, so it is not asked.

Commit the receipts under the release tag, then check them from the repository:

```console
$ ./check-qualification.py --target aarch64-linux-android --tag <tag>
$ ./check-qualification.py --target aarch64-linux-android:upstream --tag <tag>
```

## What It Checks

| Check | What a failure would mean |
| --- | --- |
| interpreter identity | wrong version, ABI, or platform for this build |
| extension modules | a module `configure` said it built is missing or will not import |
| `dlopen` of shared libraries | the relative `RUNPATH` does not resolve |
| subprocess | the interpreter cannot re-exec itself |
| relocation | the prefix stops working when moved |
| `pip` | the bundled pip surface is broken |
| `venv` | virtual environments cannot be created from the prefix |
| runtime data | a trust store or time zone path the build compiled in does not resolve |

- **Runtime data** — held to exactly what `ci-targets.yaml` says the build compiled in: a declared `openssldir` must resolve certificates, and a build with no time zone path is not asked for zones.
- **Environment** — no `LD_LIBRARY_PATH`, so the relative `RUNPATH` does the work alone. The interpreter gets a caller-owned writable state root and nothing else from the shell, so a bug cannot hide behind the device's environment.
