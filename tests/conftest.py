"""Fixtures shared by the test modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.typing import WebSocketGenerator
from sqlalchemy.engine import URL

from custom_components.ha_blocky import db

from .test_db import make_log


@pytest.fixture
def log_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> URL:
    """A query log on SQLite that the integration is pointed at."""
    url = make_log(tmp_path / "log.db")
    monkeypatch.setattr(db, "build_url", lambda settings: url)
    return url


@pytest.fixture
def settings_ws(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> Any:
    """Return a coroutine function that sends ha_blocky/set_settings as an admin."""

    async def call(**fields: Any) -> dict[str, Any]:
        client = await hass_ws_client(hass)
        await client.send_json({"id": 1, "type": "ha_blocky/set_settings", **fields})
        response = await client.receive_json()
        await hass.async_block_till_done()
        return response

    return call
