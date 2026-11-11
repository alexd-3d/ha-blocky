"""Serve and register the query log card."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

CARD_FILE = "ha-blocky-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILE}"
CARD_PATH = Path(__file__).parent / "frontend" / CARD_FILE


async def async_register_card(hass: HomeAssistant) -> None:
    """Make the card available to every dashboard.

    The file is served by Home Assistant itself; nothing is loaded from
    outside. The version in the address makes browsers fetch a new copy after
    an update.
    """
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), False)]
    )
    if "frontend" not in hass.config.components:
        return
    from homeassistant.components.frontend import add_extra_js_url

    integration = await async_get_integration(hass, DOMAIN)
    add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")
