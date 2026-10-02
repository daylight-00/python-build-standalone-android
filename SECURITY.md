# Security

## Reporting

- **How** — GitHub's [private advisory form][advisory]. Do not open a public issue.
- **Include** — release tag, target, archive flavor, and enough detail to reproduce.

## Ownership

| Surface | Owner | What this project does |
| --- | --- | --- |
| CPython source, CVE response | CPython upstream | consume signed releases, read the release notes |
| The official Android package | Python.org and BeeWare | verify its exact identity, enumerate every packaging change |
| Packaging, loader normalization, launcher, metadata | this project | fix and re-release |
| Release integrity | this project | pinned inputs, reproducible builds, checksums, provenance attestations |

- **CPython fixes** — consumed by rebuilding from the new upstream input, never by patching a distribution in place.
- **Published artifacts** — never mutated. A correction is a new release.

## Verifying a Release

- Every release publishes `SHA256SUMS` beside its archives.
- Every archive carries a build-provenance attestation.

```console
$ sha256sum -c SHA256SUMS --ignore-missing
$ gh attestation verify <archive> --repo daylight-00/python-build-standalone-android
```

[advisory]: https://github.com/daylight-00/python-build-standalone-android/security/advisories/new
