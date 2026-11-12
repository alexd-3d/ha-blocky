"""Tests for the zones: validation, storage, options, statistics, sensors and
the commands and files that show them."""

from __future__ import annotations

import ipaddress
import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator
from sqlalchemy.engine import URL

from custom_components.ha_blocky import db
from custom_components.ha_blocky.const import (
    CONF_ALLOW_LISTS,
    CONF_DENY_LISTS,
    CONF_EXACT_ONLY_LISTS,
    CONF_LIST_NETWORKS,
    CONF_LISTS,
    CONF_ZONES,
    DOMAIN,
    MAX_ZONE_NETWORKS,
    MAX_ZONES,
    STATS_INTERVAL,
)
from custom_components.ha_blocky.diagnostics import async_get_config_entry_diagnostics
from custom_components.ha_blocky.frontend import FRONTEND_DIR
from custom_components.ha_blocky.lists import ListDefinition
from custom_components.ha_blocky.validation import (
    InvalidNetworkError,
    InvalidZoneNameError,
    networks_overlap,
    parse_zone_networks,
    validate_zone_name,
)
from custom_components.ha_blocky.zones import (
    ZoneDefinition,
    ZoneError,
    build_zone,
    read_zones,
    render_blocky_config,
    zone_for_address,
)

from .test_db import NOW, add_rows, make_log
from .test_db import row as db_row
from .test_lists import LIST_OPTIONS, LOOPBACK
from .test_stats import (
    DB_OPTIONS,
    ENABLED,
    STATUS_URL,
    _poll,
    log_row,
    open_options_step,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

BASE_URL = "http://blocky.example:4000"
CARD_SOURCE = "\n".join(
    path.read_text(encoding="utf-8") for path in sorted(FRONTEND_DIR.glob("*.js"))
)

DEFINITIONS = {
    "allow_default": ListDefinition("allow_default", "allow", False),
    "deny_default": ListDefinition("deny_default", "deny", False),
    "allow_quarantine": ListDefinition("allow_quarantine", "allow", True),
}

OFFICE_ONLY = {
    "office": {"networks": ["192.0.2.0/24"], "mode": "filter", "lists": []},
}

ZONE_OPTIONS = {
    CONF_ZONES: {
        "office": {
            "networks": ["192.0.2.0/24", "2001:db8::/32"],
            "mode": "filter",
            "lists": [],
        },
        "lab": {"networks": ["198.51.100.0/24"], "mode": "learning", "lists": []},
    }
}


def _net(text: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    return ipaddress.ip_network(text)


def _zone(
    name: str,
    networks: list[str],
    mode: str = "filter",
    lists: tuple[str, ...] = (),
) -> ZoneDefinition:
    return ZoneDefinition(
        name=name,
        networks=tuple(_net(network) for network in networks),
        mode=mode,
        lists=lists,
    )


def _build(
    name: object = "office",
    networks: tuple[object, ...] = ("192.0.2.0/24",),
    mode: object = "filter",
    lists: tuple[object, ...] = (),
    others: tuple[ZoneDefinition, ...] = (),
) -> ZoneDefinition:
    return build_zone(
        name,
        list(networks),
        mode,
        list(lists),
        definitions=DEFINITIONS,
        others=others,
    )


# --- Validation -------------------------------------------------------------


@pytest.mark.parametrize("value", ["office", "lab_2", "a", "0zone", "a" * 32])
def test_zone_name_accepts(value: str) -> None:
    assert validate_zone_name(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "Office",
        "bad name",
        "../x",
        "a-b",
        "_x",
        "-x",
        "a" * 33,
        "office\n",
        None,
        5,
        ["office"],
    ],
)
def test_zone_name_refuses(value: Any) -> None:
    with pytest.raises(InvalidZoneNameError):
        validate_zone_name(value)


def test_single_address_becomes_a_host_network() -> None:
    networks = parse_zone_networks(["192.0.2.10", "2001:db8::10"])

    assert networks == (_net("192.0.2.10/32"), _net("2001:db8::10/128"))


def test_cidr_host_bits_are_normalised() -> None:
    networks = parse_zone_networks(["192.0.2.10/24"])

    assert [str(network) for network in networks] == ["192.0.2.0/24"]


def test_eight_networks_are_accepted() -> None:
    values = [f"203.0.113.{index}" for index in range(MAX_ZONE_NETWORKS)]

    assert len(parse_zone_networks(values)) == MAX_ZONE_NETWORKS


@pytest.mark.parametrize(
    "values",
    [
        [],
        [f"203.0.113.{index}" for index in range(MAX_ZONE_NETWORKS + 1)],
        ["0.0.0.0/0"],
        ["::/0"],
        ["192.0.2.0/24", "0.0.0.0/0"],
        [5],
        [None],
        [""],
        ["   "],
        ["nonsense"],
        ["192.0.2.0/33"],
        "192.0.2.1",
        None,
        5,
    ],
)
def test_zone_networks_refuse(values: Any) -> None:
    with pytest.raises(InvalidNetworkError):
        parse_zone_networks(values)


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        (["192.0.2.0/24"], ["192.0.2.0/24"], True),
        (["192.0.2.0/24"], ["192.0.2.128/25"], True),
        (["192.0.2.128/25"], ["192.0.2.0/24"], True),
        (["192.0.2.10"], ["192.0.2.0/24"], True),
        (["192.0.2.0/24"], ["198.51.100.0/24"], False),
        (["2001:db8::/32"], ["2001:db8:1::5"], True),
        (["2001:db8::/32"], ["2001:db9::/32"], False),
        (["2001:db8::/32"], ["192.0.2.0/24"], False),
        (["192.0.2.0/24"], ["2001:db8::/32"], False),
        (
            ["192.0.2.0/24", "2001:db8::/32"],
            ["2001:db8:ffff::/48"],
            True,
        ),
        (
            ["192.0.2.0/24", "2001:db8::/32"],
            ["198.51.100.0/24", "2001:db9::/32"],
            False,
        ),
    ],
)
def test_networks_overlap(first: list[str], second: list[str], expected: bool) -> None:
    assert (
        networks_overlap(parse_zone_networks(first), parse_zone_networks(second))
        is expected
    )


