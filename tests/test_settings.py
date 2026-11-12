"""Tests for the Settings tab commands: display preferences and options."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator
from sqlalchemy.engine import URL

from custom_components.ha_blocky.const import DOMAIN
from custom_components.ha_blocky.settings import (
    SettingError,
    apply_operational,
)

from .test_lists import LIST_OPTIONS
from .test_stats import DB_OPTIONS

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

BASE_URL = "http://blocky.example:4000"
ENABLED = {"enabled": True, "disabledGroups": [], "autoEnableInSec": 0}
GET = f"{DOMAIN}/settings"
SET = f"{DOMAIN}/set_settings"
STORE = f"{DOMAIN}.display"


async def _setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    assert await async_setup_component(hass, "http", {})
    aioclient_mock.get(f"{BASE_URL}/api/blocking/status", json=ENABLED)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_URL: BASE_URL},
        options={**DB_OPTIONS, **LIST_OPTIONS} if options is None else options,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _command(ws: Any, message_id: int, /, **message: Any) -> dict[str, Any]:
    await ws.send_json({"id": message_id, **message})
    return await ws.receive_json()


# --- Reading ----------------------------------------------------------------


async def test_settings_describe_display_and_options(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    entry = await _setup(
        hass, aioclient_mock, {**DB_OPTIONS, **LIST_OPTIONS, "tops_interval": 90}
    )
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=GET)

    assert response["success"]
    result = response["result"]
    assert result["display"] == {"colors": {}, "rows": None}
    described = result["entry"]
    assert described["entry_id"] == entry.entry_id
    assert described["has_query_log"] is True
    assert described["intervals"] == {
        "status_interval": {"value": 30, "min": 10, "max": 600, "default": 30},
        "stats_interval": {"value": 60, "min": 30, "max": 3600, "default": 60},
        "tops_interval": {"value": 90, "min": 30, "max": 3600, "default": 300},
    }
    assert described["report_existing_domains"] is False
    assert described["show_in_sidebar"] is True
    assert described["allow_lists"] == ["allow_default", "allow_quarantine"]
    assert described["deny_lists"] == ["deny_default"]
    assert described["exact_only_lists"] == ["allow_quarantine"]
    # Nothing secret and nothing of the connection or the list networks.
    dumped = json.dumps(result)
    assert DB_OPTIONS["db_password"] not in dumped
    assert "db.example" not in dumped
    assert "list_networks" not in dumped


async def test_settings_for_an_unknown_entry_fail_and_none_is_not_an_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    unknown = await _command(client, 1, type=GET, entry_id="nope")
    assert unknown["error"]["code"] == "entry_not_found"


# --- Display preferences ----------------------------------------------------


async def test_display_round_trip_reset_and_lower_case(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    hass_storage: dict[str, Any],
    log_url: URL,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    options_before = dict(entry.options)

    saved = await _command(
        client,
        1,
        type=SET,
        colors={"blocked": "#AA0000", "cached": "#00ff00"},
        rows=20,
    )
    assert saved["success"]
    assert saved["result"] == {
        "display_changed": True,
        "entry_changed": False,
        "reloading": False,
    }
    expected = {"colors": {"blocked": "#aa0000", "cached": "#00ff00"}, "rows": 20}
    read = await _command(client, 2, type=GET)
    assert read["result"]["display"] == expected
    assert hass_storage[STORE]["data"] == expected
    # Display preferences never touch the entry.
    assert entry.options == options_before

    # A partial update merges; null clears one colour and the rows.
    await _command(client, 3, type=SET, colors={"cached": None}, rows=None)
    read = await _command(client, 4, type=GET)
    assert read["result"]["display"] == {"colors": {"blocked": "#aa0000"}, "rows": None}

    await _command(client, 5, type=SET, colors={"blocked": None})
    read = await _command(client, 6, type=GET)
    assert read["result"]["display"] == {"colors": {}, "rows": None}


async def test_display_store_is_revalidated_on_load(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    hass_storage: dict[str, Any],
    log_url: URL,
) -> None:
    hass_storage[STORE] = {
        "version": 1,
        "key": STORE,
        "data": {
            "colors": {
                "resolved": "#112233",
                "cached": "red; background: url(x)",
                "blocked": "#12345",
                "local": 5,
                "evil": "#000000",
            },
            "rows": 7,
        },
    }
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    read = await _command(client, 1, type=GET)

    assert read["result"]["display"] == {
        "colors": {"resolved": "#112233"},
        "rows": None,
    }


@pytest.mark.parametrize(
    "value",
    [
        "red",
        "#fff",
        "#12345g",
        "#1234567",
        "#aabbcc\n",
        " #aabbcc",
        "#aabbcc;}",
        "rgb(1,2,3)",
        "",
        5,
        True,
        ["#aabbcc"],
        {"x": 1},
    ],
)
async def test_bad_colors_are_refused_without_echo(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    hass_storage: dict[str, Any],
    log_url: URL,
    value: Any,
) -> None:
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    response = await _command(
        client, 1, type=SET, colors={"blocked": value, "cached": "#00ff00"}
    )

    assert response["success"] is False
    assert response["error"] == {"code": "invalid_color", "message": "colors.blocked"}
    # Nothing was stored, not even the valid colour of the same message.
    assert STORE not in hass_storage


@pytest.mark.parametrize("rows", [0, 7, 21, "10", 10.5, True, [10]])
async def test_bad_rows_are_refused(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    rows: Any,
) -> None:
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=SET, rows=rows)

    assert response["error"] == {"code": "invalid_rows", "message": "rows"}


# --- Operational options ----------------------------------------------------


async def test_options_are_changed_partially_and_the_entry_reloads(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    before = dict(entry.options)

    response = await _command(
        client,
        1,
        type=SET,
        entry_id=entry.entry_id,
        stats_interval=90.0,
        status_interval=20,
        report_existing_domains=True,
        show_in_sidebar=False,
    )
    await hass.async_block_till_done()

    assert response["success"]
    assert response["result"] == {
        "display_changed": False,
        "entry_changed": True,
        "reloading": True,
    }
    assert entry.options == {
        **before,
        "stats_interval": 90,
        "status_interval": 20,
        "report_existing_domains": True,
        "show_in_sidebar": False,
    }
    # The connection, the database and the lists are exactly as they were.
    for key in (*DB_OPTIONS, "lists"):
        assert entry.options[key] == before[key]
    assert entry.runtime_data.coordinator.update_interval == timedelta(seconds=20)
    assert entry.runtime_data.stats.update_interval == timedelta(seconds=90)

    # The same values again change nothing and reload nothing.
    again = await _command(
        client, 2, type=SET, stats_interval=90, show_in_sidebar=False
    )
    assert again["result"]["entry_changed"] is False
    assert again["result"]["reloading"] is False


async def test_lists_are_defined_through_the_settings(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    entry = await _setup(hass, aioclient_mock, {"list_networks": ["192.0.2.0/24"]})
    client = await hass_ws_client(hass)

    response = await _command(
        client,
        1,
        type=SET,
        allow_lists=["allow_default", " allow_quarantine "],
        deny_lists=["deny_default"],
        exact_only_lists=["allow_quarantine"],
    )
    await hass.async_block_till_done()

    assert response["success"]
    assert entry.options == {
        "list_networks": ["192.0.2.0/24"],
        "lists": {
            "allow_default": {"type": "allow", "exact_only": False},
            "allow_quarantine": {"type": "allow", "exact_only": True},
            "deny_default": {"type": "deny", "exact_only": False},
        },
    }
    assert set(entry.runtime_data.lists.definitions) == {
        "allow_default",
        "allow_quarantine",
        "deny_default",
    }

    # A partial update of one kind keeps the others.
    await _command(client, 2, type=SET, deny_lists=["deny_other"])
    await hass.async_block_till_done()
    assert entry.options["lists"] == {
        "allow_default": {"type": "allow", "exact_only": False},
        "allow_quarantine": {"type": "allow", "exact_only": True},
        "deny_other": {"type": "deny", "exact_only": False},
    }


@pytest.mark.parametrize(
    ("change", "code", "field"),
    [
        ({"status_interval": 9}, "out_of_range", "status_interval"),
        ({"status_interval": 601}, "out_of_range", "status_interval"),
        ({"stats_interval": 29}, "out_of_range", "stats_interval"),
        ({"stats_interval": 3601}, "out_of_range", "stats_interval"),
        ({"tops_interval": "fast"}, "out_of_range", "tops_interval"),
        ({"tops_interval": 60.5}, "out_of_range", "tops_interval"),
        ({"tops_interval": True}, "out_of_range", "tops_interval"),
        ({"tops_interval": None}, "out_of_range", "tops_interval"),
        ({"report_existing_domains": "yes"}, "invalid_type", "report_existing_domains"),
        ({"show_in_sidebar": 1}, "invalid_type", "show_in_sidebar"),
        ({"allow_lists": "a"}, "invalid_type", "allow_lists"),
        ({"deny_lists": [1]}, "invalid_type", "deny_lists"),
        ({"allow_lists": [f"l{i}" for i in range(21)]}, "invalid_type", "allow_lists"),
        ({"allow_lists": ["Bad Name"]}, "invalid_list_name", "allow_lists"),
        ({"deny_lists": ["../x"]}, "invalid_list_name", "deny_lists"),
        ({"allow_lists": [""]}, "invalid_list_name", "allow_lists"),
        (
            {"allow_lists": ["same"], "deny_lists": ["same"]},
            "duplicate_list_name",
            "allow_lists",
        ),
        ({"allow_lists": ["a", "a"]}, "duplicate_list_name", "allow_lists"),
        (
            {"allow_lists": ["a"], "exact_only_lists": ["b"]},
            "unknown_list_name",
            "exact_only_lists",
        ),
        (
            {
                "allow_lists": [f"a{i}" for i in range(15)],
                "deny_lists": [f"d{i}" for i in range(6)],
            },
            "too_many_lists",
            "allow_lists",
        ),
    ],
)
async def test_bad_options_are_refused_and_nothing_changes(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    change: dict[str, Any],
    code: str,
    field: str,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    before = dict(entry.options)

    # A valid change next to a bad one must not be applied either.
    response = await _command(
        client, 1, type=SET, **{"report_existing_domains": True, **change}
    )
    await hass.async_block_till_done()

    assert response["success"] is False
    assert response["error"] == {"code": code, "message": field}
    assert entry.options == before


@pytest.mark.parametrize(
    "message",
    [
        {},
        {"unexpected": True},
        {"db_password": "x"},
        {"db_host": "evil.example"},
        {"list_networks": ["0.0.0.0/0"]},
        {"zones": {}},
        {"lists": {}},
        {"colors": {"evil": "#000000"}},
        {"colors": "#000000"},
        {"entry_id": 5, "rows": 5},
        {"status_interval": 30, "hours": 5},
    ],
)
async def test_unknown_keys_and_empty_requests_are_refused(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    message: dict[str, Any],
) -> None:
    entry = await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    before = dict(entry.options)

    response = await _command(client, 1, type=SET, **message)

    assert response["success"] is False
    expected = "nothing_to_change" if message == {} else "invalid_format"
    assert response["error"]["code"] == expected
    assert entry.options == before


async def test_options_need_one_matching_entry_but_display_does_not(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=SET, entry_id="nope", status_interval=20)
    assert response["error"] == {"code": "entry_not_found", "message": "entry_id"}

    ok = await _command(client, 2, type=SET, entry_id="nope", rows=5)
    assert ok["success"]


@pytest.mark.parametrize("kind", [GET, SET])
async def test_settings_commands_are_admin_only(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: MockUser,
    log_url: URL,
    kind: str,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    before = dict(entry.options)
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)

    extra = {"rows": 5} if kind == SET else {}
    response = await _command(client, 1, type=kind, **extra)

    assert response["success"] is False
    assert response["error"]["code"] == "unauthorized"
    assert entry.options == before


# --- The shared validation --------------------------------------------------


def test_apply_operational_touches_only_the_whitelisted_options() -> None:
    options = {
        "db_password": "secret",
        "zones": {"office": {}},
        "list_networks": ["192.0.2.0/24"],
        "status_interval": 30,
    }

    new = apply_operational(options, {"status_interval": 45})

    assert new == {**options, "status_interval": 45}
    assert options["status_interval"] == 30  # the input is not changed
    with pytest.raises(SettingError) as err:
        apply_operational(options, {"status_interval": 0})
    assert (err.value.field, err.value.code) == ("status_interval", "out_of_range")
    assert str(err.value) == "status_interval: out_of_range"
