"""WebSocket commands to switch "apply to Blocky" on and to run it.

Administrators only. Neither command is an entity or a service, so an
automation or a non-administrator cannot switch the opt-in or start a run. The
refusals use fixed texts; the card shows its own words for each code.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .apply import APPLY_ERRORS, ApplyError, async_apply, with_auto_apply
from .const import DOMAIN
from .websocket_levels import _entry_of, level_status


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_auto_apply",
        vol.Optional("entry_id"): str,
        vol.Required("enabled"): bool,
    }
)
@websocket_api.require_admin
@callback
def ws_set_auto_apply(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Switch the opt-in to write Blocky's options on or off."""
    entry = _entry_of(hass, connection, msg)
    if entry is None:
        return
    hass.config_entries.async_update_entry(
        entry, options=with_auto_apply(entry.options, msg["enabled"])
    )
    connection.send_result(msg["id"], {"auto_apply": msg["enabled"]})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/apply_now", vol.Optional("entry_id"): str}
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_apply_now(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Write the entries into the Blocky app's options and restart Blocky."""
    entry = _entry_of(hass, connection, msg)
    if entry is None:
        return
    try:
        result = await async_apply(hass, entry)
    except ApplyError as err:
        connection.send_error(msg["id"], err.code, APPLY_ERRORS[err.code])
        return
    connection.send_result(
        msg["id"],
        {
            "result": result,
            "last_apply": entry.runtime_data.last_apply,
            "status": level_status(entry),
        },
    )


@callback
def async_register_apply_commands(hass: HomeAssistant) -> None:
    """Register the two commands."""
    for handler in (ws_set_auto_apply, ws_apply_now):
        websocket_api.async_register_command(hass, handler)
