"""Operational settings shared by the Settings tab and the options flow.

These are the entry options that are not a connection: the update intervals,
the new-domain reporting, the sidebar panel and the hidden clients. Every value
is validated here, once, with the bounds the coordinators use. Errors carry the
field and a stable code, never the rejected value.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from .const import (
    CONF_HIDDEN_CLIENTS,
    CONF_REPORT_EXISTING_DOMAINS,
    CONF_SHOW_IN_SIDEBAR,
    INTERVALS,
    MAX_HIDDEN_CLIENTS,
)
from .intervals import interval_seconds, parse_interval
from .validation import normalize_client

BOOLEAN_KEYS: Final = (CONF_REPORT_EXISTING_DOMAINS, CONF_SHOW_IN_SIDEBAR)
# Every option key the Settings tab may write here: nothing else is ever touched.
OPERATIONAL_KEYS: Final = (*INTERVALS, *BOOLEAN_KEYS, CONF_HIDDEN_CLIENTS)


class SettingError(Exception):
    """A setting was refused; ``field`` names it, ``code`` says why."""

    def __init__(self, field: str, code: str) -> None:
        """Remember the field and the reason."""
        super().__init__(f"{field}: {code}")
        self.field = field
        self.code = code


def hidden_clients(options: Mapping[str, Any]) -> list[str]:
    """Return the stored hidden client addresses; anything invalid is dropped.

    Read side only: a hand-edited entry can never put a non-address into a
    statement. Order is kept, duplicates are removed.
    """
    stored = options.get(CONF_HIDDEN_CLIENTS)
    if not isinstance(stored, (list, tuple)):
        return []
    found: list[str] = []
    for value in stored[:MAX_HIDDEN_CLIENTS]:
        address = normalize_client(value)
        if address is not None and address not in found:
            found.append(address)
    return found


def _parse_hidden(value: Any) -> list[str]:
    """Validate a new list of hidden clients: exact addresses, at most 50."""
    if not isinstance(value, (list, tuple)):
        raise SettingError(CONF_HIDDEN_CLIENTS, "invalid_type")
    if len(value) > MAX_HIDDEN_CLIENTS * 2:
        # Refused before any parsing, whatever the duplicates would leave.
        raise SettingError(CONF_HIDDEN_CLIENTS, "too_many_clients")
    found: list[str] = []
    for item in value:
        address = normalize_client(item)
        if address is None:
            raise SettingError(CONF_HIDDEN_CLIENTS, "invalid_address")
        if address not in found:
            found.append(address)
    if len(found) > MAX_HIDDEN_CLIENTS:
        raise SettingError(CONF_HIDDEN_CLIENTS, "too_many_clients")
    return found


def read_operational(options: Mapping[str, Any]) -> dict[str, Any]:
    """Describe the operational settings of an entry, with the interval bounds."""
    return {
        "intervals": {
            key: {
                "value": interval_seconds(options, key),
                "min": spec.minimum,
                "max": spec.maximum,
                "default": spec.default,
            }
            for key, spec in INTERVALS.items()
        },
        CONF_REPORT_EXISTING_DOMAINS: (
            options.get(CONF_REPORT_EXISTING_DOMAINS) is True
        ),
        CONF_SHOW_IN_SIDEBAR: options.get(CONF_SHOW_IN_SIDEBAR, True) is True,
        CONF_HIDDEN_CLIENTS: hidden_clients(options),
    }


def apply_operational(
    options: Mapping[str, Any], changes: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the options with ``changes`` applied, or raise SettingError.

    Only the keys of OPERATIONAL_KEYS may be changed; every other option is
    carried over untouched. Nothing is changed unless every value is valid.
    """
    new = dict(options)
    for key in INTERVALS:
        if key in changes:
            seconds = parse_interval(changes[key], key)
            if seconds is None:
                raise SettingError(key, "out_of_range")
            new[key] = seconds
    for key in BOOLEAN_KEYS:
        if key in changes:
            if not isinstance(changes[key], bool):
                raise SettingError(key, "invalid_type")
            new[key] = changes[key]
    if CONF_HIDDEN_CLIENTS in changes:
        new[CONF_HIDDEN_CLIENTS] = _parse_hidden(changes[CONF_HIDDEN_CLIENTS])
    return new