# --- build_zone -------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "lists", "expected_lists"),
    [
        ("filter", (), ()),
        ("filter", ("deny_default",), ("deny_default",)),
        (
            "learning",
            ("allow_default", "deny_default"),
            ("allow_default", "deny_default"),
        ),
        ("allowlist_only", ("allow_quarantine",), ("allow_quarantine",)),
    ],
)
def test_build_zone_happy_path(
    mode: str, lists: tuple[str, ...], expected_lists: tuple[str, ...]
) -> None:
    zone = _build(name="office", networks=("192.0.2.0/24",), mode=mode, lists=lists)

    assert zone == ZoneDefinition(
        name="office",
        networks=(_net("192.0.2.0/24"),),
        mode=mode,
        lists=expected_lists,
    )


def test_build_zone_refuses_unknown_list() -> None:
    with pytest.raises(ZoneError) as err:
        _build(lists=("no_such_list",))

    assert err.value.code == "unknown_list_name"


@pytest.mark.parametrize(
    "lists",
    [
        ("deny_default", "deny_default"),
        ("deny_default", 5),
        ("deny_default", None),
        "deny_default",
        None,
    ],
)
def test_build_zone_refuses_bad_list_values(lists: Any) -> None:
    with pytest.raises(ZoneError) as err:
        build_zone(
            "office",
            ["192.0.2.0/24"],
            "filter",
            lists,
            definitions=DEFINITIONS,
            others=(),
        )

    assert err.value.code == "unknown_list_name"


@pytest.mark.parametrize(
    "lists",
    [
        (),
        ("deny_default",),
        ("allow_default",),
        ("allow_quarantine", "allow_default"),
    ],
)
def test_allowlist_only_needs_exact_only_allow_lists(lists: tuple[str, ...]) -> None:
    with pytest.raises(ZoneError) as err:
        _build(mode="allowlist_only", lists=lists)

    assert err.value.code == "allowlist_only_lists"


@pytest.mark.parametrize("mode", ["block", "", None, 5, ["filter"]])
def test_build_zone_refuses_unknown_mode(mode: Any) -> None:
    with pytest.raises(ZoneError) as err:
        _build(mode=mode)

    assert err.value.code == "invalid_zone_mode"


