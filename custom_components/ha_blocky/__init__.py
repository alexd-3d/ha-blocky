"""Blocky DNS integration for Home Assistant."""

from __future__ import annotations

from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import BlockyClient, BlockyInvalidUrlError
from .const import DOMAIN
from .coordinator import BlockyConfigEntry, BlockyCoordinator
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration: register its service actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BlockyConfigEntry) -> bool:
    """Set up Blocky from a config entry."""
    try:
        client = BlockyClient(async_get_clientsession(hass), entry.data[CONF_URL])
    except BlockyInvalidUrlError as err:
        raise ConfigEntryError("Stored Blocky URL is not valid") from err

    coordinator = BlockyCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BlockyConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
