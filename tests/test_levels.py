"""Tests for the protection levels: the Blocky block, the applied marker, the
commands for clients, base groups, notifications and rules, and the list
endpoint's revision marker.

Live-unverified (ROADMAP "Live acceptance"), so not provable here:
(a) Blocky fetches the lists again after a restart and keeps the query
string, (b) a Restricted client still resolves an ordinary domain,
(c) an Unfiltered client (empty deny group) resolves a domain that is on
``deny_default``, (d) a Lockdown client is blocked on an unknown domain and
Approve opens it. These tests only cover what Home Assistant does.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
import yaml
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockUser,
    async_capture_events,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import (
    ClientSessionGenerator,
    WebSocketGenerator,
)
from sqlalchemy.engine import URL

from custom_components.ha_blocky.const import (
    CONF_BASE_GROUPS,
    CONF_CLIENTS,
    CONF_LIST_NETWORKS,
    CONF_NOTIFY,
    DEFAULT_NOTIFY,
    DOMAIN,
    EVENT_LIST_CHANGED,
    EVENT_NEW_DOMAIN,
    MAX_CLIENTS,
)
from custom_components.ha_blocky.levels import (
    ClientConfig,
    LevelConfig,
    LevelError,
    client_groups,
    compute_rev,
    parse_base_groups,
    read_base_groups,
    read_clients,
    read_notify,
    render_block,
    valid_rev,
)

from .test_db import add_rows
from .test_lists import LOOPBACK
from .test_requests import KID, LAB, blocked, harness_round, make, row  # noqa: F401
from .test_stats import DB_OPTIONS

pytestmark = pytest.mark.usefixtures("enable_custom_integrations", "hass_storage")

BASE_URL = "http://blocky.example:4000"
STATUS_URL = f"{BASE_URL}/api/blocking/status"
REFRESH_URL = f"{BASE_URL}/api/lists/refresh"
ENABLED = {"enabled": True, "disabledGroups": [], "autoEnableInSec": 0}

CLIENTS = {
    "192.0.2.10": ClientConfig("restricted"),
    "192.0.2.11": ClientConfig("unfiltered"),
    "198.51.100.5": ClientConfig("lockdown", True),
    "2001:db8::1": ClientConfig("lockdown", False),
}
URLS = {
    "restricted_deny": "http://ha.example:8123/api/ha_blocky/lists/TOKEN/restricted_deny.txt?r=0123abcd",
    "lockdown_allow": "http://ha.example:8123/api/ha_blocky/lists/TOKEN/lockdown_allow.txt?r=0123abcd",
    "unfiltered_empty": "http://ha.example:8123/api/ha_blocky/lists/TOKEN/unfiltered_empty.txt?r=0123abcd",
}


async def _setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    assert await async_setup_component(hass, "http", {})
    aioclient_mock.get(STATUS_URL, json=ENABLED)
    aioclient_mock.post(REFRESH_URL, text="")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_URL: BASE_URL},
        options={CONF_LIST_NETWORKS: LOOPBACK} if options is None else options,
        minor_version=2,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _command(ws: Any, message_id: int, /, **message: Any) -> dict[str, Any]:
    await ws.send_json({"id": message_id, **message})
    return await ws.receive_json()


# --- Pure: base groups, clients, rev -----------------------------------------


@pytest.mark.parametrize(
    "groups",
    [["default"], ["default", "ads", "x-1.v2"], [f"g{i}" for i in range(16)]],
)
def test_base_groups_accept_valid_names(groups: list[str]) -> None:
    assert parse_base_groups(groups) == tuple(groups)


@pytest.mark.parametrize(
    ("groups", "code"),
    [
        ([], "invalid_base_groups"),
        ("default", "invalid_base_groups"),
        (None, "invalid_base_groups"),
        ([f"g{i}" for i in range(17)], "invalid_base_groups"),
        (["bad name"], "invalid_base_groups"),
        (["a\nb: c"], "invalid_base_groups"),
        (['x"y'], "invalid_base_groups"),
        ([1], "invalid_base_groups"),
        (["default", "default"], "duplicate_group"),
        (["restricted"], "reserved_group"),
        (["default", "lockdown"], "reserved_group"),
        (["unfiltered"], "reserved_group"),
    ],
)
def test_base_groups_refuse_the_rest(groups: Any, code: str) -> None:
    with pytest.raises(LevelError) as err:
        parse_base_groups(groups)
    assert err.value.code == code


def test_stored_hostile_values_are_dropped_on_read() -> None:
    options = {
        CONF_BASE_GROUPS: ["default", "evil\n  - injected"],
        CONF_CLIENTS: {
            "192.0.2.1": {"level": "restricted"},
            "192.0.2.2\nclientGroupsBlock: x": {"level": "restricted"},
            "192.0.2.0/24": {"level": "lockdown"},
            "not-an-ip": {"level": "lockdown"},
            "192.0.2.3": {"level": "standard"},
            "192.0.2.4": {"level": "root"},
            "192.0.2.5": "lockdown",
            "::ffff:192.0.2.6": {"level": "lockdown", "ask": True},
            "fe80::1%eth0": {"level": "lockdown"},
        },
        CONF_NOTIFY: {"restricted": "yes", "lockdown": False, "other": True},
    }

    assert read_base_groups(options) == ("default",)
    assert read_clients(options) == {
        "192.0.2.1": ClientConfig("restricted"),
        "192.0.2.6": ClientConfig("lockdown", True),
    }
    assert read_notify(options) == {"restricted": False, "lockdown": False}
    assert read_clients({CONF_CLIENTS: "junk"}) == {}
    assert read_notify({}) == DEFAULT_NOTIFY == {"restricted": False, "lockdown": True}


def test_client_cap_applies_when_reading() -> None:
    options = {
        CONF_CLIENTS: {
            f"192.0.2.{i}": {"level": "unfiltered"} for i in range(1, MAX_CLIENTS + 10)
        }
    }

    assert len(read_clients(options)) == MAX_CLIENTS


def test_rev_depends_on_base_groups_and_levels_but_not_on_order() -> None:
    groups = ("default",)
    first = compute_rev(groups, CLIENTS)

    assert len(first) == 8 and valid_rev(first) == first
    assert compute_rev(groups, dict(reversed(list(CLIENTS.items())))) == first
    assert compute_rev(("default", "ads"), CLIENTS) != first
    assert compute_rev(("ads", "default"), CLIENTS) != compute_rev(
        ("default", "ads"), CLIENTS
    )
    changed = {**CLIENTS, "192.0.2.10": ClientConfig("lockdown")}
    assert compute_rev(groups, changed) != first
    assert compute_rev(groups, {}) != first
    # ask is not part of what Blocky needs to know.
    asked = {**CLIENTS, "2001:db8::1": ClientConfig("lockdown", True)}
    assert compute_rev(groups, asked) == first


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("0123abcd", True),
        ("deadbeef", True),
        ("0123ABCD", False),
        ("0123abc", False),
        ("0123abcde", False),
        ("0123abcd\n", False),
        ("0123abcg", False),
        ("", False),
        (None, False),
        (5, False),
    ],
)
def test_only_eight_lowercase_hex_characters_are_a_rev(value: Any, valid: bool) -> None:
    assert (valid_rev(value) is not None) is valid


# --- Pure: the block ------------------------------------------------------------


def test_block_app_format_has_the_groups_and_one_line_per_client() -> None:
    text = render_block(("default", "ads"), CLIENTS, URLS)["app"]
    data = yaml.safe_load(text)["blocking"]

    assert "do not replace the whole option" in text
    assert data["denylists"] == [
        {"name": "restricted", "sources": [URLS["restricted_deny"]]},
        {"name": "unfiltered", "sources": [URLS["unfiltered_empty"]]},
    ]
    assert data["allowlists"] == [
        {"name": "lockdown", "sources": [URLS["lockdown_allow"]]}
    ]
    assert data["client_groups_block"] == [
        {"name": "192.0.2.10", "lists": ["default", "ads", "restricted"]},
        {"name": "192.0.2.11", "lists": ["unfiltered"]},
        {"name": "198.51.100.5", "lists": ["lockdown"]},
        {"name": "2001:db8::1", "lists": ["lockdown"]},
    ]
    # Every address carries the revision.
    assert text.count("?r=0123abcd") == 3
    # Each of the three parts says where it goes; the comments keep it valid YAML.
    assert "# Part 1 of 3, blocking.denylists:" in text
    assert "# Part 2 of 3, blocking.allowlists:" in text
    assert "# Part 3 of 3, blocking.client_groups_block:" in text


def test_block_plain_format_is_blockys_own_yaml() -> None:
    text = render_block(("default", "ads"), CLIENTS, URLS)["plain"]
    data = yaml.safe_load(text)["blocking"]

    assert "do not replace the whole option" in text
    assert data["denylists"] == {
        "restricted": [URLS["restricted_deny"]],
        "unfiltered": [URLS["unfiltered_empty"]],
    }
    assert data["allowlists"] == {"lockdown": [URLS["lockdown_allow"]]}
    assert data["clientGroupsBlock"] == {
        "192.0.2.10": ["default", "ads", "restricted"],
        "192.0.2.11": ["unfiltered"],
        "198.51.100.5": ["lockdown"],
        "2001:db8::1": ["lockdown"],
    }
    assert "# Part 1 of 3, blocking.denylists:" in text
    assert "# Part 2 of 3, blocking.allowlists:" in text
    assert "# Part 3 of 3, blocking.clientGroupsBlock:" in text


def test_block_without_clients_still_defines_the_groups_and_has_no_lines() -> None:
    block = render_block(("default",), {}, URLS)

    for text in block.values():
        data = yaml.safe_load(text)["blocking"]
        assert data.get("client_groups_block", data.get("clientGroupsBlock")) in (
            None,
            [],
            {},
        )
    assert "restricted" in block["app"] and "lockdown" in block["app"]


def test_block_standard_has_no_client_line_and_uses_the_base_name() -> None:
    clients = {"192.0.2.10": ClientConfig("restricted")}

    app = yaml.safe_load(render_block(("base1", "base2"), clients, URLS)["app"])
    lines = app["blocking"]["client_groups_block"]

    assert lines == [{"name": "192.0.2.10", "lists": ["base1", "base2", "restricted"]}]


def test_hostile_stored_text_never_reaches_the_block() -> None:
    levels = LevelConfig(
        {
            CONF_BASE_GROUPS: ["default\n  - injected"],
            CONF_CLIENTS: {
                "192.0.2.1\nblocking: {}": {"level": "restricted"},
                "192.0.2.2": {"level": "restricted"},
            },
        }
    )

    block = render_block(levels.base_groups, levels.clients, URLS)

    for text in block.values():
        assert "injected" not in text
        assert "\n192.0.2.1" not in text
    assert yaml.safe_load(block["app"])["blocking"]["client_groups_block"] == [
        {"name": "192.0.2.2", "lists": ["default", "restricted"]}
    ]


# --- Commands -------------------------------------------------------------------


async def test_assign_unassign_and_ask_through_the_command(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    rev0 = entry.runtime_data.levels.rev

    response = await _command(
        client,
        1,
        type=f"{DOMAIN}/set_client_level",
        client="::ffff:192.0.2.5",
        level="lockdown",
    )
    assert response["success"]
    assert entry.options[CONF_CLIENTS] == {
        "192.0.2.5": {"level": "lockdown", "ask": True}
    }
    assert entry.runtime_data.levels.rev != rev0
    assert response["result"]["status"]["waiting"] == 1
    assert response["result"]["status"]["applied"] is False

    await _command(
        client,
        2,
        type=f"{DOMAIN}/set_client_level",
        client="192.0.2.5",
        level="lockdown",
        ask=False,
    )
    assert entry.options[CONF_CLIENTS]["192.0.2.5"] == {
        "level": "lockdown",
        "ask": False,
    }
    # Setting the level again without ask keeps the stored switch.
    await _command(
        client,
        3,
        type=f"{DOMAIN}/set_client_level",
        client="192.0.2.5",
        level="lockdown",
    )
    assert entry.options[CONF_CLIENTS]["192.0.2.5"]["ask"] is False

    await _command(
        client,
        4,
        type=f"{DOMAIN}/set_client_level",
        client="192.0.2.5",
        level="restricted",
        ask=True,
    )
    assert entry.options[CONF_CLIENTS]["192.0.2.5"] == {"level": "restricted"}

    response = await _command(
        client,
        5,
        type=f"{DOMAIN}/set_client_level",
        client="192.0.2.5",
        level="standard",
    )
    assert response["success"]
    assert entry.options[CONF_CLIENTS] == {}
    assert entry.runtime_data.levels.rev == rev0
    assert response["result"]["status"]["waiting"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"client": "nope", "level": "lockdown"},
        {"client": "192.0.2.0/24", "level": "lockdown"},
        {"client": "192.0.2.5", "level": "root"},
        {"client": "192.0.2.5", "level": "lockdown", "ask": "yes"},
        {"client": "192.0.2.5"},
        {"level": "lockdown"},
    ],
)
async def test_set_client_level_rejects_bad_input(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    payload: dict[str, Any],
) -> None:
    entry = await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=f"{DOMAIN}/set_client_level", **payload)

    assert response["success"] is False
    assert CONF_CLIENTS not in entry.options


async def test_the_client_cap_is_enforced(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
) -> None:
    options = {
        CONF_LIST_NETWORKS: LOOPBACK,
        CONF_CLIENTS: {
            f"198.51.100.{i}": {"level": "unfiltered"} for i in range(MAX_CLIENTS)
        },
    }
    entry = await _setup(hass, aioclient_mock, options)
    client = await hass_ws_client(hass)

    refused = await _command(
        client,
        1,
        type=f"{DOMAIN}/set_client_level",
        client="192.0.2.9",
        level="restricted",
    )
    assert refused["success"] is False
    assert refused["error"]["code"] == "too_many_clients"
    # An existing client may still change its level.
    changed = await _command(
        client,
        2,
        type=f"{DOMAIN}/set_client_level",
        client="198.51.100.1",
        level="restricted",
    )
    assert changed["success"]
    assert len(entry.options[CONF_CLIENTS]) == MAX_CLIENTS


@pytest.mark.parametrize(
    "message",
    [
        {"type": f"{DOMAIN}/levels"},
        {
            "type": f"{DOMAIN}/set_client_level",
            "client": "192.0.2.5",
            "level": "lockdown",
        },
        {"type": f"{DOMAIN}/set_base_groups", "groups": ["default"]},
        {"type": f"{DOMAIN}/set_notify", "level": "lockdown", "enabled": False},
        {"type": f"{DOMAIN}/get_block"},
        {"type": f"{DOMAIN}/rules"},
        {
            "type": f"{DOMAIN}/rules_add",
            "list": "deny_default",
            "domain": "a.example.com",
        },
        {
            "type": f"{DOMAIN}/rules_remove",
            "list": "deny_default",
            "domain": "a.example.com",
        },
    ],
)
async def test_every_level_command_is_admin_only(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: MockUser,
    message: dict[str, Any],
) -> None:
    entry = await _setup(hass, aioclient_mock)
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)

    response = await _command(client, 1, **message)

    assert response["success"] is False
    assert response["error"]["code"] == "unauthorized"
    assert entry.options == {CONF_LIST_NETWORKS: LOOPBACK}
    assert entry.runtime_data.lists.entries("deny_default") == []


async def test_base_groups_command_validates_and_changes_the_rev(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    rev = entry.runtime_data.levels.rev

    response = await _command(
        client, 1, type=f"{DOMAIN}/set_base_groups", groups=["default", "ads"]
    )
    assert response["success"]
    assert response["result"]["base_groups"] == ["default", "ads"]
    assert entry.options[CONF_BASE_GROUPS] == ["default", "ads"]
    assert entry.runtime_data.levels.rev != rev
    assert response["result"]["status"]["applied"] is False

    cases = [
        ([], "invalid_base_groups"),
        (["bad name"], "invalid_base_groups"),
        (["a", "a"], "duplicate_group"),
        (["lockdown"], "reserved_group"),
    ]
    for message_id, (groups, code) in enumerate(cases, start=2):
        response = await _command(
            client, message_id, type=f"{DOMAIN}/set_base_groups", groups=groups
        )
        assert response["success"] is False
        assert response["error"]["code"] == code
    assert entry.options[CONF_BASE_GROUPS] == ["default", "ads"]


async def test_notify_command_and_defaults(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    assert entry.runtime_data.levels.notify == {"restricted": False, "lockdown": True}

    response = await _command(
        client, 1, type=f"{DOMAIN}/set_notify", level="restricted", enabled=True
    )
    assert response["result"]["notify"] == {"restricted": True, "lockdown": True}
    await _command(
        client, 2, type=f"{DOMAIN}/set_notify", level="lockdown", enabled=False
    )
    assert entry.options[CONF_NOTIFY] == {"restricted": True, "lockdown": False}

    for message in (
        {"level": "unfiltered", "enabled": True},
        {"level": "restricted", "enabled": "on"},
    ):
        response = await _command(client, 3, type=f"{DOMAIN}/set_notify", **message)
        assert response["success"] is False


async def test_the_levels_command_lists_clients_seen_and_configured(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    options = {
        **DB_OPTIONS,
        CONF_LIST_NETWORKS: LOOPBACK,
        CONF_CLIENTS: {"203.0.113.9": {"level": "unfiltered"}},
    }
    entry = await _setup(hass, aioclient_mock, options)
    add_rows(log_url, [row("a.example.com", LAB), row("b.example.com", LAB)])
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=f"{DOMAIN}/levels")

    assert response["success"]
    result = response["result"]
    assert result["entry_id"] == entry.entry_id
    assert result["base_groups"] == ["default"]
    assert result["notify"] == {"restricted": False, "lockdown": True}
    assert [c["address"] for c in result["clients"]] == ["203.0.113.9", LAB]
    assert result["clients"][0]["level"] == "unfiltered"
    assert result["clients"][1] == {
        "address": LAB,
        "client_name": None,
        "name_source": None,
        "level": "standard",
        "ask": False,
        "queries": 2,
    }
    # Never saved: the card warns that the built-in default may not fit.
    assert result["base_groups_saved"] is False
    assert result["setup"]["api_ok"] is True
    assert result["setup"]["log_ok"] is True
    assert set(result["status"]) == {
        "rev",
        "applied",
        "waiting",
        "fetched_since_start",
        "lists",
    }


async def test_the_block_command_renders_server_side_and_carries_the_rev(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
) -> None:
    options = {
        CONF_LIST_NETWORKS: LOOPBACK,
        CONF_CLIENTS: {"192.0.2.10": {"level": "restricted"}},
        CONF_BASE_GROUPS: ["default", "ads"],
    }
    entry = await _setup(hass, aioclient_mock, options)
    client = await hass_ws_client(hass)
    lists = entry.runtime_data.lists
    rev = entry.runtime_data.levels.rev

    response = await _command(client, 1, type=f"{DOMAIN}/get_block")

    assert response["success"]
    result = response["result"]
    assert result["rev"] == rev
    assert result["client_count"] == 1
    for name in ("restricted_deny", "lockdown_allow", "unfiltered_empty"):
        assert f"{lists.path(name)}?r={rev}" in result["app"]
        assert f"{lists.path(name)}?r={rev}" in result["plain"]
    assert yaml.safe_load(result["app"])["blocking"]["client_groups_block"] == [
        {"name": "192.0.2.10", "lists": ["default", "ads", "restricted"]}
    ]


# --- Rules ----------------------------------------------------------------------


async def test_rules_commands_list_add_and_remove(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    events = async_capture_events(hass, EVENT_LIST_CHANGED)

    added = await _command(
        client,
        1,
        type=f"{DOMAIN}/rules_add",
        list="deny_default",
        domain=" Ads.Example.COM. ",
    )
    assert added["result"] == {"domain": "ads.example.com", "added": True}
    again = await _command(
        client,
        2,
        type=f"{DOMAIN}/rules_add",
        list="deny_default",
        domain="ads.example.com",
    )
    assert again["result"] == {"domain": None, "added": False}
    await _command(
        client,
        3,
        type=f"{DOMAIN}/rules_add",
        list="lockdown_allow",
        domain="tv.example.com",
    )

    listing = (await _command(client, 4, type=f"{DOMAIN}/rules"))["result"]["lists"]
    by_name = {item["name"]: item for item in listing}
    assert list(by_name) == [
        "allow_default",
        "deny_default",
        "restricted_deny",
        "lockdown_allow",
    ]
    assert by_name["deny_default"]["entries"] == ["ads.example.com"]
    assert by_name["lockdown_allow"]["exact_only"] is True
    assert by_name["deny_default"]["exact_only"] is False

    removed = await _command(
        client,
        5,
        type=f"{DOMAIN}/rules_remove",
        list="deny_default",
        domain="ADS.example.com",
    )
    assert removed["result"] == {"domain": "ads.example.com", "removed": True}
    assert entry.runtime_data.lists.entries("deny_default") == []
    assert [(e.data["action"], e.data["list"]) for e in events] == [
        ("add", "deny_default"),
        ("add", "lockdown_allow"),
        ("remove", "deny_default"),
    ]


async def test_lockdown_allow_refuses_wildcards_on_add_only(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    refused = await _command(
        client,
        1,
        type=f"{DOMAIN}/rules_add",
        list="lockdown_allow",
        domain="*.example.com",
    )
    assert refused["success"] is False
    assert refused["error"]["code"] == "list_error"
    assert entry.runtime_data.lists.entries("lockdown_allow") == []

    other = await _command(
        client,
        2,
        type=f"{DOMAIN}/rules_add",
        list="allow_default",
        domain="*.example.com",
    )
    assert other["success"]
    assert entry.runtime_data.lists.entries("allow_default") == ["*.example.com"]


@pytest.mark.parametrize(
    "payload",
    [
        {"list": "no_such_list", "domain": "a.example.com"},
        {"list": "unfiltered_empty", "domain": "a.example.com"},
        {"list": "deny_default", "domain": "/.*/"},
        {"list": "deny_default", "domain": "a.example.com\nb.example.com"},
        {"list": "deny_default", "domain": ""},
        {"list": "deny_default", "domain": "x" * 300},
        {"list": "deny_default", "domain": "192.0.2.1"},
    ],
)
async def test_rules_add_rejects_bad_input(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    payload: dict[str, str],
) -> None:
    entry = await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=f"{DOMAIN}/rules_add", **payload)

    assert response["success"] is False
    assert entry.runtime_data.lists.entries("deny_default") == []


# --- The list endpoint and the applied marker -------------------------------------


async def test_a_valid_r_is_recorded_and_the_status_flips_to_applied(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
    hass_ws_client: WebSocketGenerator,
) -> None:
    options = {
        CONF_LIST_NETWORKS: LOOPBACK,
        CONF_CLIENTS: {"192.0.2.10": {"level": "restricted"}},
    }
    entry = await _setup(hass, aioclient_mock, options)
    lists = entry.runtime_data.lists
    rev = entry.runtime_data.levels.rev
    http = await hass_client_no_auth()
    ws = await hass_ws_client(hass)

    status = (await _command(ws, 1, type=f"{DOMAIN}/levels"))["result"]["status"]
    assert status["applied"] is False
    assert status["waiting"] == 1
    assert status["fetched_since_start"] is False

    for name in ("restricted_deny", "lockdown_allow"):
        assert (await http.get(f"{lists.path(name)}?r={rev}")).status == 200
    status = (await _command(ws, 2, type=f"{DOMAIN}/levels"))["result"]["status"]
    assert status["applied"] is False
    assert status["fetched_since_start"] is True
    assert status["lists"]["restricted"] == {"fetched": True, "current": True}
    assert status["lists"]["unfiltered"] == {"fetched": False, "current": False}

    assert (await http.get(f"{lists.path('unfiltered_empty')}?r={rev}")).status == 200
    status = (await _command(ws, 3, type=f"{DOMAIN}/levels"))["result"]["status"]
    assert status["applied"] is True
    assert status["waiting"] == 0

    # A new change is waiting again, until Blocky fetches with the new rev.
    await _command(
        ws,
        4,
        type=f"{DOMAIN}/set_client_level",
        client="192.0.2.11",
        level="unfiltered",
    )
    status = (await _command(ws, 5, type=f"{DOMAIN}/levels"))["result"]["status"]
    assert status["applied"] is False
    assert status["waiting"] == 1
    assert lists.applied == {
        "base_groups": ["default"],
        "clients": {"192.0.2.10": "restricted"},
    }


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?r=",
        "?r=ABCDEF12",
        "?r=0123abc",
        "?r=0123abcde",
        "?r=0123abcg",
        "?r=../../x",
        "?r=0123abcd%0A",
        "?r=a&r=b",
        "?r=%3Cscript%3E",
    ],
)
async def test_an_invalid_r_is_ignored_and_changes_nothing(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
    caplog: pytest.LogCaptureFixture,
    query: str,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    lists = entry.runtime_data.lists
    lists.async_add("deny_default", "a.example.com", "deny")
    http = await hass_client_no_auth()
    plain = await http.get(lists.path("deny_default"))

    response = await http.get(f"{lists.path('deny_default')}{query}")

    # Home Assistant's own request filter refuses some queries (newlines,
    # traversal, markup) before the view runs; the others are served as usual.
    assert plain.status == 200
    assert response.status in (200, 400)
    if response.status == 200:
        assert await response.text() == await plain.text() == "a.example.com\n"
    assert lists.fetched("deny_default") is None
    ours = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("custom_components")
    )
    assert "script" not in ours and "0123abc" not in ours


async def test_the_body_is_the_same_whatever_r_is_and_refusals_stay_404(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    lists = entry.runtime_data.lists
    lists.async_add("lockdown_allow", "tv.example.com", "allow")
    http = await hass_client_no_auth()
    path = lists.path("lockdown_allow")

    bodies = {
        await (await http.get(f"{path}{query}")).text()
        for query in ("", "?r=0123abcd", "?r=ffffffff", "?r=zzzz")
    }

    assert bodies == {"tv.example.com\n"}
    # A wrong token never records anything, whatever r says.
    wrong = await http.get(f"{path.replace(lists.token, 'x' * 43)}?r=0123abcd")
    assert wrong.status == 404
    assert (await wrong.text()) == ""
    assert lists.fetched("lockdown_allow") == (
        "ffffffff",
        lists.fetched("lockdown_allow")[1],
    )


async def test_the_unfiltered_list_is_always_served_empty_and_recorded_per_list_name(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    lists = entry.runtime_data.lists
    http = await hass_client_no_auth()

    response = await http.get(f"{lists.path('unfiltered_empty')}?r=0123abcd")
    assert response.status == 200
    assert await response.text() == ""
    # Unknown names are not recorded: the record is bounded by the fixed names.
    assert (await http.get(f"{lists.path('made_up')}?r=0123abcd")).status == 404
    for index in range(50):
        await http.get(f"{lists.path('made_up')}{index}?r=0123abcd")
    assert lists._fetched == {
        "unfiltered_empty": ("0123abcd", lists.fetched("unfiltered_empty")[1])
    }


async def test_the_applied_state_survives_a_restart(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
    hass_ws_client: WebSocketGenerator,
) -> None:
    options = {
        CONF_LIST_NETWORKS: LOOPBACK,
        CONF_CLIENTS: {"192.0.2.10": {"level": "restricted"}},
    }
    entry = await _setup(hass, aioclient_mock, options)
    lists = entry.runtime_data.lists
    rev = entry.runtime_data.levels.rev
    http = await hass_client_no_auth()
    for name in ("restricted_deny", "lockdown_allow", "unfiltered_empty"):
        await http.get(f"{lists.path(name)}?r={rev}")
    ws = await hass_ws_client(hass)
    assert (await _command(ws, 1, type=f"{DOMAIN}/levels"))["result"]["status"][
        "applied"
    ]

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # In memory records are gone ("waiting until Blocky fetches again"), but
    # nothing changed since the last applied state, so nothing is waiting.
    status = (await _command(ws, 2, type=f"{DOMAIN}/levels"))["result"]["status"]
    assert status["fetched_since_start"] is False
    assert status["waiting"] == 0


# --- Notifications ----------------------------------------------------------------


async def test_notification_off_suppresses_the_event_but_not_the_request(
    hass: HomeAssistant,
    make: Callable[..., Any],  # noqa: F811
) -> None:
    options = {
        **DB_OPTIONS,
        CONF_LIST_NETWORKS: LOOPBACK,
        CONF_CLIENTS: {
            LAB: {"level": "restricted"},
            KID: {"level": "lockdown", "ask": True},
        },
        "report_existing_domains": True,
    }
    harness = await make(options=options)
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    harness.add(row("a.example.com"), blocked("b.example.com"))

    await harness_round(hass, harness)

    # Defaults: Restricted Off (no event), Lockdown Each (event).
    assert [e.data["domain"] for e in events] == ["b.example.com"]
    assert harness.tracker.pending_count == 2

    harness.tracker._levels.update(
        {**options, CONF_NOTIFY: {"restricted": True, "lockdown": False}}
    )
    events.clear()
    harness.add(row("c.example.com"), blocked("d.example.com"))
    await harness_round(hass, harness)

    assert [e.data["domain"] for e in events] == ["c.example.com"]
    assert harness.tracker.pending_count == 4


def test_the_block_json_roundtrips_through_a_websocket_safe_form() -> None:
    block = render_block(("default",), CLIENTS, URLS)

    assert json.loads(json.dumps(block)) == block


def test_every_manual_list_names_the_levels_it_changes() -> None:
    from custom_components.ha_blocky.const import RULE_LISTS
    from custom_components.ha_blocky.levels import LIST_LEVELS

    assert set(LIST_LEVELS) == set(RULE_LISTS)
    assert LIST_LEVELS["lockdown_allow"] == ("lockdown",)
    assert LIST_LEVELS["restricted_deny"] == ("restricted",)
    # Unfiltered clients use an empty group: no manual list reaches them.
    assert all("unfiltered" not in levels for levels in LIST_LEVELS.values())
    # The groups of a client line agree: a Restricted client has the base groups
    # (where the Always lists belong) plus its own list.
    assert client_groups(ClientConfig("restricted"), ("default",)) == (
        "default",
        "restricted",
    )
