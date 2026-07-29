"""Reading an artifact name back into what it describes.

    cpython-3.14.6+20260730-aarch64-linux-android-upstream-install_only.tar.gz
            ^version ^tag    ^triple               ^option  ^flavor

The grammar is upstream's — ``generate-version-metadata.py`` parses release
assets with the same shape, and every name this project publishes parses with it.
Reading a name rather than reconstructing one matters for the qualification
receipt: the receipt records the artifact it ran against, so the receipt says
which build and which Python version it covers without depending on whatever the
operator passed to ``-o``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_BUILD_OPTION = "default"

# Flavors longest-first, so `install_only_stripped` is not read as
# `install_only` with a stray suffix.
NAME = re.compile(
    r"^cpython-"
    r"(?P<version>\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?)"
    r"\+(?P<tag>\d+)-"
    r"(?P<triple>[a-z\d_]+-[a-z\d]+-[a-z\d]+)"
    r"(?:-(?P<build_option>[a-z][a-z\d]*))?"
    r"-(?P<flavor>install_only_stripped|install_only|full)"
    r"\.tar\.(?:gz|zst)$"
)


@dataclass(frozen=True)
class ArtifactName:
    """What an artifact's name says about it."""

    version: str
    tag: str
    triple: str
    build_option: str
    flavor: str

    @property
    def artifact_infix(self) -> str:
        """The triple plus the build option, as it appears in a name."""
        if self.build_option == DEFAULT_BUILD_OPTION:
            return self.triple
        return f"{self.triple}-{self.build_option}"


def parse(filename: str) -> ArtifactName | None:
    """Read a name, or ``None`` when it is not one of this project's."""
    match = NAME.match(filename)
    if match is None:
        return None
    return ArtifactName(
        version=match.group("version"),
        tag=match.group("tag"),
        triple=match.group("triple"),
        # The flagship carries no marker, so its absence is what names it.
        build_option=match.group("build_option") or DEFAULT_BUILD_OPTION,
        flavor=match.group("flavor"),
    )


__all__ = ["DEFAULT_BUILD_OPTION", "ArtifactName", "parse"]
