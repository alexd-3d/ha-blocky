"""Tests for the sidebar panel: registration, removal and the option."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.components import frontend
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.ha_blocky.const import (
    CONF_SHOW_IN_SIDEBAR,
    DOMAIN,
    PANEL_ELEMENT,
    PANEL_URL_PATH,
)
from custom_components.ha_blocky.frontend import (
    CARD_URL,
    PANEL_URL,
    async_register_panel,
    async_remove_panel,
)

from .test_stats import open_options_step

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

BASE_URL = "http://blocky.example:4000"
STATUS_URL = f"{BASE_URL}/api/blocking/status"
ENABLED = {"enabled": True, "disabledGroups": [], "autoEnableInSec": 0}


@pytest.fixture
async def with_frontend(hass: HomeAssistant) -> None:
    """Make Home Assistant look as if the frontend is set up.

    The real component needs the hass_frontend package, which the test
    environment does not have; the panel and extra module registries are all
    the integration touches.
    """
    hass.config.components.add("frontend")
    hass.data[frontend.DATA_EXTRA_MODULE_URL] = frontend.UrlManager(
        lambda change, url: None, []
    )


async def _add_entry(
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


def _panel(hass: HomeAssistant) -> Any:
    return hass.data.get(frontend.DATA_PANELS, {}).get(PANEL_URL_PATH)


@pytest.mark.usefixtures("with_frontend")
async def test_panel_is_registered_for_administrators(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _add_entry(hass, aioclient_mock)

    panel = _panel(hass)
    assert panel is not None
    assert panel.require_admin is True
    assert panel.component_name == "custom"
    assert panel.sidebar_title == "HA-Blocky"
    custom = panel.config["_panel_custom"]
    assert custom["name"] == PANEL_ELEMENT
    assert custom["module_url"].startswith(f"{PANEL_URL}?v=")
    assert "js_url" not in custom
    assert custom["embed_iframe"] is False
    assert custom["trust_external"] is False
    # The card is still offered to dashboards.
    assert any(
        url.startswith(f"{CARD_URL}?v=")
        for url in hass.data[frontend.DATA_EXTRA_MODULE_URL].urls
    )


@pytest.mark.usefixtures("with_frontend")
async def test_the_option_turns_the_panel_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _add_entry(hass, aioclient_mock, {CONF_SHOW_IN_SIDEBAR: False})

    assert _panel(hass) is None


@pytest.mark.usefixtures("with_frontend")
async def test_panel_is_removed_with_the_last_entry_and_back_on_setup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    first = await _add_entry(hass, aioclient_mock)
    second = await _add_entry(hass, aioclient_mock)
    assert _panel(hass) is not None

    assert await hass.config_entries.async_unload(first.entry_id)
    assert _panel(hass) is not None

    assert await hass.config_entries.async_unload(second.entry_id)
    assert _panel(hass) is None

    # Setting up again (a reload) registers it again without an error.
    assert await hass.config_entries.async_setup(first.entry_id)
    await hass.async_block_till_done()
    assert _panel(hass) is not None
    assert await hass.config_entries.async_reload(first.entry_id)
    await hass.async_block_till_done()
    assert _panel(hass) is not None


@pytest.mark.usefixtures("with_frontend")
async def test_an_entry_without_the_panel_does_not_keep_it_alive(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    wants = await _add_entry(hass, aioclient_mock)
    await _add_entry(hass, aioclient_mock, {CONF_SHOW_IN_SIDEBAR: False})
    assert _panel(hass) is not None

    assert await hass.config_entries.async_unload(wants.entry_id)

    assert _panel(hass) is None


@pytest.mark.usefixtures("with_frontend")
async def test_registering_twice_does_not_raise(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _add_entry(hass, aioclient_mock)

    await async_register_panel(hass)
    await async_register_panel(hass)
    assert _panel(hass) is not None

    async_remove_panel(hass)
    async_remove_panel(hass)
    assert _panel(hass) is None


@pytest.mark.usefixtures("with_frontend")
async def test_saving_the_option_reloads_and_moves_the_panel(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _add_entry(hass, aioclient_mock)
    assert _panel(hass) is not None

    result = await open_options_step(hass, entry, "sidebar")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "sidebar"
    suggested = {
        str(key): key.description.get("suggested_value")
        for key in result["data_schema"].schema
    }
    assert suggested == {CONF_SHOW_IN_SIDEBAR: True}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SHOW_IN_SIDEBAR: False}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SHOW_IN_SIDEBAR] is False
    assert _panel(hass) is None

    result = await open_options_step(hass, entry, "sidebar")
    suggested = {
        str(key): key.description.get("suggested_value")
        for key in result["data_schema"].schema
    }
    assert suggested == {CONF_SHOW_IN_SIDEBAR: False}
    await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SHOW_IN_SIDEBAR: True}
    )
    await hass.async_block_till_done()
    assert _panel(hass) is not None


async def test_the_option_keeps_the_other_options(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _add_entry(hass, aioclient_mock, {"report_existing_domains": True})

    result = await open_options_step(hass, entry, "sidebar")
    await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SHOW_IN_SIDEBAR: False}
    )
    await hass.async_block_till_done()

    assert entry.options == {
        "report_existing_domains": True,
        CONF_SHOW_IN_SIDEBAR: False,
    }


async def test_without_the_frontend_nothing_is_registered_and_nothing_fails(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    assert "frontend" not in hass.config.components

    entry = await _add_entry(hass, aioclient_mock)

    assert frontend.DATA_PANELS not in hass.data
    assert await hass.config_entries.async_unload(entry.entry_id)
