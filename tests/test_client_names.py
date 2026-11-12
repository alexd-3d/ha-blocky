"""Tests for client names: validator, store, resolution and the command."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockUser
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator
from sqlalchemy.engine import URL

from custom_components.ha_blocky import client_names as names_module
from custom_components.ha_blocky.client_names import (
    STORAGE_KEY,
    ClientNameError,
    ClientNames,
    get_client_names,
)
from custom_components.ha_blocky.const import DOMAIN, MAX_CLIENT_NAMES
from custom_components.ha_blocky.diagnostics import async_get_config_entry_diagnostics
from custom_components.ha_blocky.validation import (
    InvalidClientNameError,
    validate_client_name,
)

from .test_card import _command, _setup
from .test_db import add_rows
from .test_stats import log_row

CLIENT = "192.0.2.10"
OTHER = "192.0.2.11"
SET = f"{DOMAIN}/set_client_name"

# --- Validator ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Laptop", "Laptop"),
        ("  Laptop  ", "Laptop"),
        ("a", "a"),
        ("a" * 64, "a" * 64),
        ("Телефон Олі", "Телефон Олі"),
        ("日本語のデバイス", "日本語のデバイス"),
        ("Phone \U0001f4f1", "Phone \U0001f4f1"),
        ("two  words", "two  words"),
        ("<b>not markup</b>", "<b>not markup</b>"),
    ],
)
def test_valid_names(value: str, expected: str) -> None:
    assert validate_client_name(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "\t",
        "a" * 65,
        " " + "a" * 65 + " ",
        "bad\x00name",
        "new\nline",
        "tab\there",
        "bell\x07",
        "del\x7f",
        "next\x85line",
        "rtl\u202eoverride",
        "zero\u200bwidth",
        "joiner\u200dhere",
        "line\u2028separator",
        "paragraph\u2029separator",
        "private\ue000use",
        "lone\ud800surrogate",
        "unassigned\U000e0080",
        None,
        5,
        b"bytes",
        ["Laptop"],
    ],
)
def test_invalid_names_are_refused_not_repaired(value: Any) -> None:
    with pytest.raises(InvalidClientNameError):
        validate_client_name(value)


# --- Store -------------------------------------------------------------------


def _stored(names: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {"names": names},
    }


async def test_set_persists_and_clear_removes(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    names = ClientNames(hass)
    await names.async_load()

    assert await names.async_set(CLIENT, "Laptop") == "Laptop"
    assert hass_storage[STORAGE_KEY]["data"] == {"names": {CLIENT: "Laptop"}}
    assert names.manual_name(CLIENT) == "Laptop"
    assert names.name_map() == {CLIENT: "Laptop"}

    await names.async_set(CLIENT, None)
    assert hass_storage[STORAGE_KEY]["data"] == {"names": {}}
    assert names.manual_name(CLIENT) is None
    # Clearing a name that is not there is fine.
    await names.async_set(OTHER, None)

    again = ClientNames(hass)
    await again.async_load()
    assert again.name_map() == {}


async def test_stored_names_come_back(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    hass_storage[STORAGE_KEY] = _stored({CLIENT: "Laptop", "2001:db8::1": "Router"})

    names = ClientNames(hass)
    await names.async_load()

    assert names.name_map() == {CLIENT: "Laptop", "2001:db8::1": "Router"}


async def test_load_revalidates_every_entry(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    hass_storage[STORAGE_KEY] = _stored(
        {
            CLIENT: "  Laptop ",
            "not-an-ip": "Bad address",
            "192.0.2.0/24": "A network",
            "::ffff:192.0.2.12": "Mapped",
            OTHER: "bad\x00name",
            "192.0.2.12": "x" * 65,
            "192.0.2.13": 5,
            "192.0.2.14": "",
            "192.0.2.15": None,
            5: "Integer key",
        }
    )

    names = ClientNames(hass)
    await names.async_load()

    assert names.name_map() == {CLIENT: "Laptop", "192.0.2.12": "Mapped"}


@pytest.mark.parametrize("stored", [None, [], "text", {"names": []}, {"names": 5}])
async def test_load_survives_a_broken_store(
    hass: HomeAssistant, hass_storage: dict[str, Any], stored: Any
) -> None:
    if stored is not None:
        hass_storage[STORAGE_KEY] = {
            "version": 1,
            "minor_version": 1,
            "key": STORAGE_KEY,
            "data": stored,
        }

    names = ClientNames(hass)
    await names.async_load()

    assert names.name_map() == {}


async def test_load_drops_everything_past_the_cap(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    hass_storage[STORAGE_KEY] = _stored(
        {
            f"{prefix}.{i % 250 + 1}": f"n{i}"
            for i, prefix in enumerate(
                ["192.0.2", "198.51.100", "203.0.113"][n // 250]
                for n in range(MAX_CLIENT_NAMES + 90)
            )
        }
    )

    names = ClientNames(hass)
    await names.async_load()

    assert len(names.name_map()) == MAX_CLIENT_NAMES
    assert names.manual_name("192.0.2.1") == "n0"


async def test_a_new_name_past_the_cap_is_refused(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(names_module, "MAX_CLIENT_NAMES", 2)
    names = ClientNames(hass)
    await names.async_load()
    await names.async_set("192.0.2.1", "One")
    await names.async_set("192.0.2.2", "Two")

    with pytest.raises(ClientNameError) as err:
        await names.async_set("192.0.2.3", "Three")
    assert err.value.code == "too_many_names"

    # An existing entry can still be renamed or cleared at the cap.
    await names.async_set("192.0.2.1", "Uno")
    await names.async_set("192.0.2.2", None)
    await names.async_set("192.0.2.3", "Three")
    assert names.name_map() == {"192.0.2.1": "Uno", "192.0.2.3": "Three"}


# --- Resolution --------------------------------------------------------------


def _tracker(
    hass: HomeAssistant, entity_id: str, ip: Any, name: Any = None, **extra: Any
) -> None:
    attributes: dict[str, Any] = {"ip": ip, **extra}
    if name is not None:
        attributes["friendly_name"] = name
    hass.states.async_set(entity_id, "home", attributes)


async def test_a_device_tracker_names_its_address(hass: HomeAssistant) -> None:
    names = ClientNames(hass)
    await names.async_load()
    _tracker(hass, "device_tracker.phone", CLIENT, "Phone")
    _tracker(hass, "device_tracker.no_ip", None, "Nothing")
    _tracker(hass, "device_tracker.bad_ip", "not-an-ip", "Bad")
    _tracker(hass, "device_tracker.mapped", "::ffff:192.0.2.77", "Mapped")
    _tracker(hass, "device_tracker.int_ip", 5, "Integer")
    # Only device trackers count.
    hass.states.async_set(
        "sensor.thing", "1", {"ip": OTHER, "friendly_name": "Not a tracker"}
    )

    assert names.name_map() == {CLIENT: "Phone", "192.0.2.77": "Mapped"}


async def test_a_manual_name_beats_a_tracker(hass: HomeAssistant) -> None:
    names = ClientNames(hass)
    await names.async_load()
    _tracker(hass, "device_tracker.phone", CLIENT, "Tracker name")
    _tracker(hass, "device_tracker.tv", OTHER, "TV")
    await names.async_set(CLIENT, "My name")

    assert names.name_map() == {CLIENT: "My name", OTHER: "TV"}
    # Clearing the manual name brings the tracker name back.
    await names.async_set(CLIENT, None)
    assert names.name_map()[CLIENT] == "Tracker name"


async def test_several_trackers_the_lowest_entity_id_wins(
    hass: HomeAssistant,
) -> None:
    names = ClientNames(hass)
    await names.async_load()
    _tracker(hass, "device_tracker.zeta", CLIENT, "Zeta")
    _tracker(hass, "device_tracker.alpha", CLIENT, "Alpha")
    _tracker(hass, "device_tracker.mid", CLIENT, "Mid")

    assert names.name_map() == {CLIENT: "Alpha"}


@pytest.mark.parametrize(
    "hostile",
    [
        "evil\x00name",
        "new\nline",
        "rtl\u202eoverride",
        "x" * 65,
        "   ",
        5,
        ["list"],
        None,
    ],
)
async def test_a_hostile_tracker_name_counts_as_no_name(
    hass: HomeAssistant, hostile: Any
) -> None:
    names = ClientNames(hass)
    await names.async_load()
    _tracker(hass, "device_tracker.evil", CLIENT, hostile)

    assert names.name_map() == {}
    assert names.manual_name(CLIENT) is None


async def test_the_winning_tracker_with_a_bad_name_leaves_the_address_unnamed(
    hass: HomeAssistant,
) -> None:
    """The lowest entity id wins first; a later, clean name does not replace it."""
    names = ClientNames(hass)
    await names.async_load()
    _tracker(hass, "device_tracker.a_evil", CLIENT, "evil\x00name")
    _tracker(hass, "device_tracker.b_good", CLIENT, "Good")

    assert names.name_map() == {}


async def test_a_tracker_name_is_cleaned_like_a_manual_one(
    hass: HomeAssistant,
) -> None:
    names = ClientNames(hass)
    await names.async_load()
    _tracker(hass, "device_tracker.padded", CLIENT, "  Padded  ")

    assert names.name_map() == {CLIENT: "Padded"}


# --- The command -------------------------------------------------------------


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_command_sets_and_clears_a_name(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    hass_storage: dict[str, Any],
    log_url: URL,
) -> None:
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    saved = await _command(client, 1, type=SET, ip=CLIENT, name="  Laptop ")
    assert saved["success"]
    assert saved["result"] == {"ip": CLIENT, "name": "Laptop"}
    assert hass_storage[STORAGE_KEY]["data"] == {"names": {CLIENT: "Laptop"}}
    names = get_client_names(hass)
    assert names is not None
    assert names.name_map() == {CLIENT: "Laptop"}

    # The address is stored in its canonical form.
    mapped = await _command(client, 2, type=SET, ip="::ffff:192.0.2.11", name="Phone")
    assert mapped["result"] == {"ip": OTHER, "name": "Phone"}

    for message_id, message in enumerate(({"name": ""}, {"name": None}, {}), start=3):
        await names.async_set(CLIENT, "Laptop")
        cleared = await _command(client, message_id, type=SET, ip=CLIENT, **message)
        assert cleared["success"], message
        assert cleared["result"] == {"ip": CLIENT, "name": None}
        assert names.manual_name(CLIENT) is None
    assert names.manual_name(OTHER) == "Phone"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_command_is_admin_only(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: MockUser,
    log_url: URL,
) -> None:
    await _setup(hass, aioclient_mock)
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=SET, ip=CLIENT, name="Laptop")

    assert response["success"] is False
    assert response["error"]["code"] == "unauthorized"
    names = get_client_names(hass)
    assert names is not None
    assert names.name_map() == {}


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize(
    "ip", ["not-an-ip", "", "192.0.2.0/24", "fe80::1%eth0", "1" * 99]
)
async def test_command_refuses_a_bad_address(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    ip: str,
) -> None:
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=SET, ip=ip, name="Laptop")

    assert response["success"] is False
    assert response["error"]["code"] == "invalid_ip"


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize(
    "name",
    ["bad\x00name", "new\nline", "x" * 65, "   ", "rtl\u202eoverride", "\n"],
)
async def test_command_refuses_a_bad_name(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    name: str,
) -> None:
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    names = get_client_names(hass)
    assert names is not None
    await names.async_set(CLIENT, "Keep me")

    response = await _command(client, 1, type=SET, ip=CLIENT, name=name)

    assert response["success"] is False
    assert response["error"]["code"] == "invalid_name"
    # A refused name neither changes nor clears what was stored.
    assert names.manual_name(CLIENT) == "Keep me"


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize(
    "message",
    [
        {"ip": 5},
        {"ip": None},
        {"ip": [CLIENT]},
        {"name": "No address"},
        {"ip": CLIENT, "name": 5},
        {"ip": CLIENT, "name": ["Laptop"]},
        {"ip": CLIENT, "name": "Laptop", "extra": True},
    ],
)
async def test_command_refuses_malformed_messages(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    message: dict[str, Any],
) -> None:
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=SET, **message)

    assert response["success"] is False
    assert response["error"]["code"] == "invalid_format"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_command_refuses_a_new_name_past_the_cap(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    monkeypatch: pytest.MonkeyPatch,
    log_url: URL,
) -> None:
    monkeypatch.setattr(names_module, "MAX_CLIENT_NAMES", 1)
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    first = await _command(client, 1, type=SET, ip=CLIENT, name="One")
    second = await _command(client, 2, type=SET, ip=OTHER, name="Two")
    again = await _command(client, 3, type=SET, ip=CLIENT, name="Uno")

    assert first["success"]
    assert second["success"] is False
    assert second["error"]["code"] == "too_many_names"
    assert again["success"]


# --- Names in answers --------------------------------------------------------


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_query_log_rows_carry_the_name(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    add_rows(
        log_url,
        [
            log_row("a.example.com", client=CLIENT),
            log_row("b.example.com", client=OTHER),
            log_row("c.example.com", client="192.0.2.12"),
        ],
    )
    await _setup(hass, aioclient_mock)
    _tracker(hass, "device_tracker.tv", "192.0.2.12", "Living room TV")
    client = await hass_ws_client(hass)
    await _command(client, 1, type=SET, ip=CLIENT, name="Laptop")

    response = await _command(client, 2, type=f"{DOMAIN}/query_log")

    by_domain = {
        row["domain"]: row["client_name"] for row in response["result"]["rows"]
    }
    assert by_domain == {
        "a.example.com": "Laptop",
        "b.example.com": None,
        "c.example.com": "Living room TV",
    }


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_requests_answer_carries_the_name(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    from .test_requests import KID, OPTIONS, blocked

    add_rows(log_url, [blocked("one.example.com", KID)])
    entry = await _setup(hass, aioclient_mock, OPTIONS)
    client = await hass_ws_client(hass)
    await _command(client, 1, type=SET, ip=KID, name="Kid Tablet")
    tracker = entry.runtime_data.requests
    await tracker.async_round()
    await tracker.async_round()

    response = await _command(client, 2, type=f"{DOMAIN}/requests")

    result = response["result"]
    assert [r["client_name"] for r in result["requests"]] == ["Kid Tablet"]
    assert [c["client_name"] for c in result["clients"]] == ["Kid Tablet"]


# --- Privacy -----------------------------------------------------------------


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_names_never_reach_diagnostics_or_logs(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from .test_requests import OPTIONS

    caplog.set_level(logging.DEBUG)
    entry = await _setup(hass, aioclient_mock, OPTIONS)
    client = await hass_ws_client(hass)
    _tracker(hass, "device_tracker.phone", "192.0.2.50", "TrackerSecret")
    await _command(client, 1, type=SET, ip=CLIENT, name="ManualSecret")
    await _command(client, 2, type=SET, ip=OTHER, name="bad\x00SecretToo")
    await entry.runtime_data.requests.async_round()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    dumped = json.dumps(diagnostics, default=str)
    # The test harness itself logs every message; look at the integration's own.
    ours = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("custom_components.ha_blocky")
    )
    for needle in ("ManualSecret", "TrackerSecret", "SecretToo"):
        assert needle not in dumped
        assert needle not in ours
