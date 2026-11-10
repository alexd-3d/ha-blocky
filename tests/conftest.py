"""Fixtures shared by the test modules."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.engine import URL

from custom_components.ha_blocky import db

from .test_db import make_log


@pytest.fixture
def log_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> URL:
    """A query log on SQLite that the integration is pointed at."""
    url = make_log(tmp_path / "log.db")
    monkeypatch.setattr(db, "build_url", lambda settings: url)
    return url