def test_build_zone_refuses_bad_name_and_network() -> None:
    with pytest.raises(ZoneError) as name_err:
        _build(name="Bad Name")
    with pytest.raises(ZoneError) as network_err:
        _build(networks=("0.0.0.0/0",))

    assert name_err.value.code == "invalid_zone_name"
    assert network_err.value.code == "invalid_network"


@pytest.mark.parametrize(
    "networks",
    [
        ("192.0.2.0/24",),
        ("192.0.2.128/25",),
        ("192.0.2.10",),
    ],
)
def test_overlap_with_another_zone_is_refused(networks: tuple[str, ...]) -> None:
    other = _zone("lab", ["192.0.2.0/24"])

    with pytest.raises(ZoneError) as err:
        _build(name="north", networks=networks, others=(other,))

    assert err.value.code == "zone_overlap"


def test_non_overlapping_zone_is_accepted() -> None:
    other = _zone("lab", ["192.0.2.0/24"])

    zone = _build(name="north", networks=("198.51.100.0/24",), others=(other,))

    assert zone.name == "north"


# --- read_zones -------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, 5, "office", ["office"], True])
def test_read_zones_ignores_a_value_that_is_not_a_mapping(raw: Any) -> None:
    assert read_zones({CONF_ZONES: raw}, DEFINITIONS) == {}


def test_read_zones_without_the_key() -> None:
    assert read_zones({}, DEFINITIONS) == {}


def test_read_zones_keeps_valid_and_drops_invalid() -> None:
    stored = {
        "office": {"networks": ["192.0.2.0/24"], "mode": "filter", "lists": []},
        "Bad Name": {"networks": ["192.0.2.0/24"], "mode": "filter", "lists": []},
        "lab": "not a mapping",
        "north": {"networks": ["198.51.100.0/24"], "mode": "block", "lists": []},
        "south": {"networks": [], "mode": "filter", "lists": []},
    }

    zones = read_zones({CONF_ZONES: stored}, DEFINITIONS)

    assert list(zones) == ["office"]
    assert zones["office"].networks == (_net("192.0.2.0/24"),)


def test_read_zones_drops_a_second_overlapping_zone() -> None:
    stored = {
        "office": {"networks": ["192.0.2.0/24"], "mode": "filter", "lists": []},
        "lab": {"networks": ["192.0.2.128/25"], "mode": "filter", "lists": []},
        "north": {"networks": ["198.51.100.0/24"], "mode": "filter", "lists": []},
    }

    zones = read_zones({CONF_ZONES: stored}, DEFINITIONS)

    assert list(zones) == ["office", "north"]


def test_read_zones_truncates_at_the_maximum() -> None:
    stored = {
        f"z{index}": {
            "networks": [f"203.0.113.{index}"],
            "mode": "filter",
            "lists": [],
        }
        for index in range(MAX_ZONES + 4)
    }

    zones = read_zones({CONF_ZONES: stored}, DEFINITIONS)

    assert len(zones) == MAX_ZONES
    assert list(zones) == [f"z{index}" for index in range(MAX_ZONES)]


def test_read_zones_never_raises_on_garbage() -> None:
    stored = {
        None: None,
        5: 5,
        "a": None,
        "b": {"networks": None, "mode": None},
        "c": {"networks": [None], "mode": 1, "lists": 5},
        "d": {"networks": [["x"]], "mode": "filter", "lists": None},
        "e": {"networks": ["192.0.2.1"], "mode": "filter", "lists": [{}]},
        "f": {"networks": 7, "mode": {"x": 1}, "lists": "deny_default"},
        "g": {"networks": ["192.0.2.1"], "mode": "filter", "lists": [None]},
    }

    assert read_zones({CONF_ZONES: stored}, DEFINITIONS) == {}


def test_dropped_zone_is_logged_without_its_name_or_networks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stored = {
        "sneaky_zone_name": {
            "networks": ["198.51.100.77"],
            "mode": "bogus",
            "lists": [],
        },
    }

    with caplog.at_level(logging.ERROR):
        zones = read_zones({CONF_ZONES: stored}, DEFINITIONS)

    assert zones == {}
    assert "invalid_zone_mode" in caplog.text
    assert "sneaky_zone_name" not in caplog.text
    assert "198.51.100.77" not in caplog.text


# --- zone_for_address -------------------------------------------------------


