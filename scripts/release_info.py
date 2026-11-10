"""Validate the release version and extract its changelog section.

Used by the release workflow and by the test suite. Writes ``tag`` and
``prerelease`` to ``$GITHUB_OUTPUT`` and the notes to ``release-notes.md``.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "custom_components" / "ha_blocky" / "manifest.json"
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"

VERSION_RE = re.compile(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+|\.dev\d+)?")
PRERELEASE_RE = re.compile(r"(?:a|b|rc|\.dev)\d+$")


def read_version() -> str:
    """Return the version, checking manifest and pyproject agree."""
    manifest_version = json.loads(MANIFEST.read_text(encoding="utf-8")).get("version")
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project_version = project.get("project", {}).get("version")

    if not isinstance(manifest_version, str) or not manifest_version:
        raise SystemExit("manifest.json does not contain a version")
    if manifest_version != project_version:
        raise SystemExit(
            f"Version mismatch: manifest.json={manifest_version!r}, "
            f"pyproject.toml={project_version!r}"
        )
    if VERSION_RE.fullmatch(manifest_version) is None:
        raise SystemExit(f"Version {manifest_version!r} is not a supported format")
    return manifest_version


def changelog_section(version: str) -> str:
    """Return the changelog text for ``version``."""
    lines = CHANGELOG.read_text(encoding="utf-8").splitlines()
    heading = f"## {version}"
    try:
        start = lines.index(heading) + 1
    except ValueError:
        raise SystemExit(f"CHANGELOG.md has no section {heading!r}") from None
    end = next(
        (i for i in range(start, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    section = "\n".join(lines[start:end]).strip()
    if not section:
        raise SystemExit(f"CHANGELOG.md section {heading!r} is empty")
    return section


def is_prerelease(version: str) -> bool:
    """Return whether ``version`` is an alpha, beta, rc or dev version."""
    return PRERELEASE_RE.search(version) is not None


def main() -> None:
    """Emit release information for the workflow."""
    version = read_version()
    notes = changelog_section(version)

    Path("release-notes.md").write_text(notes + "\n", encoding="utf-8")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"tag=v{version}\n")
            stream.write(f"prerelease={str(is_prerelease(version)).lower()}\n")
    print(f"version={version} prerelease={is_prerelease(version)}")


if __name__ == "__main__":
    main()
