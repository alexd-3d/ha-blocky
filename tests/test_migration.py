"""Tests for the one-time migration from zones and free lists to client levels.

The old option names (``zones``, ``lists``, modes, phases) appear here and in
the migration code only.
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.ha_blocky.const import (
    CONF_CLIENTS,
    CONF_LIST_NETWORKS,
    CONF_NOTIFY,
    DOMAIN,
)
from custom_components.ha_blocky.lists import storage_key as lists_key
from custom_components.ha_blocky.migration import convert_zones
from custom_components.ha_blocky.requests import storage_key as requests_key

from .test_lists import LOOPBACK

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

BASE_URL = "http://blocky.example:4000"
STATUS_URL = f"{BASE_URL}/api/blocking/status"
ENABLED = {"enabled": True, "disabledGroups": [], "autoEnableInSec": 0}

PHONE = "192.0.2.21"
VACUUM = "198.51.100.30"
TV = "198.51.100.31"
TOKEN = "T" * 43

OLD_LISTS = {
    "allow_default": {"type": "allow", "exact_only": True},
    "deny_default": {"type": "deny", "exact_only": False},
    "allow_robot": {"type": "allow", "exact_only": True},
    "deny_other": {"type": "deny", "exact_only": False},
}
OLD_OPTIONS = {
    CONF_LIST_NETWORKS: LOOPBACK,
    "lists": OLD_LISTS,
    "zones": {
        "phones": {
            "networks": [f"{PHONE}/32"],
            "mode": "learning",
            "lists": ["deny_other"],
        },
        "robots": {
            "networks": [f"{VACUUM}/32", f"{TV}/32"],
            "mode": "allowlist_only",
            "lists": ["allow_default", "allow_robot"],
        },
        "office": {"networks": ["203.0.113.0/24"], "mode": "filter", "lists": []},
        "lab": {"networks": ["203.0.113.0/25"], "mode": "learning", "lists": []},
    },
}


def _store(key: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "minor_version": 1, "key": key, "data": data}


async def _setup_old(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
    options: dict[str, Any],
    *,
    minor_version: int = 1,
    stores: bool = True,
) -> MockConfigEntry:
    assert await async_setup_component(hass, "http", {})
    aioclient_mock.get(STATUS_URL, json=ENABLED)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_URL: BASE_URL},
        options=options,
        minor_version=minor_version,
    )
    entry.add_to_hass(hass)
    if stores:
        hass_storage[lists_key(entry.entry_id)] = _store(
            lists_key(entry.entry_id),
            {
                "token": TOKEN,
                "lists": {
                    "allow_default": ["ok.example.com"],
                    "deny_default": ["ads.example.net", "*.track.example.net"],
                    "allow_robot": ["vendor.example.com", "cdn.example.com"],
                    "deny_other": ["other.example.org"],
                },
            },
        )
        hass_storage[requests_key(entry.entry_id)] = _store(
            requests_key(entry.entry_id),
            {
                "cursor": 7,
                "clients": {
                    PHONE: {
                        "zone": "phones",
                        "mode": "learning",
                        "phase": "learning",
                        "last_seen": 5.0,
                        "baselined": True,
                        "known": ["a.example.com", "b.example.com"],
                        "rejected": [],
                        "leaks": {},
                    },
                    VACUUM: {
                        "zone": "robots",
                        "mode": "allowlist_only",
                        "phase": "locked",
                        "last_seen": 5.0,
                        "baselined": True,
                        "known": ["vendor.example.com"],
                        "rejected": ["bad.example.com"],
                        "leaks": {},
                    },
                    "203.0.113.5": {
                        "zone": "office",
                        "mode": "filter",
                        "phase": "learning",
                        "last_seen": 5.0,
                        "known": ["gone.example.com"],
                    },
                },
                "requests": [
                    {
                        "id": "A" * 22,
                        "client": PHONE,
                        "domain": "a.example.com",
                        "kind": "learning",
                        "created": 5.0,
                    },
                    {
                        "id": "B" * 22,
                        "client": "203.0.113.5",
                        "domain": "gone.example.com",
                        "kind": "learning",
                        "created": 5.0,
                    },
                ],
            },
        )
    registry = er.async_get(hass)
    for platform_id, unique in (
        ("sensor", "zone_phones_queries_24h"),
        ("sensor", "zone_phones_blocked_24h"),
        ("sensor", "list_allow_robot"),
        ("sensor", "list_deny_other"),
        ("sensor", "list_allow_default"),
    ):
        registry.async_get_or_create(
            platform_id,
            DOMAIN,
            f"{entry.entry_id}_{unique}",
            config_entry=entry,
            suggested_object_id=f"old_{unique}",
        )
    return entry


async def test_the_real_shape_migrates_both_zones(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    entry = await _setup_old(hass, aioclient_mock, hass_storage, OLD_OPTIONS)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.minor_version == 2
    assert "zones" not in entry.options and "lists" not in entry.options
    assert entry.options[CONF_CLIENTS] == {
        PHONE: {"level": "restricted"},
        VACUUM: {"level": "lockdown", "ask": False},
        TV: {"level": "lockdown", "ask": True},
    }
    assert entry.options[CONF_NOTIFY] == {"restricted": True, "lockdown": True}
    assert entry.options[CONF_LIST_NETWORKS] == LOOPBACK
    levels = entry.runtime_data.levels
    assert {a: c.level for a, c in levels.clients.items()} == {
        PHONE: "restricted",
        VACUUM: "lockdown",
        TV: "lockdown",
    }

    lists = entry.runtime_data.lists
    # The copies: the linked allow lists' entries; the originals stay.
    assert lists.entries("lockdown_allow") == [
        "cdn.example.com",
        "ok.example.com",
        "vendor.example.com",
    ]
    assert lists.entries("allow_default") == ["ok.example.com"]
    assert lists.entries("deny_default") == ["*.track.example.net", "ads.example.net"]
    assert lists.entries("restricted_deny") == []
    assert lists.token == TOKEN

    # The stored per-client state keeps its address key, known domains and
    # pending request; a dropped zone's state is gone.
    tracker = entry.runtime_data.requests
    assert tracker is None  # no query log configured in this entry
    stored = hass_storage[requests_key(entry.entry_id)]["data"]
    assert set(stored["clients"]) == {PHONE, VACUUM}
    assert stored["clients"][PHONE]["level"] == "restricted"
    assert stored["clients"][PHONE]["known"] == ["a.example.com", "b.example.com"]
    assert stored["clients"][VACUUM]["rejected"] == ["bad.example.com"]
    for state in stored["clients"].values():
        assert not {"zone", "mode", "phase"} & set(state)
    assert [r["id"] for r in stored["requests"]] == ["A" * 22]
    assert stored["cursor"] == 7

    # Counts and reason codes only: no names, no addresses.
    message = next(
        r.getMessage()
        for r in caplog.records
        if r.name == "custom_components.ha_blocky.migration"
    )
    assert "3 clients migrated" in message
    assert "2 zones dropped" in message
    assert "filter_mode=1" in message and "non_host_network=1" in message
    for needle in ("phones", "robots", "office", PHONE, VACUUM, "203.0.113"):
        assert needle not in message


async def test_old_entities_are_removed_and_kept_ones_stay(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    entry = await _setup_old(hass, aioclient_mock, hass_storage, OLD_OPTIONS)
    registry = er.async_get(hass)
    assert registry.async_get("sensor.old_zone_phones_queries_24h") is not None

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for gone in (
        "sensor.old_zone_phones_queries_24h",
        "sensor.old_zone_phones_blocked_24h",
        "sensor.old_list_allow_robot",
        "sensor.old_list_deny_other",
    ):
        assert registry.async_get(gone) is None, gone
    assert registry.async_get("sensor.old_list_allow_default") is not None
    # No registry entry of the entry names a zone or a free list.
    for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
        assert "_zone_" not in registered.unique_id
        assert not registered.unique_id.endswith(("allow_robot", "deny_other"))


async def test_migration_runs_once_and_is_idempotent(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    entry = await _setup_old(hass, aioclient_mock, hass_storage, OLD_OPTIONS)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    options = dict(entry.options)
    stored = dict(hass_storage[requests_key(entry.entry_id)]["data"])

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.options == options
    assert entry.minor_version == 2
    assert (
        hass_storage[requests_key(entry.entry_id)]["data"]["clients"]
        == stored["clients"]
    )

    # Even run again as if the version had not been bumped: nothing is left to
    # migrate, and nothing changes.
    hass.config_entries.async_update_entry(entry, minor_version=1)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.options == options


async def test_a_new_entry_without_old_options_is_only_bumped(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    entry = await _setup_old(
        hass, aioclient_mock, hass_storage, {CONF_LIST_NETWORKS: LOOPBACK}, stores=False
    )
    registry = er.async_get(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.minor_version == 2
    assert entry.options == {CONF_LIST_NETWORKS: LOOPBACK}
    # Only old zone entities and free list entities go; the fixed lists stay.
    assert registry.async_get("sensor.old_zone_phones_queries_24h") is None
    assert registry.async_get("sensor.old_list_allow_default") is not None


async def test_an_entry_that_is_already_current_is_left_alone(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    entry = await _setup_old(
        hass, aioclient_mock, hass_storage, OLD_OPTIONS, minor_version=2
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Not migrated: the old options are untouched (and ignored).
    assert "zones" in entry.options
    assert entry.runtime_data.levels.clients == {}


# --- The conversion of zones --------------------------------------------------------


def _zones(**zones: Any) -> dict[str, Any]:
    return zones


@pytest.mark.parametrize(
    ("zone", "reason"),
    [
        ({"networks": ["192.0.2.0/24"], "mode": "learning"}, "non_host_network"),
        (
            {"networks": ["192.0.2.1/32", "192.0.2.0/30"], "mode": "learning"},
            "non_host_network",
        ),
        ({"networks": ["2001:db8::/64"], "mode": "allowlist_only"}, "non_host_network"),
        ({"networks": ["192.0.2.1/32"], "mode": "filter"}, "filter_mode"),
        ({"networks": ["192.0.2.1/32"], "mode": "weird"}, "malformed"),
        ({"networks": [], "mode": "learning"}, "non_host_network"),
        ({"networks": "192.0.2.1/32", "mode": "learning"}, "non_host_network"),
        ({"networks": [5], "mode": "learning"}, "non_host_network"),
        ({"networks": ["not-a-network"], "mode": "learning"}, "non_host_network"),
        ({"networks": ["192.0.2.1/32"] * 9, "mode": "learning"}, "non_host_network"),
        ("junk", "malformed"),
        (None, "malformed"),
    ],
)
def test_zones_that_cannot_migrate_safely_are_dropped_with_a_reason(
    zone: Any, reason: str
) -> None:
    clients, linked, learning, dropped = convert_zones({"z": zone}, {})

    assert clients == {}
    assert linked == set()
    assert learning is False
    assert dict(dropped) == {reason: 1}


def test_a_malformed_zones_option_drops_everything_and_counts_it() -> None:
    for raw in ("junk", ["a"], 5):
        clients, _linked, _learning, dropped = convert_zones(raw, {})
        assert clients == {} and dict(dropped) == {"malformed": 1}
    assert convert_zones(None, {})[3] == {}


def test_hosts_are_normalised_deduplicated_and_ipv6_is_supported() -> None:
    clients, linked, learning, dropped = convert_zones(
        _zones(
            a={
                "networks": ["::ffff:192.0.2.5/128", "2001:DB8::1/128"],
                "mode": "learning",
            },
            b={
                "networks": ["192.0.2.5/32", "192.0.2.6"],
                "mode": "allowlist_only",
                "lists": ["x", "y", 5],
            },
        ),
        {"x": "allow", "y": "deny"},
    )

    assert set(clients) == {"2001:db8::1", "192.0.2.5", "192.0.2.6"}
    assert clients["192.0.2.5"]["level"] == "restricted"  # first zone wins
    assert clients["192.0.2.6"]["level"] == "lockdown"
    assert linked == {"x"}  # only allow lists
    assert learning is True
    assert dict(dropped) == {}


def test_the_client_cap_drops_the_zone_that_does_not_fit() -> None:
    zones = _zones(
        big={
            "networks": [f"192.0.2.{i}/32" for i in range(1, 9)],
            "mode": "learning",
        },
        **{
            f"z{i}": {
                "networks": [f"198.51.100.{i * 8 + j}/32" for j in range(8)],
                "mode": "learning",
            }
            for i in range(0, 8)
        },
    )

    clients, _linked, _learning, dropped = convert_zones(zones, {})

    assert len(clients) <= 64
    assert dropped["too_many_clients"] >= 1 or dropped["too_many_zones"] >= 1


async def test_phases_become_ask(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    entry = await _setup_old(hass, aioclient_mock, hass_storage, OLD_OPTIONS)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # locked -> ask off; learning (and a client with no stored state) -> ask on.
    assert entry.options[CONF_CLIENTS][VACUUM]["ask"] is False
    assert entry.options[CONF_CLIENTS][TV]["ask"] is True


async def test_notify_stays_default_without_a_learning_zone(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    options = {
        CONF_LIST_NETWORKS: LOOPBACK,
        "lists": {"allow_a": {"type": "allow", "exact_only": True}},
        "zones": {
            "robots": {
                "networks": [f"{VACUUM}/32"],
                "mode": "allowlist_only",
                "lists": ["allow_a"],
            }
        },
    }
    entry = await _setup_old(hass, aioclient_mock, hass_storage, options, stores=False)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert CONF_NOTIFY not in entry.options
    assert entry.options[CONF_CLIENTS] == {VACUUM: {"level": "lockdown", "ask": True}}
    assert entry.runtime_data.levels.notify == {"restricted": False, "lockdown": True}


async def test_a_global_list_of_the_wrong_type_is_not_kept(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    options = {
        CONF_LIST_NETWORKS: LOOPBACK,
        "lists": {
            "allow_default": {"type": "deny", "exact_only": False},
            "deny_default": {"type": "deny", "exact_only": False},
        },
    }
    entry = await _setup_old(hass, aioclient_mock, hass_storage, options)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    lists = entry.runtime_data.lists
    # allow_default was a deny list before: its entries must not turn into allows.
    assert lists.entries("allow_default") == []
    assert lists.entries("deny_default") == ["*.track.example.net", "ads.example.net"]
    assert lists.entries("lockdown_allow") == []


async def test_a_malformed_zone_is_dropped_and_the_rest_still_works(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    options = {
        CONF_LIST_NETWORKS: LOOPBACK,
        "lists": OLD_LISTS,
        "zones": {
            "evil\nname": {"networks": ["192.0.2.1/32 x"], "mode": "learning"},
            "ok": {"networks": [f"{TV}/32"], "mode": "learning", "lists": []},
        },
    }
    entry = await _setup_old(hass, aioclient_mock, hass_storage, options, stores=False)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert set(entry.options[CONF_CLIENTS]) == {TV}
    assert "evil" not in caplog.text
