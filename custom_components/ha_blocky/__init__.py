"""Blocky DNS integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from . import db
from .api import BlockyClient, BlockyInvalidUrlError
from .const import (
    CONF_DB_HOST,
    CONF_DB_NAME,
    CONF_DB_PASSWORD,
    CONF_DB_PORT,
    CONF_DB_USERNAME,
    DOMAIN,
)
from .coordinator import BlockyConfigEntry, BlockyCoordinator, BlockyData
from .http import async_register_view
from .lists import STORAGE_VERSION as LISTS_STORAGE_VERSION
from .lists import ListManager, storage_key
from .services import async_setup_services
from .stats import STORAGE_VERSION, BlockyStatsCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration: its service actions and the list endpoint."""
    async_setup_services(hass)
    async_register_view(hass)
    return True


def _database_from_options(entry: BlockyConfigEntry) -> db.QueryLogDatabase | None:
    """Build the query log database from the entry options, if configured."""
    options = entry.options
    if not options.get(CONF_DB_HOST):
        return None
    try:
        settings = db.validate_settings(
            options.get(CONF_DB_HOST),
            options.get(CONF_DB_PORT),
            options.get(CONF_DB_NAME),
            options.get(CONF_DB_USERNAME),
            options.get(CONF_DB_PASSWORD),
        )
        return db.QueryLogDatabase(db.build_url(settings))
    except db.BlockyDbError as err:
        # Control of Blocky must keep working without the query log.
        _LOGGER.error("Query log database is not usable: %s", type(err).__name__)
        return None


async def async_setup_entry(hass: HomeAssistant, entry: BlockyConfigEntry) -> bool:
    """Set up Blocky from a config entry."""
    try:
        client = BlockyClient(async_get_clientsession(hass), entry.data[CONF_URL])
    except BlockyInvalidUrlError as err:
        raise ConfigEntryError("Stored Blocky URL is not valid") from err

    coordinator = BlockyCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    stats: BlockyStatsCoordinator | None = None
    database = _database_from_options(entry)
    if database is not None:
        stats = BlockyStatsCoordinator(hass, entry, database)
        await stats.async_load()
        # A database outage must not stop the entry from loading.
        await stats.async_refresh()

    lists = ListManager(hass, entry)
    await lists.async_load()
    lists.set_refresh(coordinator.async_refresh_lists)

    entry.runtime_data = BlockyData(coordinator=coordinator, lists=lists, stats=stats)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BlockyConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.lists.async_close()
        if entry.runtime_data.stats is not None:
            await entry.runtime_data.stats.async_close()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: BlockyConfigEntry) -> None:
    """Delete everything a removed entry had saved."""
    await Store(
        hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.stats"
    ).async_remove()
    await Store(hass, LISTS_STORAGE_VERSION, storage_key(entry.entry_id)).async_remove()
