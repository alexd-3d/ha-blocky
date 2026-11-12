"""Tests for the configurable update intervals."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from sqlalchemy.engine import URL

from custom_components.ha_blocky.const import (
    CONF_DB_HOST,
    CONF_STATS_INTERVAL,
    CONF_STATUS_INTERVAL,
    CONF_TOPS_INTERVAL,
    DOMAIN,
    INTERVALS,
)
from custom_components.ha_blocky.intervals import interval, interval_seconds

from .test_stats import DB_OPTIONS, open_options_step

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

BASE_URL = "http://blocky.example:4000"
STATUS_URL = f"{BASE_URL}/api/blocking/status"
ENABLED = {"enabled": True, "disabledGroups": [], "autoEnableInSec": 0}

DEFAULTS = {
    CONF_STATUS_INTERVAL: 30,
    CONF_STATS_INTERVAL: 60,
    CONF_TOPS_INTERVAL: 300,
}


async def _setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    aioclient_mock.get(STATUS_URL, json=ENABLED)
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_URL: BASE_URL}, options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# --- Reading stored values --------------------------------------------------


def test_defaults() -> None:
    assert {key: spec.default for key, spec in INTERVALS.items()} == DEFAULTS
    assert {key: interval_seconds({}, key) for key in INTERVALS} == DEFAULTS


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (10, 10),
        (600, 600),
        (45.0, 45),
        (9, 30),
        (601, 30),
        (0, 30),
        (-5, 30),
        (45.5, 30),
        (True, 30),
        ("15", 30),
        (None, 30),
        ([15], 30),
    ],
)
def test_stored_interval_is_validated(value: Any, expected: int) -> None:
    options = {CONF_STATUS_INTERVAL: value}

    assert interval_seconds(options, CONF_STATUS_INTERVAL) == expected
    assert interval(options, CONF_STATUS_INTERVAL) == timedelta(seconds=expected)


# --- Coordinators -----------------------------------------------------------


async def test_default_intervals_are_applied(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, log_url: URL
) -> None:
    entry = await _setup(hass, aioclient_mock, DB_OPTIONS)

    data = entry.runtime_data
    assert data.coordinator.update_interval == timedelta(seconds=30)
    assert data.stats.update_interval == timedelta(seconds=60)
    assert data.stats.tops_interval == timedelta(seconds=300)


async def test_stored_intervals_are_applied(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, log_url: URL
) -> None:
    entry = await _setup(
        hass,
        aioclient_mock,
        {
            **DB_OPTIONS,
            CONF_STATUS_INTERVAL: 15,
            CONF_STATS_INTERVAL: 120,
            CONF_TOPS_INTERVAL: 60,
        },
    )

    data = entry.runtime_data
    assert data.coordinator.update_interval == timedelta(seconds=15)
    assert data.stats.update_interval == timedelta(seconds=120)
    assert data.stats.tops_interval == timedelta(seconds=60)


async def test_tampered_intervals_fall_back_to_defaults(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, log_url: URL
) -> None:
    entry = await _setup(
        hass,
        aioclient_mock,
        {
            **DB_OPTIONS,
            CONF_STATUS_INTERVAL: 0,
            CONF_STATS_INTERVAL: "1; DROP",
            CONF_TOPS_INTERVAL: -1,
        },
    )

    data = entry.runtime_data
    assert data.coordinator.update_interval == timedelta(seconds=30)
    assert data.stats.update_interval == timedelta(seconds=60)
    assert data.stats.tops_interval == timedelta(seconds=300)


async def test_changing_the_database_keeps_intervals(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, log_url: URL
) -> None:
    intervals = {**DEFAULTS, CONF_TOPS_INTERVAL: 60}
    entry = await _setup(hass, aioclient_mock, intervals)

    result = await open_options_step(hass, entry, "database")
    await hass.config_entries.options.async_configure(result["flow_id"], DB_OPTIONS)
    await hass.async_block_till_done()
    assert entry.options == {**intervals, **DB_OPTIONS}
    assert entry.runtime_data.stats.tops_interval == timedelta(seconds=60)

    # Switching the query log off again keeps the intervals too.
    result = await open_options_step(hass, entry, "database")
    await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert entry.options == intervals
    assert CONF_DB_HOST not in entry.options
