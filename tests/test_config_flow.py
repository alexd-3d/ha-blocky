"""Tests for the config flow and config entry setup."""

from __future__ import annotations

import aiohttp
import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.ha_blocky.const import DOMAIN
from custom_components.ha_blocky.coordinator import BlockyCoordinator

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

BASE_URL = "http://blocky.example:4000"
STATUS_URL = f"{BASE_URL}/api/blocking/status"
GOOD_STATUS = {"enabled": True, "disabledGroups": [], "autoEnableInSec": 0}


async def _start_flow(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    assert set(result["description_placeholders"]) == {
        "example_url",
        "addon_url",
    }
    return result["flow_id"]


async def test_user_flow_creates_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(STATUS_URL, json=GOOD_STATUS)
    flow_id = await _start_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_URL: "  HTTP://Blocky.Example:4000/  "}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Blocky (blocky.example)"
    assert result["data"] == {CONF_URL: BASE_URL}

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.state is ConfigEntryState.LOADED
    assert isinstance(entry.runtime_data.coordinator, BlockyCoordinator)
    assert entry.runtime_data.stats is None


@pytest.mark.parametrize(
    "bad_url",
    [
        "blocky.example:4000",
        "ftp://blocky.example",
        "http://user:secret@blocky:4000",
        "http://blocky.example:4000/api",
        "http://blocky.example:4000/?next=1",
    ],
)
async def test_user_flow_invalid_url(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, bad_url: str
) -> None:
    flow_id = await _start_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_URL: bad_url}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_URL: "invalid_url"}
    assert aioclient_mock.call_count == 0


async def test_user_flow_cannot_connect_then_recovers(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(STATUS_URL, exc=aiohttp.ClientConnectionError())
    flow_id = await _start_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_URL: BASE_URL}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    aioclient_mock.clear_requests()
    aioclient_mock.get(STATUS_URL, json=GOOD_STATUS)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_URL: BASE_URL}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    "kwargs",
    [
        {"text": "<html>router login</html>"},
        {"json": {"enabled": "yes"}},
        {"json": GOOD_STATUS, "status": 503},
    ],
)
async def test_user_flow_invalid_response(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, kwargs: dict
) -> None:
    aioclient_mock.get(STATUS_URL, **kwargs)
    flow_id = await _start_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_URL: BASE_URL}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_response"}


async def test_user_flow_already_configured(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    MockConfigEntry(domain=DOMAIN, data={CONF_URL: BASE_URL}).add_to_hass(hass)
    flow_id = await _start_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_URL: "http://BLOCKY.example:4000/"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert aioclient_mock.call_count == 0


async def test_setup_and_unload_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(STATUS_URL, json=GOOD_STATUS)
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_URL: BASE_URL})
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize(
    "kwargs",
    [
        {"exc": aiohttp.ClientConnectionError()},
        {"exc": TimeoutError()},
        {"text": "not blocky"},
    ],
)
async def test_setup_entry_not_ready(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, kwargs: dict
) -> None:
    aioclient_mock.get(STATUS_URL, **kwargs)
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_URL: BASE_URL})
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_with_tampered_url(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_URL: "http://blocky.example:4000/../evil"}
    )
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert aioclient_mock.call_count == 0
