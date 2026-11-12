"""Serve the query log card and register it and its sidebar panel."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import CONF_SHOW_IN_SIDEBAR, DOMAIN, PANEL_ELEMENT, PANEL_URL_PATH

CARD_FILE = "ha-blocky-card.js"
PANEL_FILE = "ha-blocky-panel.js"
STATIC_URL = f"/{DOMAIN}"
CARD_URL = f"{STATIC_URL}/{CARD_FILE}"
PANEL_URL = f"{STATIC_URL}/{PANEL_FILE}"
FRONTEND_DIR = Path(__file__).parent / "frontend"
CARD_PATH = FRONTEND_DIR / CARD_FILE
PANEL_ICON = "mdi:dns"


async def async_register_card(hass: HomeAssistant) -> None:
    """Make the card available to every dashboard.

    The files are served by Home Assistant itself; nothing is loaded from
    outside. The directory holds only the card's JavaScript modules. The
    version in the address makes browsers fetch a new copy of the entry file
    after an update.
    """
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), False)]
    )
    if "frontend" not in hass.config.components:
        return
    from homeassistant.components.frontend import add_extra_js_url

    integration = await async_get_integration(hass, DOMAIN)
    add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")


async def async_register_panel(hass: HomeAssistant) -> None:
    """Add the administrator-only sidebar panel; a second call changes nothing."""
    if "frontend" not in hass.config.components:
        return
    from homeassistant.components import frontend, panel_custom

    if frontend.async_panel_exists(hass, PANEL_URL_PATH):
        return
    integration = await async_get_integration(hass, DOMAIN)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        sidebar_title="HA-Blocky",
        sidebar_icon=PANEL_ICON,
        module_url=f"{PANEL_URL}?v={integration.version}",
        require_admin=True,
    )


def async_remove_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel; nothing happens when there is none."""
    if "frontend" not in hass.config.components:
        return
    from homeassistant.components import frontend

    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)


def wants_panel(hass: HomeAssistant, *, excluding: str | None = None) -> bool:
    """Return whether a loaded entry (other than ``excluding``) shows the panel."""
    return any(
        entry.entry_id != excluding
        and entry.state is ConfigEntryState.LOADED
        and entry.options.get(CONF_SHOW_IN_SIDEBAR, True) is True
        for entry in hass.config_entries.async_entries(DOMAIN)
    )
