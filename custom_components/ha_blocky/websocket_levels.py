"""WebSocket commands for clients, levels and rules, used by the card.

Every command is restricted to administrators and validated on the server:
client addresses are normalised IP addresses, levels come from a fixed set,
list names from the fixed rule lists, group names from the group name
validator. The number of clients is capped. Nothing here reloads the entry.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

from .client_names import client_name_map, get_client_names
from .const import (
    ATTR_ACTION,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DOMAIN,
    ATTR_LIST,
    DEFAULT_BASE_GROUPS,
    DEFAULT_NOTIFY,
    DOMAIN,
    EVENT_LIST_CHANGED,
    EXACT_ONLY_LISTS,
    LEVEL_LOCKDOWN,
    LEVELS,
    LIST_LOCKDOWN_ALLOW,
    LIST_RESTRICTED_DENY,
    LIST_UNFILTERED_EMPTY,
    RULE_LISTS,
)
from .coordinator import BlockyConfigEntry
from .db import BlockyDbError
from .levels import (
    LevelError,
    apply_options,
    base_groups_saved,
    render_block,
    with_base_groups,
    with_client,
    with_notify,
)
from .lists import ListError
from .validation import normalize_client

# How far back the client list looks for clients seen in the query log.
SEEN_WINDOW: Final = timedelta(days=7)
MAX_CLIENTS_LISTED: Final = 200
MAX_RULES_LISTED: Final = 500

# The served list each level's group is built from.
LEVEL_LIST: Final = {
    "restricted": LIST_RESTRICTED_DENY,
    "lockdown": LIST_LOCKDOWN_ALLOW,
    "unfiltered": LIST_UNFILTERED_EMPTY,
}

# Fixed texts for the reasons a change is refused (never contain input).
LEVEL_ERRORS: Final = {
    "invalid_client": "The client is not a valid IP address.",
    "invalid_level": "Not a known level.",
    "too_many_clients": "Too many clients have a level already.",
    "invalid_base_groups": "Use 1 to 16 list group names of letters, digits, _ - .",
    "reserved_group": "That name is used for a level; choose another list group.",
    "duplicate_group": "Every list group may be named only once.",
    "invalid_notify": "Not a valid notification setting.",
}


def _client_address(value: Any) -> str:
    """Accept an IP address only and return its canonical text."""
    address = normalize_client(value)
    if address is None:
        raise vol.Invalid("not an IP address")
    return address


def _entry_of(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> BlockyConfigEntry | None:
    """Find the loaded entry a command addresses, or answer with an error."""
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    entry_id = msg.get("entry_id")
    if entry_id is not None:
        entries = [entry for entry in entries if entry.entry_id == entry_id]
    if len(entries) != 1:
        connection.send_error(msg["id"], "entry_not_found", "Blocky entry not found")
        return None
    return entries[0]


def _snapshot(entry: BlockyConfigEntry) -> dict[str, Any]:
    levels = entry.runtime_data.levels
    return {
        "base_groups": list(levels.base_groups),
        "clients": {
            address: config.level for address, config in levels.clients.items()
        },
    }


def count_changes(current: dict[str, Any], applied: dict[str, Any] | None) -> int:
    """Count the changes between what is applied and the current levels."""
    if applied is None:
        applied = {"base_groups": list(DEFAULT_BASE_GROUPS), "clients": {}}
    changes = sum(
        1
        for address in set(current["clients"]) | set(applied["clients"])
        if current["clients"].get(address) != applied["clients"].get(address)
    )
    if current["base_groups"] != applied["base_groups"]:
        changes += 1
    return changes


def level_status(entry: BlockyConfigEntry) -> dict[str, Any]:
    """Describe whether Blocky has the current configuration (applied) or not.

    Applied: every served list was fetched with the current revision, or there
    is nothing that differs from the last applied state. Live-unverified (a):
    that Blocky fetches again after a restart and keeps the query string.
    """
    data = entry.runtime_data
    rev = data.levels.rev
    fetched = {name: data.lists.fetched(name) for name in LEVEL_LIST.values()}
    current_fetched = {
        name: value is not None and value[0] == rev for name, value in fetched.items()
    }
    snapshot = _snapshot(entry)
    if all(current_fetched.values()):
        data.lists.set_applied(snapshot)
    waiting = (
        0
        if all(current_fetched.values())
        else count_changes(snapshot, data.lists.applied)
    )
    return {
        "rev": rev,
        "applied": waiting == 0,
        "waiting": waiting,
        "fetched_since_start": any(value is not None for value in fetched.values()),
        "lists": {
            level: {
                "fetched": fetched[name] is not None,
                "current": current_fetched[name],
            }
            for level, name in LEVEL_LIST.items()
        },
    }


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/levels", vol.Optional("entry_id"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_levels(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Describe the clients, the levels, the notifications and the status."""
    entry = _entry_of(hass, connection, msg)
    if entry is None:
        return
    data = entry.runtime_data
    levels = data.levels
    seen: dict[str, int] = {}
    log_ok: bool | None = None
    if data.stats is not None:
        log_ok = data.stats.last_update_success
        since = (dt_util.utcnow() - SEEN_WINDOW).replace(tzinfo=None)
        try:
            counts = await hass.async_add_executor_job(
                data.stats.database.client_counts, since
            )
        except BlockyDbError:
            log_ok = False
        else:
            for address, queries, _blocked in counts:
                key = normalize_client(address)
                if key is not None:
                    seen[key] = seen.get(key, 0) + queries
    # Clients with a level or a manual name are always listed, also when the
    # log has not seen them lately. Nothing is stored for a client seen for the
    # first time: the list is derived on every call.
    client_names = get_client_names(hass)
    manual = client_names.manual_names() if client_names is not None else {}
    for address in (*levels.clients, *manual):
        seen.setdefault(address, 0)
    names = client_name_map(hass)
    clients = []
    for address, queries in sorted(seen.items(), key=lambda item: (-item[1], item[0])):
        config = levels.clients.get(address)
        name = names.get(address)
        clients.append(
            {
                "address": address,
                "client_name": name,
                # "manual" is editable; "device" comes from a device tracker.
                "name_source": (
                    None
                    if name is None
                    else "manual"
                    if address in manual
                    else "device"
                ),
                "level": config.level if config else "standard",
                "ask": bool(config and config.ask),
                "queries": queries,
            }
        )
    # A client with a level or a manual name is always listed, even beyond the
    # cap; the others fill what is left of it.
    pinned: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []
    for item in clients:
        is_pinned = item["level"] != "standard" or item["address"] in manual
        (pinned if is_pinned else others).append(item)
    clients = pinned + others[: max(0, MAX_CLIENTS_LISTED - len(pinned))]
    connection.send_result(
        msg["id"],
        {
            "entry_id": entry.entry_id,
            "base_groups": list(levels.base_groups),
            # False while the list groups were never saved: the built-in
            # default may not match the names used in Blocky.
            "base_groups_saved": base_groups_saved(entry.options),
            "notify": dict(levels.notify),
            "clients": clients,
            "status": level_status(entry),
            "setup": {
                "api_ok": data.coordinator.last_update_success,
                "log_ok": log_ok,
            },
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_client_level",
        vol.Optional("entry_id"): str,
        vol.Required("client"): _client_address,
        vol.Required("level"): vol.In(LEVELS),
        vol.Optional("ask"): bool,
    }
)
@websocket_api.require_admin
@callback
def ws_set_client_level(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Give a client a level (Standard removes its entry); Lockdown may ask."""
    entry = _entry_of(hass, connection, msg)
    if entry is None:
        return
    existing = entry.runtime_data.levels.clients.get(msg["client"])
    ask = msg.get("ask")
    if ask is None:
        ask = existing.ask if existing and existing.level == LEVEL_LOCKDOWN else True
    try:
        new_options = with_client(entry.options, msg["client"], msg["level"], ask)
    except LevelError as err:
        connection.send_error(msg["id"], err.code, LEVEL_ERRORS.get(err.code, ""))
        return
    apply_options(hass, entry, new_options)
    connection.send_result(
        msg["id"], {"status": level_status(entry), "client": msg["client"]}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_base_groups",
        vol.Optional("entry_id"): str,
        vol.Required("groups"): list,
    }
)
@websocket_api.require_admin
@callback
def ws_set_base_groups(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set the list groups that make up the Standard level."""
    entry = _entry_of(hass, connection, msg)
    if entry is None:
        return
    try:
        new_options = with_base_groups(entry.options, msg["groups"])
    except LevelError as err:
        connection.send_error(msg["id"], err.code, LEVEL_ERRORS.get(err.code, ""))
        return
    apply_options(hass, entry, new_options)
    connection.send_result(
        msg["id"],
        {
            "base_groups": list(entry.runtime_data.levels.base_groups),
            "status": level_status(entry),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_notify",
        vol.Optional("entry_id"): str,
        vol.Required("level"): vol.In(tuple(DEFAULT_NOTIFY)),
        vol.Required("enabled"): bool,
    }
)
@websocket_api.require_admin
@callback
def ws_set_notify(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Switch the new-domain notifications of Restricted or Lockdown on or off."""
    entry = _entry_of(hass, connection, msg)
    if entry is None:
        return
    try:
        new_options = with_notify(entry.options, msg["level"], msg["enabled"])
    except LevelError as err:
        connection.send_error(msg["id"], err.code, LEVEL_ERRORS.get(err.code, ""))
        return
    apply_options(hass, entry, new_options)
    connection.send_result(
        msg["id"], {"notify": dict(entry.runtime_data.levels.notify)}
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/get_block", vol.Optional("entry_id"): str}
)
@websocket_api.require_admin
@callback
def ws_get_block(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Render the entries to paste into Blocky's configuration.

    The text holds the secret list token: it goes to administrators only.
    """
    entry = _entry_of(hass, connection, msg)
    if entry is None:
        return
    data = entry.runtime_data
    try:
        base = get_url(hass, allow_external=False, allow_cloud=False, allow_ip=True)
    except NoURLAvailableError:
        base = ""
    rev = data.levels.rev
    urls = {
        name: f"{base}{data.lists.path(name)}?r={rev}" for name in LEVEL_LIST.values()
    }
    block = render_block(data.levels.base_groups, data.levels.clients, urls)
    connection.send_result(
        msg["id"],
        {
            "rev": rev,
            "base_known": bool(base),
            "client_count": len(data.levels.clients),
            **block,
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/rules", vol.Optional("entry_id"): str}
)
@websocket_api.require_admin
@callback
def ws_rules(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List the entries of the four rule lists."""
    entry = _entry_of(hass, connection, msg)
    if entry is None:
        return
    lists = entry.runtime_data.lists
    connection.send_result(
        msg["id"],
        {
            "lists": [
                {
                    "name": name,
                    "type": list_type,
                    "exact_only": name in EXACT_ONLY_LISTS,
                    "total": lists.count(name),
                    "entries": lists.entries(name)[:MAX_RULES_LISTED],
                }
                for name, list_type in RULE_LISTS.items()
            ]
        },
    )


def _fire_list_changed(
    hass: HomeAssistant,
    entry: BlockyConfigEntry,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    action: str,
    name: str,
    domain: str,
) -> None:
    hass.bus.async_fire(
        EVENT_LIST_CHANGED,
        {
            ATTR_CONFIG_ENTRY_ID: entry.entry_id,
            ATTR_ACTION: action,
            ATTR_LIST: name,
            ATTR_DOMAIN: domain,
        },
        context=connection.context(msg),
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/rules_add",
        vol.Optional("entry_id"): str,
        vol.Required("list"): vol.In(tuple(RULE_LISTS)),
        vol.Required("domain"): vol.All(str, vol.Length(min=1, max=260)),
    }
)
@websocket_api.require_admin
@callback
def ws_rules_add(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Add a domain to a rule list (the Lockdown list refuses wildcards)."""
    entry = _entry_of(hass, connection, msg)
    if entry is None:
        return
    try:
        added = entry.runtime_data.lists.async_add(
            msg["list"], msg["domain"], RULE_LISTS[msg["list"]]
        )
    except ListError as err:
        connection.send_error(msg["id"], "list_error", str(err))
        return
    if added is not None:
        _fire_list_changed(hass, entry, connection, msg, "add", msg["list"], added)
    connection.send_result(msg["id"], {"domain": added, "added": added is not None})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/rules_remove",
        vol.Optional("entry_id"): str,
        vol.Required("list"): vol.In(tuple(RULE_LISTS)),
        vol.Required("domain"): vol.All(str, vol.Length(min=1, max=260)),
    }
)
@websocket_api.require_admin
@callback
def ws_rules_remove(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove a domain from a rule list."""
    entry = _entry_of(hass, connection, msg)
    if entry is None:
        return
    try:
        removed = entry.runtime_data.lists.async_remove(msg["list"], msg["domain"])
    except ListError as err:
        connection.send_error(msg["id"], "list_error", str(err))
        return
    if removed is not None:
        _fire_list_changed(hass, entry, connection, msg, "remove", msg["list"], removed)
    connection.send_result(
        msg["id"], {"domain": removed, "removed": removed is not None}
    )


@callback
def async_register_level_commands(hass: HomeAssistant) -> None:
    """Register the commands of clients, levels and rules."""
    for handler in (
        ws_levels,
        ws_set_client_level,
        ws_set_base_groups,
        ws_set_notify,
        ws_get_block,
        ws_rules,
        ws_rules_add,
        ws_rules_remove,
    ):
        websocket_api.async_register_command(hass, handler)
