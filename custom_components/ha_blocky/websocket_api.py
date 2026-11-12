"""WebSocket commands used by the query log card.

All commands are restricted to administrators: the query log is the DNS
history of everyone on the network.
"""

from __future__ import annotations

from datetime import timedelta
from functools import partial
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from .client_names import (
    ClientNameError,
    client_name_map,
    get_client_names,
)
from .const import (
    DASHBOARD_PERIODS,
    DASHBOARD_ROWS,
    DOMAIN,
    MAX_LOG_HOURS,
    MAX_LOG_ROWS,
    REQUEST_ACTIONS,
)
from .coordinator import BlockyConfigEntry
from .dashboard import async_dashboard
from .db import BlockyDbError, TopItem
from .requests import RequestError, RequestTracker, normalize_client
from .validation import (
    InvalidClientNameError,
    InvalidDomainError,
    normalize_domain,
    validate_client_name,
)
from .zones import zone_for_address

STATUS_ALL = "all"
STATUS_BLOCKED = "blocked"
STATUS_ALLOWED = "allowed"


def _printable(value: Any) -> str:
    """Accept a short filter text without control characters."""
    if not isinstance(value, str):
        raise vol.Invalid("not a string")
    text = value.strip()
    if any(not char.isprintable() for char in text):
        raise vol.Invalid("control characters are not allowed")
    return text


def _client_address(value: Any) -> str:
    """Accept an IP address only and return its canonical text."""
    address = normalize_client(value)
    if address is None:
        raise vol.Invalid("not an IP address")
    return address


def _plain_domain(value: Any) -> str:
    """Accept one exact domain name (no wildcard) and return its canonical form."""
    try:
        return normalize_domain(value, allow_wildcard=False)
    except InvalidDomainError as err:
        raise vol.Invalid("not a valid domain name") from err


def _loaded_entries(hass: HomeAssistant) -> list[BlockyConfigEntry]:
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/config"})
@websocket_api.require_admin
@callback
def ws_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Describe the configured Blocky instances and their manual lists."""
    registry = er.async_get(hass)
    connection.send_result(
        msg["id"],
        {
            "entries": [
                {
                    "entry_id": entry.entry_id,
                    "title": entry.title,
                    "has_query_log": entry.runtime_data.stats is not None,
                    # The blocking switch the dashboard drives (None if removed).
                    "blocking_entity": registry.async_get_entity_id(
                        "switch", DOMAIN, f"{entry.entry_id}_blocking"
                    ),
                    "lists": [
                        {
                            "name": definition.name,
                            "type": definition.list_type,
                            "exact_only": definition.exact_only,
                        }
                        for definition in entry.runtime_data.lists.definitions.values()
                    ],
                    "zones": [
                        {
                            "name": zone.name,
                            "mode": zone.mode,
                            "lists": list(zone.lists),
                        }
                        for zone in entry.runtime_data.zones.values()
                    ],
                }
                for entry in _loaded_entries(hass)
            ]
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/query_log",
        vol.Optional("entry_id"): str,
        vol.Optional("hours", default=24): vol.All(
            int, vol.Range(min=1, max=MAX_LOG_HOURS)
        ),
        vol.Optional("status", default=STATUS_ALL): vol.In(
            [STATUS_ALL, STATUS_BLOCKED, STATUS_ALLOWED]
        ),
        vol.Optional("client", default=""): vol.All(_printable, vol.Length(max=64)),
        vol.Optional("domain", default=""): vol.All(_printable, vol.Length(max=253)),
        vol.Optional("before_id"): vol.All(int, vol.Range(min=1)),
        vol.Optional("limit", default=50): vol.All(
            int, vol.Range(min=1, max=MAX_LOG_ROWS)
        ),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_query_log(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return one page of the query log, newest first."""
    entries = _loaded_entries(hass)
    entry_id = msg.get("entry_id")
    if entry_id is not None:
        entries = [entry for entry in entries if entry.entry_id == entry_id]
    if len(entries) != 1:
        connection.send_error(msg["id"], "entry_not_found", "Blocky entry not found")
        return
    stats = entries[0].runtime_data.stats
    if stats is None:
        connection.send_error(
            msg["id"], "no_query_log", "No query log database is configured"
        )
        return

    since = (dt_util.utcnow() - timedelta(hours=msg["hours"])).replace(tzinfo=None)
    blocked: bool | None = None
    if msg["status"] == STATUS_BLOCKED:
        blocked = True
    elif msg["status"] == STATUS_ALLOWED:
        blocked = False
    limit: int = msg["limit"]

    try:
        rows = await hass.async_add_executor_job(
            partial(
                stats.database.query_log,
                since=since,
                client=msg["client"] or None,
                domain=msg["domain"] or None,
                blocked=blocked,
                before_id=msg.get("before_id"),
                limit=limit,
            )
        )
    except BlockyDbError:
        connection.send_error(
            msg["id"], "database_error", "The query log database did not answer"
        )
        return

    zones = entries[0].runtime_data.zones
    names = client_name_map(hass)
    for row in rows:
        row["zone"] = zone_for_address(row.get("client"), zones)
        address = normalize_client(row.get("client"))
        row["client_name"] = names.get(address) if address else None

    connection.send_result(
        msg["id"],
        {
            "rows": rows,
            "has_more": len(rows) == limit,
            "next_before_id": rows[-1]["id"] if rows else None,
        },
    )


