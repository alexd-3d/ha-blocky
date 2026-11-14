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
    ATTR_ASK,
    ATTR_CLIENT,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DOMAIN,
    ATTR_DURATION,
    ATTR_GROUPS,
    ATTR_LIST,
    ATTR_REQUEST_ID,
    DOMAIN,
    EVENT_LIST_CHANGED,
    LEVEL_LOCKDOWN,
    LIST_TYPE_ALLOW,
    LIST_TYPE_DENY,
    REQUEST_ACTION_APPROVE,
    REQUEST_ACTION_BLOCK,
    REQUEST_ACTION_REJECT,
    RULE_LISTS,
    SERVICE_ALLOW_DOMAIN,
    SERVICE_APPROVE_REQUEST,
    SERVICE_BLOCK_DOMAIN,
    SERVICE_BLOCK_REQUEST,
    SERVICE_DISABLE_BLOCKING,
    SERVICE_GET_LIST,
    SERVICE_GET_REQUESTS,
    SERVICE_REJECT_REQUEST,
    SERVICE_REMOVE_DOMAIN,
    SERVICE_ROTATE_LIST_TOKEN,
    SERVICE_SET_CLIENT_ASK,
)
from .coordinator import BlockyConfigEntry
from .levels import apply_options, with_client
from .lists import ListError
from .requests import RequestError, RequestTracker
from .validation import normalize_client

_LIST_NAME = vol.In(tuple(RULE_LISTS))

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
        vol.Required(ATTR_LIST): _LIST_NAME,
        vol.Required(ATTR_DOMAIN): cv.string,
    }
)

GET_LIST_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_LIST): _LIST_NAME,
    }
)

ENTRY_ONLY_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})

_REQUEST_ID = vol.All(cv.string, vol.Length(min=1, max=64))

APPROVE_REQUEST_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_REQUEST_ID): _REQUEST_ID,
    }
)

REQUEST_ID_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_REQUEST_ID): _REQUEST_ID,
    }
)

SET_CLIENT_ASK_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_CLIENT): vol.All(cv.string, vol.Length(max=64)),
        vol.Required(ATTR_ASK): cv.boolean,
    }
)


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
    return {
        "list": name,
        "type": RULE_LISTS[name],
        "entries": entries,
    }


async def _async_rotate_list_token(call: ServiceCall) -> None:
    """Replace the secret in the list URLs."""
    entry = _get_entry(call.hass, call)
    await entry.runtime_data.lists.async_rotate_token()
    _fire_list_changed(call, entry, "rotate_token", "", "")


def _get_tracker(call: ServiceCall) -> tuple[BlockyConfigEntry, RequestTracker]:
    """Return the entry and its request tracker, which needs the query log."""
    entry = _get_entry(call.hass, call)
    tracker = entry.runtime_data.requests
    if tracker is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_query_log"
        )
    return entry, tracker


def _request_failure(err: RequestError) -> ServiceValidationError:
    return ServiceValidationError(translation_domain=DOMAIN, translation_key=err.code)


def _make_resolve_handler(action: str) -> Any:
    async def _async_resolve(call: ServiceCall) -> None:
        _entry, tracker = _get_tracker(call)
        try:
            tracker.async_resolve(call.data[ATTR_REQUEST_ID], action, call.context)
        except RequestError as err:
            raise _request_failure(err) from err

    return _async_resolve


async def _async_get_requests(call: ServiceCall) -> ServiceResponse:
    """Return the requests waiting for a decision."""
    _entry, tracker = _get_tracker(call)
    return {
        "requests": tracker.describe_requests(),
    }


async def _async_set_client_ask(call: ServiceCall) -> None:
    """Switch whether a Lockdown client asks about new domains."""
    entry = _get_entry(call.hass, call)
    address = normalize_client(call.data[ATTR_CLIENT])
    if address is None:
        raise _request_failure(RequestError("invalid_client"))
    if entry.runtime_data.levels.level_of(address) != LEVEL_LOCKDOWN:
        raise _request_failure(RequestError("client_not_lockdown"))
    apply_options(
        call.hass,
        entry,
        with_client(entry.options, address, LEVEL_LOCKDOWN, call.data[ATTR_ASK]),
    )


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
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_APPROVE_REQUEST,
        _make_resolve_handler(REQUEST_ACTION_APPROVE),
        schema=APPROVE_REQUEST_SCHEMA,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_REJECT_REQUEST,
        _make_resolve_handler(REQUEST_ACTION_REJECT),
        schema=REQUEST_ID_SCHEMA,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_BLOCK_REQUEST,
        _make_resolve_handler(REQUEST_ACTION_BLOCK),
        schema=REQUEST_ID_SCHEMA,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_GET_REQUESTS,
        _async_get_requests,
        schema=ENTRY_ONLY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_SET_CLIENT_ASK,
        _async_set_client_ask,
        schema=SET_CLIENT_ASK_SCHEMA,
    )
