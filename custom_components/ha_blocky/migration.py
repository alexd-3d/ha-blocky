"""One-time migration from zones and free lists to clients with levels.

Runs once per config entry (entry minor version 1 -> 2), before the entry is
set up. Fail closed: a zone that cannot be migrated safely is dropped, and the
log says only how many and why (a reason code), never a name or an address.

- A zone whose networks are all single hosts becomes one client per host:
  mode ``learning`` -> Restricted, mode ``allowlist_only`` -> Lockdown (with
  the stored phase: learning -> ask on, locked -> ask off).
- Zones with a network wider than one host, ``filter`` zones and anything
  malformed are dropped.
- ``lockdown_allow`` receives a copy of the entries of the allow lists linked
  to the migrated Lockdown zones; the originals stay.
- ``notify.restricted`` becomes true when a learning zone was migrated.
- The options ``zones`` and ``lists`` are removed, and so are the registry
  entries of the old zone sensors and the free list sensors.

The migration is idempotent: with the old options gone it only bumps the
version.
"""

from __future__ import annotations

import ipaddress
import logging
from collections import Counter
from collections.abc import Mapping
from typing import Any, Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import (
    CONF_CLIENTS,
    CONF_NOTIFY,
    DEFAULT_NOTIFY,
    LEVEL_LOCKDOWN,
    LEVEL_RESTRICTED,
    LIST_ALLOW_DEFAULT,
    LIST_DENY_DEFAULT,
    LIST_LOCKDOWN_ALLOW,
    LIST_TYPE_ALLOW,
    LIST_TYPE_DENY,
    MAX_CLIENTS,
    MAX_LIST_ENTRIES,
    RULE_LISTS,
)
from .lists import STORAGE_VERSION as LISTS_STORAGE_VERSION
from .lists import storage_key as lists_storage_key
from .requests import STORAGE_VERSION as REQUESTS_STORAGE_VERSION
from .requests import storage_key as requests_storage_key
from .validation import InvalidDomainError, normalize_client, normalize_domain

_LOGGER = logging.getLogger(__name__)

TARGET_MINOR: Final = 2
# Old option keys (the zone and free list model), removed by the migration.
_OLD_ZONES: Final = "zones"
_OLD_LISTS: Final = "lists"
_OLD_MODE_LEARNING: Final = "learning"
_OLD_MODE_ALLOWLIST: Final = "allowlist_only"
_OLD_PHASE_LOCKED: Final = "locked"
_MAX_OLD_ZONES: Final = 16
_MAX_OLD_NETWORKS: Final = 8


def _host_addresses(raw: object) -> list[str] | None:
    """Return the normalised addresses if every network is one host, else None."""
    if isinstance(raw, str) or not isinstance(raw, list):
        return None
    if not 1 <= len(raw) <= _MAX_OLD_NETWORKS:
        return None
    addresses: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            return None
        try:
            network = ipaddress.ip_network(item.strip(), strict=False)
        except ValueError:
            return None
        if network.prefixlen != network.max_prefixlen:
            return None
        address = normalize_client(str(network.network_address))
        if address is None:
            return None
        addresses.append(address)
    return addresses


def _old_list_types(raw: object) -> dict[str, str]:
    """Return name -> "allow" or "deny" of the old list definitions."""
    types: dict[str, str] = {}
    if isinstance(raw, Mapping):
        for name, spec in raw.items():
            if (
                isinstance(name, str)
                and isinstance(spec, Mapping)
                and spec.get("type") in (LIST_TYPE_ALLOW, LIST_TYPE_DENY)
            ):
                types[name] = spec["type"]
    return types


def convert_zones(
    raw_zones: object, list_types: Mapping[str, str]
) -> tuple[dict[str, dict[str, Any]], set[str], bool, Counter[str]]:
    """Turn the old zones into clients.

    Returns ``(clients, linked_allow_lists, learning_migrated, dropped)``;
    ``clients`` maps an address to ``{"level", "ask"}`` (ask defaults to true for
    Lockdown; the stored phase is applied by the caller).
    """
    clients: dict[str, dict[str, Any]] = {}
    linked: set[str] = set()
    learning = False
    dropped: Counter[str] = Counter()
    if raw_zones is None:
        return clients, linked, learning, dropped
    if not isinstance(raw_zones, Mapping):
        dropped["malformed"] += 1
        return clients, linked, learning, dropped
    for index, spec in enumerate(raw_zones.values()):
        if index >= _MAX_OLD_ZONES:
            dropped["too_many_zones"] += 1
            continue
        if not isinstance(spec, Mapping):
            dropped["malformed"] += 1
            continue
        mode = spec.get("mode")
        if mode not in (_OLD_MODE_LEARNING, _OLD_MODE_ALLOWLIST):
            dropped["filter_mode" if mode == "filter" else "malformed"] += 1
            continue
        addresses = _host_addresses(spec.get("networks"))
        if addresses is None:
            dropped["non_host_network"] += 1
            continue
        level = LEVEL_RESTRICTED if mode == _OLD_MODE_LEARNING else LEVEL_LOCKDOWN
        new = [a for a in addresses if a not in clients]
        if len(clients) + len(new) > MAX_CLIENTS:
            dropped["too_many_clients"] += 1
            continue
        for address in new:
            clients[address] = {"level": level}
        if level == LEVEL_RESTRICTED:
            learning = True
        else:
            names = spec.get("lists")
            if isinstance(names, list):
                linked.update(
                    name
                    for name in names
                    if isinstance(name, str) and list_types.get(name) == LIST_TYPE_ALLOW
                )
    return clients, linked, learning, dropped


