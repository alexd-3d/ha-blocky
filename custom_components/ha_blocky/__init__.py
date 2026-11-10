"""Blocky DNS integration for Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    BlockyClient,
    BlockyConnectionError,
    BlockyInvalidUrlError,
    BlockyResponseError,
)

type BlockyConfigEntry = ConfigEntry[BlockyClient]


async def async_setup_entry(hass: HomeAssistant, entry: BlockyConfigEntry) -> bool:
    """Set up Blocky from a config entry."""
    try:
        client = BlockyClient(async_get_clientsession(hass), entry.data[CONF_URL])
    except BlockyInvalidUrlError as err:
        raise ConfigEntryError("Stored Blocky URL is not valid") from err

    try:
        await client.async_get_status()
    except BlockyConnectionError as err:
        raise ConfigEntryNotReady("Blocky is not reachable") from err
    except BlockyResponseError as err:
        raise ConfigEntryNotReady("Blocky returned an unexpected response") from err

    entry.runtime_data = client
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BlockyConfigEntry) -> bool:
    """Unload a config entry."""
    return True
