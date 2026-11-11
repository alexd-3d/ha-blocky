"""WebSocket commands used by the query log card.

Both commands are restricted to administrators: the query log is the DNS
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
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MAX_LOG_HOURS, MAX_LOG_ROWS
from .coordinator import BlockyConfigEntry
from .db import BlockyDbError
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
    connection.send_result(
        msg["id"],
        {
            "entries": [
                {
                    "entry_id": entry.entry_id,
                    "title": entry.title,
                    "has_query_log": entry.runtime_data.stats is not None,
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
    for row in rows:
        row["zone"] = zone_for_address(row.get("client"), zones)

    connection.send_result(
        msg["id"],
        {
            "rows": rows,
            "has_more": len(rows) == limit,
            "next_before_id": rows[-1]["id"] if rows else None,
        },
    )


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    """Register the WebSocket commands."""
    websocket_api.async_register_command(hass, ws_config)
    websocket_api.async_register_command(hass, ws_query_log)