def _tracker_of(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> tuple[BlockyConfigEntry, RequestTracker] | None:
    """Find the entry and tracker a command addresses, or answer with an error."""
    entries = _loaded_entries(hass)
    entry_id = msg.get("entry_id")
    if entry_id is not None:
        entries = [entry for entry in entries if entry.entry_id == entry_id]
    if len(entries) != 1:
        connection.send_error(msg["id"], "entry_not_found", "Blocky entry not found")
        return None
    tracker = entries[0].runtime_data.requests
    if tracker is None:
        connection.send_error(
            msg["id"], "no_query_log", "No query log database is configured"
        )
        return None
    return entries[0], tracker


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/requests", vol.Optional("entry_id"): str}
)
@websocket_api.require_admin
@callback
def ws_requests(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List the requests waiting for a decision and the client phases."""
    found = _tracker_of(hass, connection, msg)
    if found is None:
        return
    entry, tracker = found
    connection.send_result(
        msg["id"],
        {
            "entry_id": entry.entry_id,
            "requests": tracker.describe_requests(),
            "clients": tracker.describe_clients(),
            "tracked": tracker.describe_tracked(),
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/overview", vol.Optional("entry_id"): str}
)
@websocket_api.require_admin
@callback
def ws_overview(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the 24 hour top lists and the pending requests for the overview."""
    found = _tracker_of(hass, connection, msg)
    if found is None:
        return
    entry, tracker = found
    stats = entry.runtime_data.stats
    data = stats.data if stats is not None else None
    names = client_name_map(hass)

    def client_item(item: TopItem) -> dict[str, Any]:
        address = normalize_client(item.name)
        return {
            "name": item.name,
            "count": item.count,
            "client_name": names.get(address) if address else None,
        }

    connection.send_result(
        msg["id"],
        {
            "entry_id": entry.entry_id,
            "top_domains": [
                {"name": item.name, "count": item.count}
                for item in (data.top_domains if data else ())
            ],
            "top_blocked_domains": [
                {"name": item.name, "count": item.count}
                for item in (data.top_blocked_domains if data else ())
            ],
            "top_clients": [
                client_item(item) for item in (data.top_clients if data else ())
            ],
            "requests": tracker.describe_requests(),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/dashboard",
        vol.Optional("entry_id"): str,
        vol.Optional("period", default="24h"): vol.In(DASHBOARD_PERIODS),
        vol.Optional("rows", default=10): vol.All(int, vol.In(DASHBOARD_ROWS)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_dashboard(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the aggregates of the dashboard tab for one period (read only)."""
    entries = _loaded_entries(hass)
    entry_id = msg.get("entry_id")
    if entry_id is not None:
        entries = [entry for entry in entries if entry.entry_id == entry_id]
    if len(entries) != 1:
        connection.send_error(msg["id"], "entry_not_found", "Blocky entry not found")
        return
    entry = entries[0]
    integration = await async_get_integration(hass, DOMAIN)
    meta: dict[str, Any] = {
        "version": str(integration.version or ""),
        # Blocky's API client does not read the server version.
        "blocky_version": None,
        "generated_at": dt_util.utcnow().isoformat(timespec="seconds"),
    }
    stats = entry.runtime_data.stats
    if stats is None:
        connection.send_result(
            msg["id"],
            {
                "state": "no_database",
                "period": msg["period"],
                "rows": msg["rows"],
                "meta": meta,
            },
        )
        return

    try:
        shared = await async_dashboard(
            hass, entry.runtime_data, stats.database, msg["period"], msg["rows"]
        )
    except BlockyDbError:
        connection.send_error(
            msg["id"], "database_error", "The query log database did not answer"
        )
        return

    names = client_name_map(hass)
    result = dict(shared)
    result["top_clients"] = [
        {
            "address": item["name"],
            "client_name": names.get(normalize_client(item["name"]) or ""),
            **{key: value for key, value in item.items() if key != "name"},
        }
        for item in shared["top_clients"]
    ]
    meta["generated_at"] = result.pop("generated_at")
    result["meta"] = meta
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/known_domains",
        vol.Optional("entry_id"): str,
        vol.Required("client"): _client_address,
    }
)
@websocket_api.require_admin
@callback
def ws_known_domains(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List the known domains of one tracked client, newest first."""
    found = _tracker_of(hass, connection, msg)
    if found is None:
        return
    _entry, tracker = found
    try:
        result = tracker.describe_known(msg["client"])
    except RequestError as err:
        connection.send_error(msg["id"], err.code, err.message)
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/block_known",
        vol.Optional("entry_id"): str,
        vol.Required("client"): _client_address,
        vol.Required("domain"): _plain_domain,
    }
)
@websocket_api.require_admin
@callback
def ws_block_known(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Block a known domain of a learning-zone client (first deny list)."""
    found = _tracker_of(hass, connection, msg)
    if found is None:
        return
    _entry, tracker = found
    try:
        domain = tracker.async_block_known(
            msg["client"], msg["domain"], connection.context(msg)
        )
    except RequestError as err:
        connection.send_error(msg["id"], err.code, err.message)
        return
    connection.send_result(msg["id"], {"client": msg["client"], "domain": domain})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/resolve_request",
        vol.Optional("entry_id"): str,
        vol.Required("request_id"): vol.All(str, vol.Length(min=1, max=64)),
        vol.Required("action"): vol.In(REQUEST_ACTIONS),
        vol.Optional("list"): vol.All(str, vol.Length(min=1, max=32)),
    }
)
@websocket_api.require_admin
@callback
def ws_resolve_request(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Approve, reject or block one request (single use)."""
    found = _tracker_of(hass, connection, msg)
    if found is None:
        return
    _entry, tracker = found
    try:
        tracker.async_resolve(
            msg["request_id"], msg["action"], msg.get("list"), connection.context(msg)
        )
    except RequestError as err:
        connection.send_error(msg["id"], err.code, err.message)
        return
    connection.send_result(msg["id"], {"requests": tracker.describe_requests()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_client_name",
        vol.Required("ip"): str,
        vol.Optional("name"): vol.Any(str, None),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set_client_name(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Name a client address by hand; an empty or missing name clears it."""
    address = normalize_client(msg["ip"])
    if address is None:
        connection.send_error(msg["id"], "invalid_ip", "Not a valid IP address")
        return
    names = get_client_names(hass)
    if names is None:
        connection.send_error(msg["id"], "not_ready", "Client names are not available")
        return
    raw = msg.get("name")
    name: str | None = None
    if raw is not None and raw != "":
        try:
            name = validate_client_name(raw)
        except InvalidClientNameError:
            connection.send_error(
                msg["id"],
                "invalid_name",
                "The name must be 1 to 64 characters without control characters",
            )
            return
    try:
        stored = await names.async_set(address, name)
    except ClientNameError as err:
        connection.send_error(
            msg["id"], err.code, "Too many client names are stored already"
        )
        return
    connection.send_result(msg["id"], {"ip": address, "name": stored})


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    """Register the WebSocket commands."""
    websocket_api.async_register_command(hass, ws_config)
    websocket_api.async_register_command(hass, ws_query_log)
    websocket_api.async_register_command(hass, ws_requests)
    websocket_api.async_register_command(hass, ws_overview)
    websocket_api.async_register_command(hass, ws_dashboard)
    websocket_api.async_register_command(hass, ws_known_domains)
    websocket_api.async_register_command(hass, ws_block_known)
    websocket_api.async_register_command(hass, ws_resolve_request)
    websocket_api.async_register_command(hass, ws_set_client_name)
