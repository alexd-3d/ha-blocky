"""Tests for the sidebar panel: registration, removal and the option."""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.components import frontend
from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
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
    CARD_FILE,
    DATA_FRONTEND_BASE,
    PANEL_FILE,
    async_register_panel,
    async_remove_panel,
)

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
    base = hass.data[DATA_FRONTEND_BASE]
    assert re.fullmatch(r"/ha_blocky/[0-9a-f]{12}", base)
    assert custom["module_url"] == f"{base}/{PANEL_FILE}"
    assert "js_url" not in custom
    assert custom["embed_iframe"] is False
    assert custom["trust_external"] is False
    # The card is still offered to dashboards.
    assert f"{base}/{CARD_FILE}" in hass.data[frontend.DATA_EXTRA_MODULE_URL].urls


@pytest.mark.usefixtures("with_frontend")
async def test_the_option_turns_the_panel_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _add_entry(hass, aioclient_mock, {CONF_SHOW_IN_SIDEBAR: False})

    assert _panel(hass) is None


@pytest.mark.usefixtures("with_frontend")
async def test_a_reload_never_takes_the_panel_away(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The browser leaves a panel that vanishes, even for an instant."""
    entry = await _add_entry(hass, aioclient_mock)
    own = _panel(hass)
    assert own is not None

    with patch(
        "homeassistant.components.frontend.async_remove_panel",
        wraps=frontend.async_remove_panel,
    ) as removed:
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        # A plain unload (what a reload starts with) keeps it as well.
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert _panel(hass) is own
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    removed.assert_not_called()
    assert _panel(hass) is own


@pytest.mark.usefixtures("with_frontend")
async def test_disabling_the_last_entry_removes_the_panel_and_enabling_adds_it(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    first = await _add_entry(hass, aioclient_mock)
    second = await _add_entry(hass, aioclient_mock)
    assert _panel(hass) is not None

    await hass.config_entries.async_set_disabled_by(
        first.entry_id, ConfigEntryDisabler.USER
    )
    await hass.async_block_till_done()
    # Another entry still wants it.
    assert _panel(hass) is not None

    await hass.config_entries.async_set_disabled_by(
        second.entry_id, ConfigEntryDisabler.USER
    )
    await hass.async_block_till_done()
    assert _panel(hass) is None

    await hass.config_entries.async_set_disabled_by(first.entry_id, None)
    await hass.async_block_till_done()
    assert _panel(hass) is not None


@pytest.mark.usefixtures("with_frontend")
async def test_removing_the_last_entry_removes_the_panel(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    first = await _add_entry(hass, aioclient_mock)
    second = await _add_entry(hass, aioclient_mock)

    await hass.config_entries.async_remove(first.entry_id)
    await hass.async_block_till_done()
    assert _panel(hass) is not None

    await hass.config_entries.async_remove(second.entry_id)
    await hass.async_block_till_done()
    assert _panel(hass) is None


@pytest.mark.usefixtures("with_frontend")
async def test_an_entry_without_the_panel_does_not_keep_it_alive(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    wants = await _add_entry(hass, aioclient_mock)
    await _add_entry(hass, aioclient_mock, {CONF_SHOW_IN_SIDEBAR: False})
    assert _panel(hass) is not None

    await hass.config_entries.async_set_disabled_by(
        wants.entry_id, ConfigEntryDisabler.USER
    )
    await hass.async_block_till_done()

    assert _panel(hass) is None


@pytest.mark.usefixtures("with_frontend")
async def test_the_option_off_removes_the_panel_only_when_no_other_entry_wants_it(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, settings_ws: Any
) -> None:
    wants = await _add_entry(hass, aioclient_mock)
    other = await _add_entry(hass, aioclient_mock)
    assert _panel(hass) is not None

    # One entry turns it off: the other still wants it.
    hass.config_entries.async_update_entry(other, options={CONF_SHOW_IN_SIDEBAR: False})
    assert await hass.config_entries.async_reload(other.entry_id)
    await hass.async_block_till_done()
    assert _panel(hass) is not None

    # The last one turns it off: after its reload the panel is gone.
    hass.config_entries.async_update_entry(wants, options={CONF_SHOW_IN_SIDEBAR: False})
    assert await hass.config_entries.async_reload(wants.entry_id)
    await hass.async_block_till_done()
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
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, settings_ws: Any
) -> None:
    entry = await _add_entry(hass, aioclient_mock)
    assert _panel(hass) is not None

    response = await settings_ws(**{CONF_SHOW_IN_SIDEBAR: False})

    assert response["success"]
    assert entry.options[CONF_SHOW_IN_SIDEBAR] is False
    assert _panel(hass) is None

    await settings_ws(**{CONF_SHOW_IN_SIDEBAR: True})
    assert _panel(hass) is not None


async def test_the_option_keeps_the_other_options(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, settings_ws: Any
) -> None:
    entry = await _add_entry(hass, aioclient_mock, {"report_existing_domains": True})

    await settings_ws(**{CONF_SHOW_IN_SIDEBAR: False})

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


def _foreign_panel(hass: HomeAssistant) -> Any:
    """Register somebody else's panel (a dashboard) at our URL path."""
    frontend.async_register_built_in_panel(
        hass,
        "lovelace",
        sidebar_title="Mine",
        sidebar_icon="mdi:home",
        frontend_url_path=PANEL_URL_PATH,
        config={"mode": "storage"},
    )
    panel = _panel(hass)
    assert panel is not None
    return panel


@pytest.mark.usefixtures("with_frontend")
async def test_a_panel_of_somebody_else_is_never_removed_or_replaced(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, settings_ws: Any
) -> None:
    foreign = _foreign_panel(hass)
    entry = await _add_entry(hass, aioclient_mock)
    assert _panel(hass) is foreign

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _panel(hass) is foreign

    # Turning the option off and on again, which reloads, leaves it alone too.
    await settings_ws(**{CONF_SHOW_IN_SIDEBAR: False})
    assert _panel(hass) is foreign
    await settings_ws(**{CONF_SHOW_IN_SIDEBAR: True})
    assert _panel(hass) is foreign

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert _panel(hass) is foreign
    async_remove_panel(hass)
    assert _panel(hass) is foreign


@pytest.mark.usefixtures("with_frontend")
async def test_our_own_panel_is_still_removed_and_added_again(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, settings_ws: Any
) -> None:
    entry = await _add_entry(hass, aioclient_mock)
    own = _panel(hass)
    assert own is not None

    await settings_ws(**{CONF_SHOW_IN_SIDEBAR: False})
    assert _panel(hass) is None
    await settings_ws(**{CONF_SHOW_IN_SIDEBAR: True})
    assert _panel(hass) is not None
    await hass.config_entries.async_set_disabled_by(
        entry.entry_id, ConfigEntryDisabler.USER
    )
    await hass.async_block_till_done()
    assert _panel(hass) is None


@pytest.mark.usefixtures("with_frontend")
async def test_saving_another_option_reloads_without_the_panel_vanishing(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, settings_ws: Any
) -> None:
    """The bug: after Save the browser landed on the default dashboard."""
    entry = await _add_entry(hass, aioclient_mock)
    own = _panel(hass)
    assert own is not None

    with patch(
        "homeassistant.components.frontend.async_remove_panel",
        wraps=frontend.async_remove_panel,
    ) as removed:
        response = await settings_ws(report_existing_domains=True)
        await hass.async_block_till_done()

    assert response["result"]["reloading"] is True
    assert entry.options["report_existing_domains"] is True
    removed.assert_not_called()
    assert _panel(hass) is own
