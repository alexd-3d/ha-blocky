"""Operational settings shared by the Settings tab and the options flow.

These are the entry options that are not a connection: the update intervals,
the new-domain reporting, the sidebar panel and which manual lists exist. Every
value is validated here, once, with the bounds the coordinators use. Errors
carry the field and a stable code, never the rejected value.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from .const import (
    CONF_ALLOW_LISTS,
    CONF_DENY_LISTS,
    CONF_EXACT_ONLY_LISTS,
    CONF_LISTS,
    CONF_REPORT_EXISTING_DOMAINS,
    CONF_SHOW_IN_SIDEBAR,
    INTERVALS,
    LIST_TYPE_ALLOW,
    LIST_TYPE_DENY,
    MAX_LISTS,
)
from .intervals import interval_seconds, parse_interval
from .lists import read_definitions
from .validation import InvalidListNameError, validate_list_name
from .zones import ZoneError, build_zone, read_zones

BOOLEAN_KEYS: Final = (CONF_REPORT_EXISTING_DOMAINS, CONF_SHOW_IN_SIDEBAR)
LIST_KEYS: Final = (CONF_ALLOW_LISTS, CONF_DENY_LISTS, CONF_EXACT_ONLY_LISTS)
# Every option key the Settings tab may write: nothing else is ever touched.
OPERATIONAL_KEYS: Final = (*INTERVALS, *BOOLEAN_KEYS, *LIST_KEYS)


class SettingError(Exception):
    """A setting was refused; ``field`` names it, ``code`` says why."""

    def __init__(self, field: str, code: str) -> None:
        """Remember the field and the reason."""
        super().__init__(f"{field}: {code}")
        self.field = field
        self.code = code


def current_lists(options: Mapping[str, Any]) -> dict[str, list[str]]:
    """Return the names of the allow, deny and exact-only lists of the options."""
    definitions = read_definitions(options).values()
    return {
        CONF_ALLOW_LISTS: [
            d.name for d in definitions if d.list_type == LIST_TYPE_ALLOW
        ],
        CONF_DENY_LISTS: [d.name for d in definitions if d.list_type == LIST_TYPE_DENY],
        CONF_EXACT_ONLY_LISTS: [d.name for d in definitions if d.exact_only],
    }


def zones_stay_valid(
    options: Mapping[str, Any], new_lists: dict[str, dict[str, Any]]
) -> bool:
    """Return whether every stored zone is still valid with new lists."""
    new_definitions = read_definitions({CONF_LISTS: new_lists})
    for zone in read_zones(options, read_definitions(options)).values():
        try:
            build_zone(
                zone.name,
                [str(net) for net in zone.networks],
                zone.mode,
                list(zone.lists),
                definitions=new_definitions,
                others=(),
            )
        except ZoneError:
            return False
    return True


def build_list_definitions(
    options: Mapping[str, Any],
    allow: list[str],
    deny: list[str],
    exact: list[str],
) -> dict[str, dict[str, Any]]:
    """Validate the list names and return the definitions to store.

    Raises SettingError. A list that a zone uses cannot be removed or made
    unsuitable.
    """
    for field, names in ((CONF_ALLOW_LISTS, allow), (CONF_DENY_LISTS, deny)):
        try:
            for name in names:
                validate_list_name(name)
        except InvalidListNameError:
            raise SettingError(field, "invalid_list_name") from None
    if (
        len(set(allow)) != len(allow)
        or len(set(deny)) != len(deny)
        or set(allow) & set(deny)
    ):
        raise SettingError(CONF_ALLOW_LISTS, "duplicate_list_name")
    if len(allow) + len(deny) > MAX_LISTS:
        raise SettingError(CONF_ALLOW_LISTS, "too_many_lists")
    if set(exact) - set(allow) - set(deny):
        raise SettingError(CONF_EXACT_ONLY_LISTS, "unknown_list_name")
    definitions = {
        name: {"type": list_type, "exact_only": name in exact}
        for list_type, names in ((LIST_TYPE_ALLOW, allow), (LIST_TYPE_DENY, deny))
        for name in names
    }
    if not zones_stay_valid(options, definitions):
        raise SettingError(CONF_ALLOW_LISTS, "list_in_use")
    return definitions


def _name_list(field: str, value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_LISTS:
        raise SettingError(field, "invalid_type")
    if not all(isinstance(name, str) for name in value):
        raise SettingError(field, "invalid_type")
    return [name.strip() for name in value]


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
        **current_lists(options),
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
    if any(key in changes for key in LIST_KEYS):
        lists = current_lists(options)
        for key in LIST_KEYS:
            if key in changes:
                lists[key] = _name_list(key, changes[key])
        new[CONF_LISTS] = build_list_definitions(
            options,
            lists[CONF_ALLOW_LISTS],
            lists[CONF_DENY_LISTS],
            lists[CONF_EXACT_ONLY_LISTS],
        )
    return new
