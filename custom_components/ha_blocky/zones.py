"""Zones: user-defined client groups.

A zone is only a record used to tell which policy applies to a client address
seen in the query log. The integration never changes Blocky's configuration;
it can render a fragment for the user to copy.

Zones live in the entry options and are re-validated on every read: nothing
stored is trusted.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .const import (
    CONF_ZONES,
    LIST_TYPE_ALLOW,
    LIST_TYPE_DENY,
    MAX_ZONES,
    ZONE_MODE_ALLOWLIST_ONLY,
    ZONE_MODES,
)
from .lists import ListDefinition
from .validation import (
    InvalidNetworkError,
    InvalidZoneNameError,
    IPNetwork,
    address_in_networks,
    networks_overlap,
    parse_zone_networks,
    validate_zone_name,
)

_LOGGER = logging.getLogger(__name__)


class ZoneError(Exception):
    """A zone definition was refused; ``code`` is a short machine-readable reason."""

    def __init__(self, code: str) -> None:
        """Remember the reason."""
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ZoneDefinition:
    """A validated zone."""

    name: str
    networks: tuple[IPNetwork, ...]
    mode: str
    lists: tuple[str, ...]


def build_zone(
    name: object,
    networks: object,
    mode: object,
    lists: object,
    *,
    definitions: Mapping[str, ListDefinition],
    others: Iterable[ZoneDefinition],
) -> ZoneDefinition:
    """Validate everything and return the zone, or raise ZoneError.

    ``others`` are the other zones; overlap with them is refused, because
    Blocky merges the groups of every matching client group, which would
    silently switch an allowlist-only zone off.
    """
    try:
        valid_name = validate_zone_name(name)
    except InvalidZoneNameError as err:
        raise ZoneError("invalid_zone_name") from err
    try:
        valid_networks = parse_zone_networks(networks)
    except InvalidNetworkError as err:
        raise ZoneError("invalid_network") from err
    if not isinstance(mode, str) or mode not in ZONE_MODES:
        raise ZoneError("invalid_zone_mode")

    if isinstance(lists, str) or not isinstance(lists, (list, tuple)):
        raise ZoneError("unknown_list_name")
    linked: list[str] = []
    for item in lists:
        if not isinstance(item, str) or item not in definitions or item in linked:
            raise ZoneError("unknown_list_name")
        linked.append(item)

    if mode == ZONE_MODE_ALLOWLIST_ONLY and (
        not linked
        or any(
            definitions[item].list_type != LIST_TYPE_ALLOW
            or not definitions[item].exact_only
            for item in linked
        )
    ):
        raise ZoneError("allowlist_only_lists")

    for other in others:
        if networks_overlap(valid_networks, other.networks):
            raise ZoneError("zone_overlap")

    return ZoneDefinition(
        name=valid_name, networks=valid_networks, mode=mode, lists=tuple(linked)
    )


def read_zones(
    options: Mapping[str, Any], definitions: Mapping[str, ListDefinition]
) -> dict[str, ZoneDefinition]:
    """Read the zones from the options, dropping invalid ones. Never raises."""
    raw = options.get(CONF_ZONES)
    zones: dict[str, ZoneDefinition] = {}
    if not isinstance(raw, Mapping):
        return zones
    for index, (name, spec) in enumerate(raw.items()):
        if len(zones) >= MAX_ZONES:
            _LOGGER.error("More than %d stored zones; the rest are ignored", MAX_ZONES)
            break
        try:
            if not isinstance(spec, Mapping):
                raise ZoneError("invalid_zone_name")
            zone = build_zone(
                name,
                spec.get("networks"),
                spec.get("mode"),
                spec.get("lists", []),
                definitions=definitions,
                others=zones.values(),
            )
        except ZoneError as err:
            # Neither the name nor the networks are logged: they are data.
            _LOGGER.error("Stored zone number %d ignored: %s", index + 1, err.code)
            continue
        zones[zone.name] = zone
    return zones


def zone_to_options(zone: ZoneDefinition) -> dict[str, Any]:
    """Return the form in which a zone is stored in the options."""
    return {
        "networks": [str(network) for network in zone.networks],
        "mode": zone.mode,
        "lists": list(zone.lists),
    }


def zone_for_address(
    address: object, zones: Mapping[str, ZoneDefinition]
) -> str | None:
    """Return the name of the zone a client address (text) belongs to."""
    for name, zone in zones.items():
        if address_in_networks(address, zone.networks):
            return name
    return None


def _quote(value: str) -> str:
    """Return a YAML double-quoted scalar (JSON strings are valid YAML)."""
    return json.dumps(value)


def render_blocky_config(
    zones: Mapping[str, ZoneDefinition],
    urls: Mapping[str, str],
    definitions: Mapping[str, ListDefinition],
) -> str:
    """Render the Blocky ``blocking`` fragment for the zones, or "".

    Built only from validated names, ``str(network)`` and the given URLs.
    """
    if not zones:
        return ""

    sections: dict[str, list[str]] = {"denylists": [], "allowlists": []}
    for zone in zones.values():
        for key, list_type in (
            ("denylists", LIST_TYPE_DENY),
            ("allowlists", LIST_TYPE_ALLOW),
        ):
            linked = [
                urls[item]
                for item in zone.lists
                if item in urls
                and item in definitions
                and definitions[item].list_type == list_type
            ]
            if linked:
                sections[key].append(f"    {_quote(zone.name)}:")
                sections[key].extend(f"      - {_quote(url)}" for url in linked)

    lines = ["blocking:"]
    for key, body in sections.items():
        if body:
            lines.append(f"  {key}:")
            lines.extend(body)
    lines.append("  clientGroupsBlock:")
    for zone in zones.values():
        for network in zone.networks:
            lines.append(f"    {_quote(str(network))}:")
            lines.append(f"      - {_quote(zone.name)}")
    return "\n".join(lines) + "\n"
