"""Service actions for the Blocky DNS integration.

Every action is restricted to administrators.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service

from .api import MAX_DISABLE_SECONDS, BlockyError, validate_group_names
from .const import (
    ATTR_ACTION,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DOMAIN,
    ATTR_DURATION,
    ATTR_GROUPS,
    ATTR_LIST,
    DOMAIN,
    EVENT_LIST_CHANGED,
    LIST_TYPE_ALLOW,
    LIST_TYPE_DENY,
    SERVICE_ALLOW_DOMAIN,
    SERVICE_BLOCK_DOMAIN,
    SERVICE_DISABLE_BLOCKING,
    SERVICE_GET_LIST,
    SERVICE_REMOVE_DOMAIN,
    SERVICE_ROTATE_LIST_TOKEN,
)
from .coordinator import BlockyConfigEntry
from .lists import ListError

DISABLE_BLOCKING_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_DURATION): cv.positive_time_period,
        vol.Optional(ATTR_GROUPS, default=list): vol.All(cv.ensure_list, [cv.string]),
    }
)

LIST_ENTRY_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_LIST): cv.string,
        vol.Required(ATTR_DOMAIN): cv.string,
    }
)

GET_LIST_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_LIST): cv.string,
    }
)

ENTRY_ONLY_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})


def _get_entry(hass: HomeAssistant, call: ServiceCall) -> BlockyConfigEntry:
    """Return the loaded config entry a service call addresses."""
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
    return entries[0]


async def _async_disable_blocking(call: ServiceCall) -> None:
    """Pause blocking for a bounded time, optionally for some groups only."""
    coordinator = _get_entry(call.hass, call).runtime_data.coordinator

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


def _fire_list_changed(
    call: ServiceCall, entry: BlockyConfigEntry, action: str, list_name: str, value: str
) -> None:
    """Leave an audit trail of who changed which list."""
    call.hass.bus.async_fire(
        EVENT_LIST_CHANGED,
        {
            ATTR_CONFIG_ENTRY_ID: entry.entry_id,
            ATTR_ACTION: action,
            ATTR_LIST: list_name,
            ATTR_DOMAIN: value,
        },
        context=call.context,
    )


def _make_add_handler(list_type: str) -> Any:
    async def _async_add(call: ServiceCall) -> None:
        entry = _get_entry(call.hass, call)
        try:
            added = entry.runtime_data.lists.async_add(
                call.data[ATTR_LIST], call.data[ATTR_DOMAIN], list_type
            )
        except ListError as err:
            raise ServiceValidationError(str(err)) from err
        if added is not None:
            _fire_list_changed(call, entry, "add", call.data[ATTR_LIST], added)

    return _async_add


async def _async_remove_domain(call: ServiceCall) -> None:
    """Remove a domain from a manual list."""
    entry = _get_entry(call.hass, call)
    try:
        removed = entry.runtime_data.lists.async_remove(
            call.data[ATTR_LIST], call.data[ATTR_DOMAIN]
        )
    except ListError as err:
        raise ServiceValidationError(str(err)) from err
    if removed is not None:
        _fire_list_changed(call, entry, "remove", call.data[ATTR_LIST], removed)


async def _async_get_list(call: ServiceCall) -> ServiceResponse:
    """Return the entries of a manual list."""
    lists = _get_entry(call.hass, call).runtime_data.lists
    name = call.data[ATTR_LIST]
    try:
        entries = lists.entries(name)
    except ListError as err:
        raise ServiceValidationError(str(err)) from err
    definition = lists.definitions[name]
    return {
        "list": name,
        "type": definition.list_type,
        "exact_only": definition.exact_only,
        "entries": entries,
    }


async def _async_rotate_list_token(call: ServiceCall) -> None:
    """Replace the secret in the list URLs."""
    entry = _get_entry(call.hass, call)
    await entry.runtime_data.lists.async_rotate_token()
    _fire_list_changed(call, entry, "rotate_token", "", "")


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
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_ALLOW_DOMAIN,
        _make_add_handler(LIST_TYPE_ALLOW),
        schema=LIST_ENTRY_SCHEMA,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_BLOCK_DOMAIN,
        _make_add_handler(LIST_TYPE_DENY),
        schema=LIST_ENTRY_SCHEMA,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_REMOVE_DOMAIN,
        _async_remove_domain,
        schema=LIST_ENTRY_SCHEMA,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_GET_LIST,
        _async_get_list,
        schema=GET_LIST_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_ROTATE_LIST_TOKEN,
        _async_rotate_list_token,
        schema=ENTRY_ONLY_SCHEMA,
    )
