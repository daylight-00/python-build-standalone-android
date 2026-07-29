# Android Quirks

Where Bionic and Android differ from the POSIX host CPython expects, and what
this project does about each. These are runtime properties: they describe the
distribution you unpack, not the machine that built it.

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

### `default` — a compiled-in trust store

Only the CA half is solved at build time:

```
OpenSSL   --openssldir=/data/data/com.termux/files/usr/etc/tls
```

`--openssldir` is fixed when OpenSSL is compiled, and upstream's
`Android/android.py` downloads prebuilt dependency archives built with OpenSSL's
default:

```
/usr/local/ssl/cert.pem
/usr/local/ssl/certs
```

Neither path exists on Android, which is the root cause of the empty trust
store, and no amount of repackaging can change it afterwards. So `default`
builds all six dependency recipes from source rather than unpacking them — that
one argument is the whole reason. It stays overridable at runtime with
`SSL_CERT_FILE` and `SSL_CERT_DIR`, and it makes the runtime require no Termux
prefix and no Termux native library, which is why it is not named in the
artifact.

**The time zone path is left at CPython's default**, as upstream leaves it.
Termux ships no zoneinfo tree, so compiling in a path to one would name a
directory that does not exist. `zoneinfo` therefore falls back to the `tzdata`
package, exactly as it does on a Linux host with no system zoneinfo installed.
Callers who need time zones install `tzdata`, set `PYTHONTZPATH`, or use the
data product.

An earlier version of this document claimed the source build solved both halves.
It did not: a device found `ZoneInfo("Asia/Seoul")` failing while the
qualification gate passed, because nothing checked it. The gate checks it now,
and only against what a build actually declares.

What the two builds resolve on a device, with nothing set:

| | `default` | `upstream` |
| --- | --- | --- |
| OpenSSL cafile | `…/com.termux/files/usr/etc/tls/cert.pem`, present | `/usr/local/ssl/cert.pem`, absent |
| CA certificates loaded | **119** | **0** |
| Time zone directories present | none | none |

Both figures come from the committed qualification receipts. The trust store is
the whole difference the source build buys, and 119 against 0 is the size of it.

Using Android's own system CA and tz databases belongs to `extended` or beyond,
and is still under research.

## Android adaptations

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


[pbs]: https://github.com/astral-sh/python-build-standalone
[research]: https://github.com/daylight-00/cpython-android-cli
