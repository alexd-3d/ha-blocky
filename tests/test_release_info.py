"""The release metadata must be consistent before anything is merged."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_release_info() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "release_info", ROOT / "scripts" / "release_info.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


release_info = _load_release_info()


def test_versions_agree_and_changelog_has_section() -> None:
    version = release_info.read_version()

    assert release_info.changelog_section(version)


def test_hacs_and_manifest_are_consistent() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "ha_blocky" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))

    assert manifest["domain"] == "ha_blocky"
    assert manifest["name"] == hacs["name"]
    assert manifest["config_flow"] is True
    assert manifest["requirements"] == []


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("0.2.0", False),
        ("1.0.0", False),
        ("0.2.0b1", True),
        ("0.2.0rc2", True),
        ("0.2.0a1", True),
        ("0.2.0.dev3", True),
    ],
)
def test_is_prerelease(version: str, expected: bool) -> None:
    assert release_info.VERSION_RE.fullmatch(version)
    assert release_info.is_prerelease(version) is expected


@pytest.mark.parametrize(
    "version",
    ["1.0", "v1.0.0", "1.0.0-beta", "1.0.0; rm -rf /", "$(id)", "1.0.0\n2.0.0", ""],
)
def test_bad_versions_are_rejected(version: str) -> None:
    assert release_info.VERSION_RE.fullmatch(version) is None