def _convert_state(raw: object, level: str) -> dict[str, Any] | None:
    """Return the stored state of a client in the new form, or None."""
    if not isinstance(raw, dict):
        return None
    if raw.get("level") == level:
        return raw
    mode = raw.get("mode")
    expected = _OLD_MODE_LEARNING if level == LEVEL_RESTRICTED else _OLD_MODE_ALLOWLIST
    if mode != expected or not isinstance(raw.get("zone"), str):
        return None
    converted = {
        key: value for key, value in raw.items() if key not in ("zone", "mode", "phase")
    }
    converted["level"] = level
    return converted


async def _migrate_requests(
    hass: HomeAssistant, entry_id: str, clients: dict[str, dict[str, Any]]
) -> None:
    """Rewrite the stored request state; set ``ask`` from the stored phases."""
    store: Store[dict[str, Any]] = Store(
        hass, REQUESTS_STORAGE_VERSION, requests_storage_key(entry_id)
    )
    stored = await store.async_load()
    old_states: dict[str, Any] = {}
    if isinstance(stored, dict) and isinstance(stored.get("clients"), dict):
        for raw_address, raw in stored["clients"].items():
            address = normalize_client(raw_address)
            if address is not None:
                old_states[address] = raw
    for address, spec in clients.items():
        if spec["level"] == LEVEL_LOCKDOWN:
            state = old_states.get(address)
            phase = state.get("phase") if isinstance(state, dict) else None
            spec["ask"] = phase != _OLD_PHASE_LOCKED
    if not isinstance(stored, dict):
        return
    states: dict[str, Any] = {}
    for address, spec in clients.items():
        converted = _convert_state(old_states.get(address), spec["level"])
        if converted is not None:
            states[address] = converted
    requests = [
        raw
        for raw in stored.get("requests", [])
        if isinstance(raw, dict) and normalize_client(raw.get("client")) in states
    ]
    await store.async_save(
        {"cursor": stored.get("cursor"), "clients": states, "requests": requests}
    )


async def _migrate_lists(
    hass: HomeAssistant,
    entry_id: str,
    list_types: Mapping[str, str],
    linked: set[str],
) -> None:
    """Keep the two global lists, copy linked allow lists into lockdown_allow."""
    store: Store[dict[str, Any]] = Store(
        hass, LISTS_STORAGE_VERSION, lists_storage_key(entry_id)
    )
    stored = await store.async_load()
    if not isinstance(stored, dict) or not isinstance(stored.get("lists"), dict):
        return
    old = stored["lists"]
    new: dict[str, list[str]] = {name: [] for name in RULE_LISTS}
    keep = (
        (LIST_ALLOW_DEFAULT, LIST_TYPE_ALLOW),
        (LIST_DENY_DEFAULT, LIST_TYPE_DENY),
    )
    for name, list_type in keep:
        if list_types.get(name) == list_type and isinstance(old.get(name), list):
            new[name] = list(old[name][:MAX_LIST_ENTRIES])
    lockdown: set[str] = set()
    sources = [old.get(LIST_LOCKDOWN_ALLOW), *(old.get(name) for name in linked)]
    for source in sources:
        if not isinstance(source, list):
            continue
        for item in source[:MAX_LIST_ENTRIES]:
            try:
                lockdown.add(normalize_domain(item, allow_wildcard=False))
            except InvalidDomainError:
                continue
    new[LIST_LOCKDOWN_ALLOW] = sorted(lockdown)[:MAX_LIST_ENTRIES]
    await store.async_save({**stored, "lists": new})


def _remove_old_entities(hass: HomeAssistant, entry_id: str) -> int:
    """Remove the registry entries of zone sensors and free list sensors."""
    registry = er.async_get(hass)
    zone_prefix = f"{entry_id}_zone_"
    list_prefix = f"{entry_id}_list_"
    removed = 0
    for registered in er.async_entries_for_config_entry(registry, entry_id):
        unique_id = registered.unique_id
        if unique_id.startswith(zone_prefix) or (
            unique_id.startswith(list_prefix)
            and unique_id.removeprefix(list_prefix) not in RULE_LISTS
        ):
            registry.async_remove(registered.entity_id)
            removed += 1
    return removed


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an entry to the client level model (entry point, runs once)."""
    if entry.version > 1:
        return False
    if entry.minor_version >= TARGET_MINOR:
        return True

    options = dict(entry.options)
    raw_zones = options.pop(_OLD_ZONES, None)
    raw_lists = options.pop(_OLD_LISTS, None)
    had_old = raw_zones is not None or raw_lists is not None
    list_types = _old_list_types(raw_lists)

    clients, linked, learning, dropped = convert_zones(raw_zones, list_types)
    if had_old:
        await _migrate_requests(hass, entry.entry_id, clients)
        await _migrate_lists(hass, entry.entry_id, list_types, linked)
        if clients and CONF_CLIENTS not in options:
            options[CONF_CLIENTS] = clients
        if learning and CONF_NOTIFY not in options:
            options[CONF_NOTIFY] = {**DEFAULT_NOTIFY, LEVEL_RESTRICTED: True}
    removed = _remove_old_entities(hass, entry.entry_id)

    hass.config_entries.async_update_entry(
        entry, options=options, minor_version=TARGET_MINOR
    )
    if had_old or removed:
        # Counts and reason codes only: names and addresses are data.
        _LOGGER.warning(
            "Client levels migration: %d clients migrated, %d zones dropped (%s), "
            "%d old entities removed",
            len(clients),
            sum(dropped.values()),
            ", ".join(f"{code}={count}" for code, count in sorted(dropped.items()))
            or "none",
            removed,
        )
    return True
