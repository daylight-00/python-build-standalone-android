# Android Quirks

Where Bionic and Android differ from the POSIX host CPython expects, and what each build does about it. These are runtime properties of the distribution you unpack, not of the machine that built it.

## Runtime Data: CA Certificates and Time Zones

Bionic provides neither of the two things a POSIX CPython assumes:

- **No `/etc/ssl/certs`** — `ssl.create_default_context()` has an empty trust store and every HTTPS call fails, including `pip` and `uv`.
- **No `/usr/share/zoneinfo`** — `zoneinfo.ZoneInfo("Asia/Seoul")` fails; Android's own tz database uses a private merged format CPython cannot read.

### `upstream` — External Data Product

- **External** — the official package is consumed as-is, so no compiled-in default can be changed.
- **Data track** — `certifi` plus a raw `zoneinfo` tree ship on a separate release track, installed into an external `DATA_ROOT` with an atomic `current` symlink and rollback.
- **Separate** — `certifi` and `tzdata` expire on their own schedule; a small data refresh must not require republishing a whole Python archive.
- **Use** — point `SSL_CERT_FILE` and `PYTHONTZPATH` at the installed data; see [Running Distributions](running.md#ca-certificates-and-time-zones).

### `default` — A Compiled-In Trust Store

Only the CA half is solved at build time:

```
OpenSSL   --openssldir=/data/data/com.termux/files/usr/etc/tls
```

- **Why compiled in** — `--openssldir` is fixed when OpenSSL is built, and no repackaging can change it afterward.
- **Upstream's default** — `Android/android.py` downloads prebuilt dependency archives built with `/usr/local/ssl/cert.pem` and `/usr/local/ssl/certs`; neither exists on Android, which is the root cause of the empty trust store.
- **Cost** — `default` builds all six dependency recipes from source rather than unpacking them; the `--openssldir` argument is the whole reason.
- **Overridable** — `SSL_CERT_FILE` and `SSL_CERT_DIR` still apply at runtime.
- **No Termux dependency** — the runtime requires no Termux prefix and no Termux native library, which is why it is not named in the artifact.
- **Time zone path** — left at CPython's default, as upstream leaves it; Termux ships no zoneinfo tree, so compiling in a path would name a directory that does not exist.
- **Time zone fallback** — `zoneinfo` falls back to the `tzdata` package, as on a Linux host with no system zoneinfo. Callers who need time zones install `tzdata`, set `PYTHONTZPATH`, or use the data product.
- **Gate** — the qualification gate checks time zone resolution only against what a build declares.

What the two builds resolve on a device, with nothing set:

| | `default` | `upstream` |
| --- | --- | --- |
| OpenSSL cafile | `…/com.termux/files/usr/etc/tls/cert.pem`, present | `/usr/local/ssl/cert.pem`, absent |
| CA certificates loaded | **119** | **0** |
| Time zone directories present | none | none |

- **Source** — the committed qualification receipts under `qualification/`.
- **Speed** — the source build's other advantage, measured in [the technical notes](technotes.md#why-a-source-build-is-worth-having).
- **System databases** — Android's own CA and tz databases are not used by either build; adopting them is still under research.

## Android Adaptations

- **Interpreter** — the official package is embedding-oriented and ships no executable, so the project supplies the POSIX-equivalent `Programs/python.c` `Py_BytesMain` frontend: no loader bootstrap, no CA policy, no custom argument handling.
- **`DT_RUNPATH`** — every ELF object gets one relative entry, from its own directory to the install `lib` directory.
- **Preserved** — `DT_NEEDED`, SONAME, architecture, ELF kind, and the 16 KiB program-segment alignment contract.
- **Forbidden** — a project-required `LD_LIBRARY_PATH`, and bootstrap self-re-execution.
- **Shell wrappers** — `bin/pip*` and `bin/python3.14-config` locate their sibling interpreter relatively, because a generated console script bakes in the absolute interpreter path and the prefix must stay relocatable.
- **Writable state** — a three-root model:

```
INSTALL_ROOT   immutable, relocatable
DATA_ROOT      independently updateable CA and time zone payloads
STATE_ROOT     caller-owned cache, temp, user-site, and venv state
```