@pytest.fixture
def zones() -> dict[str, ZoneDefinition]:
    return {
        "office": _zone("office", ["192.0.2.0/24"]),
        "lab": _zone("lab", ["198.51.100.0/24"]),
        "v6": _zone("v6", ["2001:db8::/32"]),
    }


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("192.0.2.10", "office"),
        ("198.51.100.200", "lab"),
        ("2001:db8::5", "v6"),
        ("203.0.113.5", None),
        ("2001:db9::5", None),
    ],
)
def test_zone_for_address_matches(
    zones: dict[str, ZoneDefinition], address: str, expected: str | None
) -> None:
    assert zone_for_address(address, zones) == expected


@pytest.mark.parametrize("address", [None, "", "not-an-ip", 5, "192.0.2.0/24", b"x"])
def test_zone_for_address_ignores_garbage(
    zones: dict[str, ZoneDefinition], address: Any
) -> None:
    assert zone_for_address(address, zones) is None


def test_zone_for_address_matches_ipv4_mapped_ipv6(
    zones: dict[str, ZoneDefinition],
) -> None:
    assert zone_for_address("::ffff:192.0.2.5", zones) == "office"
    assert zone_for_address("::ffff:203.0.113.5", zones) is None


def test_zone_for_address_without_zones() -> None:
    assert zone_for_address("192.0.2.10", {}) is None


# --- render_blocky_config ---------------------------------------------------

ALLOW_URL = f"{BASE_URL}/api/ha_blocky/lists/token-placeholder/allow_quarantine.txt"
DENY_URL = f"{BASE_URL}/api/ha_blocky/lists/token-placeholder/deny_default.txt"
URLS = {"allow_quarantine": ALLOW_URL, "deny_default": DENY_URL}


def test_render_without_zones_is_empty() -> None:
    assert render_blocky_config({}, URLS, DEFINITIONS) == ""


def test_render_fragment_parses_and_maps_networks() -> None:
    zones = {
        "office": _zone(
            "office", ["192.0.2.0/24", "2001:db8::/32"], "filter", ("deny_default",)
        ),
        "lab": _zone(
            "lab", ["198.51.100.0/24"], "allowlist_only", ("allow_quarantine",)
        ),
        "no": _zone("no", ["203.0.113.0/25"], "filter", ("deny_default",)),
        "123": _zone("123", ["203.0.113.128/25"], "learning"),
    }

    fragment = render_blocky_config(zones, URLS, DEFINITIONS)
    parsed = yaml.safe_load(fragment)

    assert parsed["blocking"]["clientGroupsBlock"] == {
        "192.0.2.0/24": ["office"],
        "2001:db8::/32": ["office"],
        "198.51.100.0/24": ["lab"],
        "203.0.113.0/25": ["no"],
        "203.0.113.128/25": ["123"],
    }
    assert parsed["blocking"]["allowlists"] == {"lab": [ALLOW_URL]}
    assert parsed["blocking"]["denylists"] == {"office": [DENY_URL], "no": [DENY_URL]}


def test_render_keeps_zone_names_that_yaml_would_change() -> None:
    zones = {
        "no": _zone("no", ["203.0.113.0/25"], "filter", ("deny_default",)),
        "123": _zone("123", ["203.0.113.128/25"], "filter", ("deny_default",)),
    }

    parsed = yaml.safe_load(render_blocky_config(zones, URLS, DEFINITIONS))

    assert parsed["blocking"]["clientGroupsBlock"]["203.0.113.0/25"] == ["no"]
    assert parsed["blocking"]["clientGroupsBlock"]["203.0.113.128/25"] == ["123"]
    assert parsed["blocking"]["denylists"] == {"no": [DENY_URL], "123": [DENY_URL]}
    assert all(isinstance(name, str) for name in parsed["blocking"]["denylists"])


def test_render_omits_empty_sections() -> None:
    zones = {"learn": _zone("learn", ["198.51.100.0/24"], "learning")}

    parsed = yaml.safe_load(render_blocky_config(zones, URLS, DEFINITIONS))

    assert set(parsed["blocking"]) == {"clientGroupsBlock"}
    assert parsed["blocking"]["clientGroupsBlock"] == {"198.51.100.0/24": ["learn"]}


