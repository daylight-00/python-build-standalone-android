# Python Standalone Builds for Android

Standalone, redistributable builds of CPython for Android (Bionic), published in
the shape of [astral-sh/python-build-standalone][pbs]. The archive roots, flavor
relationships, `PYTHON.json` metadata, artifact naming, and release model are
upstream's, so a consumer that already understands those distributions needs to
learn nothing new.

These documents follow upstream's own split, and are named for it.

| | |
| --- | --- |
| [running](running.md) | obtaining a distribution and running it |
| [building](building.md) | building, checking, and qualifying one yourself |
| [quirks](quirks.md) | where Android differs from the POSIX host CPython expects |
| [technotes](technotes.md) | why the build is the way it is |
| [distributions](distributions.md) | the archive contract and its metadata |
| [status](status.md) | what is supported, and what deliberately is not |

Design questions are settled in [cpython-android-cli][research] and arrive here
as build recipes; this repository holds the recipes and the release machinery.

[pbs]: https://github.com/astral-sh/python-build-standalone
[research]: https://github.com/daylight-00/cpython-android-cli
