"""Service actions for the Blocky DNS integration."""

from __future__ import annotations

from datetime import timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service

from .api import MAX_DISABLE_SECONDS, BlockyError, validate_group_names
from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DURATION,
    ATTR_GROUPS,
    DOMAIN,
    SERVICE_DISABLE_BLOCKING,
)
from .coordinator import BlockyCoordinator

DISABLE_BLOCKING_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_DURATION): cv.positive_time_period,
        vol.Optional(ATTR_GROUPS, default=list): vol.All(cv.ensure_list, [cv.string]),
    }
)


def _get_coordinator(hass: HomeAssistant, call: ServiceCall) -> BlockyCoordinator:
    """Return the coordinator a service call addresses."""
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if entry_id is not None:
        entries = [entry for entry in entries if entry.entry_id == entry_id]
        if not entries:
            raise ServiceValidationError("Blocky config entry not found or not loaded")
    elif len(entries) != 1:
        raise ServiceValidationError(
            "Specify config_entry_id: there is not exactly one loaded Blocky entry"
        )
    return entries[0].runtime_data.coordinator


async def _async_disable_blocking(call: ServiceCall) -> None:
    """Pause blocking for a bounded time, optionally for some groups only."""
    coordinator = _get_coordinator(call.hass, call)

    duration: timedelta = call.data[ATTR_DURATION]
    seconds = int(duration.total_seconds())
    if not 1 <= seconds <= MAX_DISABLE_SECONDS:
        raise ServiceValidationError("Duration must be between 1 second and 24 hours")
    try:
        groups = validate_group_names(call.data[ATTR_GROUPS])
    except ValueError as err:
        raise ServiceValidationError(f"Invalid group name: {err}") from err

    try:
        await coordinator.async_disable_blocking(seconds, groups)
    except BlockyError as err:
        raise HomeAssistantError("Could not pause Blocky blocking") from err


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's service actions (administrators only)."""
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_DISABLE_BLOCKING,
        _async_disable_blocking,
        schema=DISABLE_BLOCKING_SCHEMA,
    )
