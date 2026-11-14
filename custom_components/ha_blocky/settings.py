"""Operational settings shared by the Settings tab and the options flow.

These are the entry options that are not a connection: the update intervals,
the new-domain reporting and the sidebar panel. Every value is validated here,
once, with the bounds the coordinators use. Errors carry the field and a stable
code, never the rejected value.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from .const import (
    CONF_REPORT_EXISTING_DOMAINS,
    CONF_SHOW_IN_SIDEBAR,
    INTERVALS,
)
from .intervals import interval_seconds, parse_interval

BOOLEAN_KEYS: Final = (CONF_REPORT_EXISTING_DOMAINS, CONF_SHOW_IN_SIDEBAR)
# Every option key the Settings tab may write here: nothing else is ever touched.
OPERATIONAL_KEYS: Final = (*INTERVALS, *BOOLEAN_KEYS)


class SettingError(Exception):
    """A setting was refused; ``field`` names it, ``code`` says why."""

    def __init__(self, field: str, code: str) -> None:
        """Remember the field and the reason."""
        super().__init__(f"{field}: {code}")
        self.field = field
        self.code = code


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
    return new
