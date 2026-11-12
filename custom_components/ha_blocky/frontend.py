"""Serve the query log card and register it and its sidebar panel."""

from __future__ import annotations

import hashlib
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util.hass_dict import HassKey

from .const import CONF_SHOW_IN_SIDEBAR, DOMAIN, PANEL_ELEMENT, PANEL_URL_PATH

CARD_FILE = "ha-blocky-card.js"
PANEL_FILE = "ha-blocky-panel.js"
STATIC_URL = f"/{DOMAIN}"
# The address the files are served under: /ha_blocky/<token>, set once at setup.
DATA_FRONTEND_BASE: HassKey[str] = HassKey(f"{DOMAIN}_frontend_base")
# True while the sidebar panel at PANEL_URL_PATH is ours. A panel somebody else
# registered there (for example a dashboard with the same URL path) is never
# touched.
DATA_PANEL_OWNED: HassKey[bool] = HassKey(f"{DOMAIN}_panel_owned")
TOKEN_LENGTH = 12
FRONTEND_DIR = Path(__file__).parent / "frontend"
CARD_PATH = FRONTEND_DIR / CARD_FILE
PANEL_ICON = "mdi:dns"


def frontend_token() -> str:
    """Return a short digest of the names and contents of the frontend files.

    It changes whenever any file changes, so the address of every module
    changes with it and a browser can never mix old and new modules. Blocking
    file access: run it in the executor.
    """
    digest = hashlib.sha256()
    for path in sorted(FRONTEND_DIR.glob("*.js")):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:TOKEN_LENGTH]


async def async_frontend_base(hass: HomeAssistant) -> str:
    """Serve the frontend under its tokenised path (once) and return the path.

    The path is immutable for its content, so it is served with cache headers.
    A second call, for example for another config entry, changes nothing.
    """
    base = hass.data.get(DATA_FRONTEND_BASE)
    if base is not None:
        return base
    token = await hass.async_add_executor_job(frontend_token)
    base = f"{STATIC_URL}/{token}"
    hass.data[DATA_FRONTEND_BASE] = base
    await hass.http.async_register_static_paths(
        [StaticPathConfig(base, str(FRONTEND_DIR), True)]
    )
    return base


async def async_register_card(hass: HomeAssistant) -> None:
    """Make the card available to every dashboard.

    The files are served by Home Assistant itself; nothing is loaded from
    outside. The directory holds only the card's JavaScript modules. The
    modules import each other by relative path, so putting the token in the
    directory versions them all together.
    """
    base = await async_frontend_base(hass)
    if "frontend" not in hass.config.components:
        return
    from homeassistant.components.frontend import add_extra_js_url

    add_extra_js_url(hass, f"{base}/{CARD_FILE}")


async def async_register_panel(hass: HomeAssistant) -> None:
    """Add the administrator-only sidebar panel; a second call changes nothing."""
    if "frontend" not in hass.config.components:
        return
    from homeassistant.components import frontend, panel_custom

    if frontend.async_panel_exists(hass, PANEL_URL_PATH):
        return
    base = await async_frontend_base(hass)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        sidebar_title="HA-Blocky",
        sidebar_icon=PANEL_ICON,
        module_url=f"{base}/{PANEL_FILE}",
        require_admin=True,
    )
    hass.data[DATA_PANEL_OWNED] = True


def async_remove_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel, but only one this integration registered."""
    if "frontend" not in hass.config.components:
        return
    if not hass.data.get(DATA_PANEL_OWNED):
        return
    hass.data[DATA_PANEL_OWNED] = False
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
