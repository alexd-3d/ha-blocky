"""Diagnostics for the Blocky DNS integration.

Addresses, credentials, domain names and client addresses are left out or
redacted: a diagnostics file is meant to be shared.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant

from .const import CONF_DB_HOST, CONF_DB_NAME, CONF_DB_PASSWORD, CONF_DB_USERNAME
from .coordinator import BlockyConfigEntry

TO_REDACT = {CONF_URL, CONF_DB_HOST, CONF_DB_NAME, CONF_DB_USERNAME, CONF_DB_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BlockyConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data
    status = data.coordinator.data

    diagnostics: dict[str, Any] = {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "blocking": {
            "reachable": data.coordinator.last_update_success,
            "enabled": status.enabled,
            "disabled_group_count": len(status.disabled_groups),
            "auto_enable_in_sec": status.auto_enable_in_sec,
        },
        "query_log": None,
    }

    if data.stats is not None:
        stats = data.stats.data
        query_log: dict[str, Any] = {
            "reachable": data.stats.last_update_success,
            "dialect": data.stats.database.dialect,
        }
        if stats is not None:
            latest = stats.summary.latest_request
            query_log.update(
                {
                    "queries_total": stats.queries_total,
                    "blocked_total": stats.blocked_total,
                    "category_totals": stats.category_totals,
                    "queries_24h": stats.summary.queries,
                    "blocked_24h": stats.summary.blocked,
                    "clients_24h": stats.summary.clients,
                    "avg_duration_ms": stats.summary.avg_duration_ms,
                    "latest_request_utc": latest.isoformat() if latest else None,
                    "top_list_sizes": [
                        len(stats.top_domains),
                        len(stats.top_blocked_domains),
                        len(stats.top_clients),
                    ],
                }
            )
        diagnostics["query_log"] = query_log

    return diagnostics
