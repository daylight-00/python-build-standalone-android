# Security

## Reporting

Report a vulnerability through [GitHub's private advisory form][advisory]. Do
not open a public issue for one.

Include the release tag, the target, the archive flavor, and enough detail to
reproduce.

## Ownership

| Surface | Owner | What this project does |
| --- | --- | --- |
| CPython source, CVE response | CPython upstream | consume signed releases, read the release notes |
| The official Android package | Python.org and BeeWare | verify its exact identity, enumerate every packaging change |
| Packaging, loader normalization, launcher, metadata | this project | fix and re-release |
| Release integrity | this project | pinned inputs, reproducible builds, checksums, provenance attestations |

A CPython security release is consumed by rebuilding from the new upstream
input, not by patching a distribution in place. Published artifacts are never
mutated: a correction is a new release, and the superseded one is marked, not
edited.

## Verifying a release

Every release publishes `SHA256SUMS` alongside its archives, and every archive
carries a build-provenance attestation:

```console
$ sha256sum -c SHA256SUMS --ignore-missing
$ gh attestation verify <archive> --repo daylight-00/python-build-standalone-android
```

[advisory]: https://github.com/daylight-00/python-build-standalone-android/security/advisories/new
