"""Tests for the IP and name filters of the query log and the client list."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator
from sqlalchemy.engine import URL

from custom_components.ha_blocky import db
from custom_components.ha_blocky import websocket_levels as levels_module
from custom_components.ha_blocky.client_names import addresses_with_name
from custom_components.ha_blocky.const import (
    CONF_CLIENTS,
    DOMAIN,
    MAX_NAME_MATCHES,
)
from custom_components.ha_blocky.validation import (
    InvalidIpFilterError,
    parse_ip_filter,
)

from .test_card import _command, _setup
from .test_db import add_rows
from .test_stats import DB_OPTIONS, log_row

LOG = f"{DOMAIN}/query_log"
SET = f"{DOMAIN}/set_client_name"

# --- The IP filter parser ----------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", (None, None)),
        ("   ", (None, None)),
        ("192.0.2.10", ("192.0.2.10", None)),
        (" 192.0.2.10 ", ("192.0.2.10", None)),
        ("2001:DB8::1", ("2001:db8::1", None)),
        ("::ffff:192.0.2.10", ("192.0.2.10", None)),
        ("192.0.2.", (None, "192.0.2.")),
        ("2.10", (None, "2.10")),
        ("db8:", (None, "db8:")),
        ("192.0.2.256", (None, "192.0.2.256")),
    ],
)
def test_ip_filter_is_exact_for_a_whole_address_and_a_fragment_otherwise(
    value: str, expected: tuple[str | None, str | None]
) -> None:
    assert parse_ip_filter(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "192.0.2.x",
        "g",
        "1 2",
        "%",
        "_",
        "192.0.2.4'; --",
        "192.0.2.1\nx",
        "a" * 46,
        "١٢٣",  # Arabic-Indic digits are not 0-9
        None,
        10,
        ["1"],
    ],
)
def test_ip_filter_refuses_everything_but_address_characters(value: Any) -> None:
    with pytest.raises(InvalidIpFilterError):
        parse_ip_filter(value)


def test_the_longest_filter_is_45_characters() -> None:
    assert parse_ip_filter("a" * 45) == (None, "a" * 45)


# --- The name resolution -----------------------------------------------------


def test_names_match_as_a_case_insensitive_contains_sorted() -> None:
    names = {
        "192.0.2.12": "Kids LAPTOP",
        "192.0.2.10": "Laptop",
        "192.0.2.11": "Phone",
        "198.51.100.1": "ЛАПТОП",
    }
    assert addresses_with_name(names, "lap") == ["192.0.2.10", "192.0.2.12"]
    assert addresses_with_name(names, "лапт") == ["198.51.100.1"]
    assert addresses_with_name(names, "none") == []


def test_a_name_filter_expands_to_at_most_256_addresses() -> None:
    # Only the cap matters here, not that the addresses are example ones.
    names = {f"x{index:04d}": "Cam" for index in range(300)}
    found = addresses_with_name(names, "cam")
    assert len(found) == MAX_NAME_MATCHES == 256
    assert found == sorted(names)[:256]


# --- The database ------------------------------------------------------------


def _since() -> Any:
    return (dt_util.utcnow() - timedelta(hours=24)).replace(tzinfo=None)


def test_pattern_characters_in_a_fragment_match_literally(log_url: URL) -> None:
    add_rows(
        log_url,
        [
            log_row("a.example.com", client="192.0.2.10"),
            log_row("b.example.com", client="2001:db8::10"),
        ],
    )
    database = db.QueryLogDatabase(log_url)

    assert database.query_log(since=_since(), client_part="%") == []
    assert database.query_log(since=_since(), client_part="_") == []
    assert database.query_log(since=_since(), client_part="2.1_") == []
    found = database.query_log(since=_since(), client_part="db8:")
    assert [row["domain"] for row in found] == ["b.example.com"]


def test_the_database_combines_every_client_filter_with_and(log_url: URL) -> None:
    add_rows(
        log_url,
        [
            log_row("a.example.com", client="192.0.2.1"),
            log_row("b.example.com", client="192.0.2.10"),
            log_row("c.example.com", client="192.0.2.100"),
        ],
    )
    database = db.QueryLogDatabase(log_url)
    since = _since()

    def domains(**filters: Any) -> list[str]:
        return [row["domain"] for row in database.query_log(since=since, **filters)]

    assert domains(client="192.0.2.1") == ["a.example.com"]
    assert domains(client_part="192.0.2.1") == [
        "c.example.com",
        "b.example.com",
        "a.example.com",
    ]
    assert domains(addresses=["192.0.2.10", "192.0.2.100"]) == [
        "c.example.com",
        "b.example.com",
    ]
    assert domains(client_part="2.10", addresses=["192.0.2.10", "192.0.2.1"]) == [
        "b.example.com"
    ]
    assert domains(client_part="2.10", addresses=["192.0.2.1"]) == []
    # An empty set matches nothing, and does not reach the database.
    with patch.object(database, "_run", side_effect=AssertionError):
        assert database.query_log(since=since, addresses=[]) == []


# --- The command -------------------------------------------------------------


async def _name(client: Any, message_id: int, ip: str, name: str) -> None:
    response = await _command(client, message_id, type=SET, ip=ip, name=name)
    assert response["success"], response


def _domains(response: dict[str, Any]) -> list[str]:
    assert response["success"], response
    return [row["domain"] for row in response["result"]["rows"]]


@pytest.fixture
async def log_client(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> Any:
    add_rows(
        log_url,
        [
            log_row("a.example.com", client="192.0.2.1"),
            log_row("b.example.com", client="192.0.2.10"),
            log_row("c.example.com", client="192.0.2.100"),
            log_row("d.example.com", client="192.0.2.12"),
            log_row("e.example.com", client="2001:db8::10"),
        ],
    )
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    await _name(client, 1, "192.0.2.10", "Laptop Anna")
    await _name(client, 2, "192.0.2.12", "Laptop Ben")
    await _name(client, 3, "192.0.2.1", "Phone")
    return client


pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_a_whole_address_matches_exactly(log_client: Any) -> None:
    assert _domains(await _command(log_client, 11, type=LOG, ip="192.0.2.1")) == [
        "a.example.com"
    ]


async def test_anything_else_is_a_literal_fragment(log_client: Any) -> None:
    assert _domains(await _command(log_client, 12, type=LOG, ip="2.10")) == [
        "c.example.com",
        "b.example.com",
    ]
    assert _domains(await _command(log_client, 13, type=LOG, ip="db8:")) == [
        "e.example.com"
    ]
    assert _domains(await _command(log_client, 14, type=LOG, ip="")) == [
        "e.example.com",
        "d.example.com",
        "c.example.com",
        "b.example.com",
        "a.example.com",
    ]


@pytest.mark.parametrize("value", ["%", "_", "192.0.2.x", "zzz-secret", "a" * 46, 5])
async def test_a_bad_ip_filter_is_refused_with_a_stable_code(
    log_client: Any, value: Any
) -> None:
    response = await _command(log_client, 11, type=LOG, ip=value)

    assert response["success"] is False
    assert response["error"]["code"] == "invalid_ip"
    # The rejected value is never repeated.
    for text in (value, "zzz-secret"):
        if isinstance(text, str) and len(text) > 2:
            assert text not in json.dumps(response)


async def test_a_name_is_resolved_to_addresses(log_client: Any) -> None:
    assert _domains(await _command(log_client, 11, type=LOG, name="laptop")) == [
        "d.example.com",
        "b.example.com",
    ]
    assert _domains(await _command(log_client, 12, type=LOG, name="ANNA")) == [
        "b.example.com"
    ]
    assert _domains(await _command(log_client, 13, type=LOG, name="  phone ")) == [
        "a.example.com"
    ]


async def test_a_name_nobody_has_asks_the_database_nothing(log_client: Any) -> None:
    with patch.object(db.QueryLogDatabase, "query_log", side_effect=AssertionError):
        response = await _command(log_client, 11, type=LOG, name="nobody")

    assert response["success"]
    assert response["result"] == {
        "rows": [],
        "has_more": False,
        "next_before_id": None,
    }


async def test_ip_and_name_are_anded(log_client: Any) -> None:
    assert (
        _domains(
            await _command(log_client, 11, type=LOG, ip="192.0.2.1", name="laptop")
        )
        == []
    )
    assert _domains(
        await _command(log_client, 12, type=LOG, ip="2.1", name="laptop")
    ) == ["d.example.com", "b.example.com"]
    assert _domains(
        await _command(log_client, 13, type=LOG, ip="192.0.2.10", name="laptop")
    ) == ["b.example.com"]


@pytest.mark.parametrize("value", ["a\x07b", "x" * 65, 5, ["a"]])
async def test_a_bad_name_is_refused_and_never_echoed(
    log_client: Any, value: Any
) -> None:
    response = await _command(log_client, 11, type=LOG, name=value)

    assert response["success"] is False
    assert response["error"]["code"] == "invalid_name"
    assert "x" * 65 not in json.dumps(response)


async def test_the_filters_work_with_paging_and_the_other_filters(
    log_client: Any,
) -> None:
    page = (await _command(log_client, 12, type=LOG, ip="2.1", limit=1))["result"]
    assert [row["domain"] for row in page["rows"]] == ["d.example.com"]
    assert page["has_more"] is True
    rest = (
        await _command(
            log_client,
            13,
            type=LOG,
            ip="2.1",
            limit=5,
            before_id=page["next_before_id"],
            domain="example.com",
            status="allowed",
        )
    )["result"]
    assert [row["domain"] for row in rest["rows"]] == [
        "c.example.com",
        "b.example.com",
        "a.example.com",
    ]


async def test_the_old_client_field_is_gone(log_client: Any) -> None:
    response = await _command(log_client, 11, type=LOG, client="192.0.2.1")

    assert response["success"] is False


# --- The client list of the Settings tab ------------------------------------


def _clients(response: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assert response["success"], response
    return {item["address"]: item for item in response["result"]["clients"]}


async def test_the_client_list_is_seen_plus_leveled_plus_named(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    add_rows(
        log_url,
        [
            log_row("a.example.com", client="192.0.2.1"),
            log_row("b.example.com", client="192.0.2.2"),
        ],
    )
    entry = await _setup(
        hass,
        aioclient_mock,
        {**DB_OPTIONS, CONF_CLIENTS: {"203.0.113.7": {"level": "restricted"}}},
    )
    hass.states.async_set(
        "device_tracker.tv", "home", {"ip": "192.0.2.2", "friendly_name": "TV"}
    )
    # A tracker whose address nobody queried from is not listed.
    hass.states.async_set(
        "device_tracker.idle", "home", {"ip": "192.0.2.99", "friendly_name": "Idle"}
    )
    client = await hass_ws_client(hass)
    await _name(client, 1, "198.51.100.5", "Printer")
    await _name(client, 2, "192.0.2.1", "Laptop")

    clients = _clients(await _command(client, 3, type=f"{DOMAIN}/levels"))

    assert set(clients) == {"192.0.2.1", "192.0.2.2", "203.0.113.7", "198.51.100.5"}
    assert clients["192.0.2.1"]["name_source"] == "manual"
    assert clients["192.0.2.1"]["client_name"] == "Laptop"
    assert clients["192.0.2.2"]["name_source"] == "device"
    assert clients["192.0.2.2"]["client_name"] == "TV"
    # Named by hand but never seen: listed, with no queries and Standard level.
    printer = clients["198.51.100.5"]
    assert printer["queries"] == 0
    assert printer["level"] == "standard"
    assert printer["name_source"] == "manual"
    assert clients["203.0.113.7"]["name_source"] is None
    assert clients["203.0.113.7"]["level"] == "restricted"
    # Nothing was stored for the clients seen for the first time.
    assert entry.options[CONF_CLIENTS] == {"203.0.113.7": {"level": "restricted"}}


async def test_clients_with_a_level_or_a_name_are_listed_beyond_the_cap(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(levels_module, "MAX_CLIENTS_LISTED", 2)
    add_rows(
        log_url,
        [log_row("a.example.com", client=f"192.0.2.{n}") for n in range(1, 6)],
    )
    await _setup(
        hass,
        aioclient_mock,
        {**DB_OPTIONS, CONF_CLIENTS: {"203.0.113.7": {"level": "lockdown"}}},
    )
    client = await hass_ws_client(hass)
    await _name(client, 1, "198.51.100.5", "Printer")
    await _name(client, 2, "192.0.2.5", "Laptop")

    clients = _clients(await _command(client, 3, type=f"{DOMAIN}/levels"))

    # Three have a level or a name: all listed, and no other client fits.
    assert set(clients) == {"203.0.113.7", "198.51.100.5", "192.0.2.5"}