def test_render_skips_lists_without_an_address() -> None:
    zones = {
        "lab": _zone(
            "lab", ["198.51.100.0/24"], "allowlist_only", ("allow_quarantine",)
        )
    }

    parsed = yaml.safe_load(render_blocky_config(zones, {}, DEFINITIONS))

    assert set(parsed["blocking"]) == {"clientGroupsBlock"}


# --- Options flow -----------------------------------------------------------


async def _setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    options: dict[str, Any],
) -> MockConfigEntry:
    assert await async_setup_component(hass, "http", {})
    aioclient_mock.get(STATUS_URL, json=ENABLED)
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_URL: BASE_URL}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _configure(
    hass: HomeAssistant, flow_id: str, data: dict[str, Any]
) -> dict[str, Any]:
    return await hass.config_entries.options.async_configure(flow_id, data)


async def _open_zone_form(
    hass: HomeAssistant, entry: MockConfigEntry, choice: str
) -> dict[str, Any]:
    result = await open_options_step(hass, entry, "zones")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zones"
    result = await _configure(hass, result["flow_id"], {"zone": choice})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zone_edit"
    return result


async def test_add_a_zone(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(hass, aioclient_mock, dict(LIST_OPTIONS))
    form = await _open_zone_form(hass, entry, "add-new")

    result = await _configure(
        hass,
        form["flow_id"],
        {
            "name": "office",
            "networks": ["192.0.2.0/24"],
            "mode": "filter",
            "lists": ["deny_default"],
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ZONES] == {
        "office": {
            "networks": ["192.0.2.0/24"],
            "mode": "filter",
            "lists": ["deny_default"],
        }
    }
    assert entry.options[CONF_LISTS] == LIST_OPTIONS[CONF_LISTS]
    assert entry.options[CONF_LIST_NETWORKS] == LOOPBACK


async def test_edit_a_zone(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(
        hass, aioclient_mock, {**LIST_OPTIONS, CONF_ZONES: OFFICE_ONLY}
    )
    form = await _open_zone_form(hass, entry, "office")
    suggested = {
        str(key): (key.description or {}).get("suggested_value")
        for key in form["data_schema"].schema
    }
    assert suggested["networks"] == ["192.0.2.0/24"]
    assert suggested["mode"] == "filter"

    result = await _configure(
        hass,
        form["flow_id"],
        {"networks": ["192.0.2.0/25"], "mode": "learning", "lists": ["deny_default"]},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ZONES] == {
        "office": {
            "networks": ["192.0.2.0/25"],
            "mode": "learning",
            "lists": ["deny_default"],
        }
    }


async def test_delete_a_zone(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(
        hass, aioclient_mock, {**LIST_OPTIONS, CONF_ZONES: ZONE_OPTIONS[CONF_ZONES]}
    )
    form = await _open_zone_form(hass, entry, "lab")

    result = await _configure(
        hass,
        form["flow_id"],
        {
            "networks": ["198.51.100.0/24"],
            "mode": "learning",
            "lists": [],
            "delete": True,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert list(entry.options[CONF_ZONES]) == ["office"]


@pytest.mark.parametrize(
    ("choice", "user_input", "errors"),
    [
        (
            "add-new",
            {
                "name": "Bad Name",
                "networks": ["198.51.100.0/24"],
                "mode": "filter",
                "lists": [],
            },
            {"name": "invalid_zone_name"},
        ),
        (
            "add-new",
            {
                "name": "office",
                "networks": ["198.51.100.0/24"],
                "mode": "filter",
                "lists": [],
            },
            {"name": "duplicate_zone_name"},
        ),
        (
            "add-new",
            {"name": "lab", "networks": ["nonsense"], "mode": "filter", "lists": []},
            {"networks": "invalid_network"},
        ),
        (
            "add-new",
            {
                "name": "lab",
                "networks": ["192.0.2.128/25"],
                "mode": "filter",
                "lists": [],
            },
            {"networks": "zone_overlap"},
        ),
        (
            "add-new",
            {
                "name": "lab",
                "networks": ["198.51.100.0/24"],
                "mode": "allowlist_only",
                "lists": [],
            },
            {"lists": "allowlist_only_lists"},
        ),
        (
            "add-new",
            {
                "name": "lab",
                "networks": ["198.51.100.0/24"],
                "mode": "allowlist_only",
                "lists": ["allow_default"],
            },
            {"lists": "allowlist_only_lists"},
        ),
        (
            "add-new",
            {
                "name": "lab",
                "networks": ["198.51.100.0/24"],
                "mode": "allowlist_only",
                "lists": ["deny_default"],
            },
            {"lists": "allowlist_only_lists"},
        ),
        (
            "office",
            {"networks": ["0.0.0.0/0"], "mode": "filter", "lists": []},
            {"networks": "invalid_network"},
        ),
    ],
)
async def test_zone_form_refuses_bad_input(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    choice: str,
    user_input: dict[str, Any],
    errors: dict[str, str],
) -> None:
    entry = await _setup(
        hass, aioclient_mock, {**LIST_OPTIONS, CONF_ZONES: OFFICE_ONLY}
    )
    form = await _open_zone_form(hass, entry, choice)

    result = await _configure(hass, form["flow_id"], user_input)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zone_edit"
    assert result["errors"] == errors
    assert entry.options[CONF_ZONES] == OFFICE_ONLY


async def test_zone_form_refuses_a_seventeenth_zone(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    stored = {
        f"z{index}": {"networks": [f"203.0.113.{index}"], "mode": "filter", "lists": []}
        for index in range(MAX_ZONES)
    }
    entry = await _setup(hass, aioclient_mock, {**LIST_OPTIONS, CONF_ZONES: stored})
    form = await _open_zone_form(hass, entry, "add-new")

    result = await _configure(
        hass,
        form["flow_id"],
        {
            "name": "extra",
            "networks": ["198.51.100.0/24"],
            "mode": "filter",
            "lists": [],
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "too_many_zones"}
    assert entry.options[CONF_ZONES] == stored


@pytest.mark.parametrize(
    ("stored_zone", "new_lists", "new_exact"),
    [
        # A zone still links a deny list that the change would remove.
        (
            {"networks": ["192.0.2.0/24"], "mode": "filter", "lists": ["deny_default"]},
            [("allow_default", "allow"), ("allow_quarantine", "allow")],
            [],
        ),
        # An allowlist-only zone needs exact-only lists; un-marking one refuses.
        (
            {
                "networks": ["192.0.2.0/24"],
                "mode": "allowlist_only",
                "lists": ["allow_quarantine"],
            },
            [
                ("allow_default", "allow"),
                ("allow_quarantine", "allow"),
                ("deny_default", "deny"),
            ],
            [],
        ),
    ],
)
async def test_list_change_refused_while_a_zone_uses_the_list(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    stored_zone: dict[str, Any],
    new_lists: list[tuple[str, str]],
    new_exact: list[str],
) -> None:
    stored = {"office": stored_zone}
    entry = await _setup(hass, aioclient_mock, {**LIST_OPTIONS, CONF_ZONES: stored})
    result = await open_options_step(hass, entry, "lists")

    allow = [name for name, kind in new_lists if kind == "allow"]
    deny = [name for name, kind in new_lists if kind == "deny"]
    result = await _configure(
        hass,
        result["flow_id"],
        {
            CONF_ALLOW_LISTS: allow,
            CONF_DENY_LISTS: deny,
            CONF_EXACT_ONLY_LISTS: new_exact,
            CONF_LIST_NETWORKS: LOOPBACK,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "lists"
    assert result["errors"] == {"base": "list_in_use"}
    assert entry.options[CONF_ZONES] == stored


async def test_zone_config_shows_the_fragment(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(
        hass,
        aioclient_mock,
        {**LIST_OPTIONS, CONF_ZONES: ZONE_OPTIONS[CONF_ZONES]},
    )
    before = dict(entry.options)

    result = await open_options_step(hass, entry, "zone_config")

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zone_config"
    config = result["description_placeholders"]["config"]
    assert config.startswith("```yaml\n")
    assert "clientGroupsBlock" in config
    assert "192.0.2.0/24" in config
    assert "office" in config and "lab" in config

    result = await _configure(hass, result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "zone_config_closed"
    assert dict(entry.options) == before


async def test_zone_config_without_zones_shows_a_dash(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(hass, aioclient_mock, dict(LIST_OPTIONS))

    result = await open_options_step(hass, entry, "zone_config")

    assert result["description_placeholders"]["config"] == "-"


# --- Query log counts per client (database) --------------------------------


@pytest.fixture
def clients(tmp_path: Path) -> db.QueryLogDatabase:
    url = make_log(
        tmp_path / "clients.db",
        [
            db_row("example.com", client="192.0.2.10"),
            db_row("ads.example", client="192.0.2.10", response_type="BLOCKED"),
            db_row("example.com", client="192.0.2.11", duration_ms=30),
            db_row("ads.example", client="192.0.2.11", response_type="BLOCKED"),
            db_row("ads.example", client="192.0.2.11", response_type="BLOCKED"),
            db_row("old.example", client="192.0.2.99", age=timedelta(days=2)),
            db_row("x.example", client="198.51.100.5"),
        ],
    )
    log = db.QueryLogDatabase(url)
    yield log
    log.close()


def test_client_counts_totals_and_blocked(clients: db.QueryLogDatabase) -> None:
    since = NOW - timedelta(hours=1)

    assert clients.client_counts(since) == [
        ("192.0.2.11", 3, 2),
        ("192.0.2.10", 2, 1),
        ("198.51.100.5", 1, 0),
    ]


def test_client_counts_respects_since(clients: db.QueryLogDatabase) -> None:
    assert clients.client_counts(NOW - timedelta(days=3)) == [
        ("192.0.2.11", 3, 2),
        ("192.0.2.10", 2, 1),
        ("192.0.2.99", 1, 0),
        ("198.51.100.5", 1, 0),
    ]
    assert clients.client_counts(NOW + timedelta(hours=1)) == []


@pytest.mark.parametrize(("limit", "count"), [(2, 2), (1, 1), (0, 1)])
def test_client_counts_respects_limit(
    clients: db.QueryLogDatabase, limit: int, count: int
) -> None:
    counts = clients.client_counts(NOW - timedelta(hours=1), limit=limit)

    assert len(counts) == count
    assert counts[0] == ("192.0.2.11", 3, 2)


# --- Statistics and sensors -------------------------------------------------


def _zone_sensor(
    hass: HomeAssistant, entry: MockConfigEntry, zone: str, suffix: str
) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_zone_{zone}_{suffix}"
    )
    assert entity_id is not None, (zone, suffix)
    return entity_id


def _zone_state(
    hass: HomeAssistant, entry: MockConfigEntry, zone: str, suffix: str
) -> str:
    return hass.states.get(_zone_sensor(hass, entry, zone, suffix)).state


async def test_zone_counts_follow_the_networks(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
) -> None:
    add_rows(
        log_url,
        [
            log_row("example.com", client="192.0.2.10"),
            log_row("ads.example", client="192.0.2.11", response_type="BLOCKED"),
            log_row("example.com", client="2001:db8::5"),
            log_row("example.com", client="203.0.113.50"),
            log_row("ads.example", client="203.0.113.50", response_type="BLOCKED"),
        ],
    )
    entry = await _setup(hass, aioclient_mock, {**DB_OPTIONS, **ZONE_OPTIONS})

    assert _zone_state(hass, entry, "office", "queries_24h") == "3"
    assert _zone_state(hass, entry, "office", "blocked_24h") == "1"
    # A zone without traffic reports zero, not unknown.
    assert _zone_state(hass, entry, "lab", "queries_24h") == "0"
    assert _zone_state(hass, entry, "lab", "blocked_24h") == "0"

    add_rows(log_url, [log_row("example.com", client="198.51.100.9")])
    await _poll(hass, freezer, STATS_INTERVAL)

    assert _zone_state(hass, entry, "lab", "queries_24h") == "1"
    assert _zone_state(hass, entry, "office", "queries_24h") == "3"


async def test_zone_sensors_have_stable_unique_ids(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, log_url: URL
) -> None:
    entry = await _setup(hass, aioclient_mock, {**DB_OPTIONS, **ZONE_OPTIONS})

    registry = er.async_get(hass)
    zone_entries = [
        registered
        for registered in er.async_entries_for_config_entry(registry, entry.entry_id)
        if "_zone_" in registered.unique_id
    ]
    assert sorted(item.unique_id for item in zone_entries) == sorted(
        f"{entry.entry_id}_zone_{zone}_{suffix}"
        for zone in ("office", "lab")
        for suffix in ("queries_24h", "blocked_24h")
    )


async def test_no_client_counts_without_zones(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []
    original = db.QueryLogDatabase.client_counts

    def spy(self: db.QueryLogDatabase, since: Any, limit: int = 5000) -> Any:
        calls.append(since)
        return original(self, since, limit)

    monkeypatch.setattr(db.QueryLogDatabase, "client_counts", spy)

    entry = await _setup(hass, aioclient_mock, dict(DB_OPTIONS))

    assert entry.runtime_data.stats is not None
    assert calls == []


async def test_zone_sensors_of_a_deleted_zone_are_removed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, log_url: URL
) -> None:
    entry = await _setup(hass, aioclient_mock, {**DB_OPTIONS, **ZONE_OPTIONS})
    registry = er.async_get(hass)
    assert registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_zone_lab_queries_24h"
    )

    hass.config_entries.async_update_entry(
        entry,
        options={
            **DB_OPTIONS,
            CONF_ZONES: {"office": ZONE_OPTIONS[CONF_ZONES]["office"]},
        },
    )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    for suffix in ("queries_24h", "blocked_24h"):
        assert (
            registry.async_get_entity_id(
                "sensor", DOMAIN, f"{entry.entry_id}_zone_lab_{suffix}"
            )
            is None
        )
        assert (
            registry.async_get_entity_id(
                "sensor", DOMAIN, f"{entry.entry_id}_zone_office_{suffix}"
            )
            is not None
        )


# --- WebSocket commands -----------------------------------------------------


async def _command(ws: Any, message_id: int, /, **message: Any) -> dict[str, Any]:
    await ws.send_json({"id": message_id, **message})
    return await ws.receive_json()


async def test_config_command_lists_zones_without_networks(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
) -> None:
    await _setup(hass, aioclient_mock, {**LIST_OPTIONS, **ZONE_OPTIONS})
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=f"{DOMAIN}/config")

    assert response["success"]
    zones = response["result"]["entries"][0]["zones"]
    assert zones == [
        {"name": "office", "mode": "filter", "lists": []},
        {"name": "lab", "mode": "learning", "lists": []},
    ]
    dumped = json.dumps(response)
    assert "networks" not in dumped
    assert "192.0.2.0" not in dumped
    assert "198.51.100.0" not in dumped
    assert "2001:db8" not in dumped


async def test_query_log_rows_carry_the_zone(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    hass_ws_client: WebSocketGenerator,
) -> None:
    add_rows(
        log_url,
        [
            log_row("example.com", client="192.0.2.10"),
            log_row("example.com", client="198.51.100.7"),
            log_row("example.com", client="203.0.113.50"),
        ],
    )
    await _setup(hass, aioclient_mock, {**DB_OPTIONS, **ZONE_OPTIONS})
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=f"{DOMAIN}/query_log")

    assert response["success"]
    pairs = {(row["client"], row["zone"]) for row in response["result"]["rows"]}
    assert pairs == {
        ("192.0.2.10", "office"),
        ("198.51.100.7", "lab"),
        ("203.0.113.50", None),
    }


# --- Diagnostics ------------------------------------------------------------


async def test_diagnostics_never_show_a_zone_network(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, log_url: URL
) -> None:
    add_rows(log_url, [log_row("example.com", client="192.0.2.10")])
    entry = await _setup(hass, aioclient_mock, {**DB_OPTIONS, **ZONE_OPTIONS})

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(diagnostics, default=str)

    for network in ("192.0.2.0/24", "2001:db8::/32", "198.51.100.0/24", "192.0.2.10"):
        assert network not in dumped, network
    assert diagnostics["zones"] == [
        {"name": "office", "mode": "filter", "lists": [], "networks": 2},
        {"name": "lab", "mode": "learning", "lists": [], "networks": 1},
    ]


# --- Card (static checks) ---------------------------------------------------


def test_card_still_writes_no_markup_and_shows_zones_as_text() -> None:
    assert "innerHTML" not in CARD_SOURCE
    assert "textContent" in CARD_SOURCE or "text:" in CARD_SOURCE
    # The zone sits dimmed under the name or the address of a client.
    assert ".sub" in CARD_SOURCE
    assert "row.zone" in CARD_SOURCE
    assert 'className: "sub"' in CARD_SOURCE
