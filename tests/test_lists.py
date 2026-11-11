"""Tests for the manual lists: storage, endpoint, actions and options."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import CONF_URL
from homeassistant.core import Context, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockUser,
    async_capture_events,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.ha_blocky.const import (
    CONF_ALLOW_LISTS,
    CONF_DENY_LISTS,
    CONF_EXACT_ONLY_LISTS,
    CONF_LIST_NETWORKS,
    CONF_LISTS,
    DOMAIN,
    EVENT_LIST_CHANGED,
    MAX_LIST_ENTRIES,
    REFRESH_DEBOUNCE_SECONDS,
)
from custom_components.ha_blocky.lists import storage_key

from .test_stats import open_options_step

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

BASE_URL = "http://blocky.example:4000"
STATUS_URL = f"{BASE_URL}/api/blocking/status"
REFRESH_URL = f"{BASE_URL}/api/lists/refresh"
ENABLED = {"enabled": True, "disabledGroups": [], "autoEnableInSec": 0}

# The test client connects from the loopback address.
LOOPBACK = ["127.0.0.0/8", "::1/128"]
LIST_OPTIONS = {
    CONF_LISTS: {
        "allow_default": {"type": "allow", "exact_only": False},
        "deny_default": {"type": "deny", "exact_only": False},
        "allow_quarantine": {"type": "allow", "exact_only": True},
    },
    CONF_LIST_NETWORKS: LOOPBACK,
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
        options=LIST_OPTIONS if options is None else options,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _call(hass: HomeAssistant, service: str, **data: Any) -> Any:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=service == "get_list"
    )


def _refresh_calls(aioclient_mock: AiohttpClientMocker) -> int:
    return sum(
        1
        for method, url, _data, _headers in aioclient_mock.mock_calls
        if method.upper() == "POST" and url.path == "/api/lists/refresh"
    )


# --- Actions ----------------------------------------------------------------


async def test_allow_block_remove_and_get(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    events = async_capture_events(hass, EVENT_LIST_CHANGED)
    user_context = Context(user_id=None)

    await hass.services.async_call(
        DOMAIN,
        "allow_domain",
        {"list": "allow_default", "domain": "  Good.Example.COM. "},
        blocking=True,
        context=user_context,
    )
    await _call(hass, "allow_domain", list="allow_default", domain="*.cdn.example")
    await _call(hass, "block_domain", list="deny_default", domain="ads.example.net")

    assert await _call(hass, "get_list", list="allow_default") == {
        "list": "allow_default",
        "type": "allow",
        "exact_only": False,
        "entries": ["*.cdn.example", "good.example.com"],
    }
    assert (await _call(hass, "get_list", list="deny_default"))["entries"] == [
        "ads.example.net"
    ]

    await _call(hass, "remove_domain", list="allow_default", domain="GOOD.example.com")
    assert (await _call(hass, "get_list", list="allow_default"))["entries"] == [
        "*.cdn.example"
    ]

    assert [(e.data["action"], e.data["list"], e.data["domain"]) for e in events] == [
        ("add", "allow_default", "good.example.com"),
        ("add", "allow_default", "*.cdn.example"),
        ("add", "deny_default", "ads.example.net"),
        ("remove", "allow_default", "good.example.com"),
    ]
    assert events[0].context is user_context


async def test_repeated_changes_are_not_reported_twice(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    events = async_capture_events(hass, EVENT_LIST_CHANGED)

    await _call(hass, "block_domain", list="deny_default", domain="ads.example.net")
    await _call(hass, "block_domain", list="deny_default", domain="ADS.example.net.")
    await _call(hass, "remove_domain", list="deny_default", domain="other.example")

    assert len(events) == 1


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("allow_domain", {"list": "deny_default", "domain": "example.com"}),
        ("block_domain", {"list": "allow_default", "domain": "example.com"}),
        ("allow_domain", {"list": "no_such_list", "domain": "example.com"}),
        ("allow_domain", {"list": "../allow_default", "domain": "example.com"}),
        ("allow_domain", {"list": "allow_default", "domain": "/.*/"}),
        ("allow_domain", {"list": "allow_default", "domain": "*"}),
        ("allow_domain", {"list": "allow_default", "domain": "com"}),
        ("allow_domain", {"list": "allow_default", "domain": "a.example\nb.example"}),
        ("allow_domain", {"list": "allow_default", "domain": "example.com # x"}),
        ("allow_domain", {"list": "allow_quarantine", "domain": "*.example.com"}),
        ("block_domain", {"list": "deny_default", "domain": "192.0.2.1"}),
        ("remove_domain", {"list": "no_such_list", "domain": "example.com"}),
        ("remove_domain", {"list": "deny_default", "domain": "not a domain"}),
        ("get_list", {"list": "no_such_list"}),
    ],
)
async def test_actions_reject_bad_input(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    service: str,
    data: dict[str, Any],
) -> None:
    await _setup(hass, aioclient_mock)
    events = async_capture_events(hass, EVENT_LIST_CHANGED)

    with pytest.raises(ServiceValidationError):
        await _call(hass, service, **data)

    assert events == []
    assert (await _call(hass, "get_list", list="allow_default"))["entries"] == []


async def test_exact_only_list_accepts_exact_names(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)

    await _call(hass, "allow_domain", list="allow_quarantine", domain="tv.example.com")

    assert await _call(hass, "get_list", list="allow_quarantine") == {
        "list": "allow_quarantine",
        "type": "allow",
        "exact_only": True,
        "entries": ["tv.example.com"],
    }


@pytest.mark.parametrize(
    "service",
    ["allow_domain", "block_domain", "remove_domain", "get_list", "rotate_list_token"],
)
async def test_actions_are_admin_only(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_read_only_user: MockUser,
    service: str,
) -> None:
    await _setup(hass, aioclient_mock)
    data = {"list": "allow_default", "domain": "example.com"}
    if service == "get_list":
        data = {"list": "allow_default"}
    elif service == "rotate_list_token":
        data = {}

    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            service,
            data,
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
            return_response=service == "get_list",
        )


async def test_list_has_a_size_limit(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(hass, aioclient_mock)
    lists = entry.runtime_data.lists
    for index in range(MAX_LIST_ENTRIES):
        lists.async_add("deny_default", f"h{index}.example.com", "deny")

    with pytest.raises(ServiceValidationError):
        await _call(
            hass, "block_domain", list="deny_default", domain="one.more.example"
        )

    assert lists.count("deny_default") == MAX_LIST_ENTRIES


# --- Reload of Blocky -------------------------------------------------------


async def test_changes_trigger_one_delayed_reload(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, aioclient_mock)

    for index in range(5):
        await _call(
            hass, "block_domain", list="deny_default", domain=f"ads{index}.example.net"
        )
    assert _refresh_calls(aioclient_mock) == 0

    freezer.tick(timedelta(seconds=REFRESH_DEBOUNCE_SECONDS + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert _refresh_calls(aioclient_mock) == 1


async def test_failed_reload_keeps_the_change(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, aioclient_mock)
    aioclient_mock.clear_requests()
    aioclient_mock.get(STATUS_URL, json=ENABLED)
    aioclient_mock.post(REFRESH_URL, status=500, text="boom")

    await _call(hass, "block_domain", list="deny_default", domain="ads.example.net")
    freezer.tick(timedelta(seconds=REFRESH_DEBOUNCE_SECONDS + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert (await _call(hass, "get_list", list="deny_default"))["entries"] == [
        "ads.example.net"
    ]


# --- Endpoint ---------------------------------------------------------------


async def test_endpoint_serves_a_list(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    await _call(hass, "allow_domain", list="allow_default", domain="b.example.com")
    await _call(hass, "allow_domain", list="allow_default", domain="*.a.example.com")
    client = await hass_client_no_auth()

    response = await client.get(entry.runtime_data.lists.path("allow_default"))

    assert response.status == 200
    assert response.content_type == "text/plain"
    assert response.headers["Cache-Control"] == "no-store"
    assert "Access-Control-Allow-Origin" not in response.headers
    assert await response.text() == "*.a.example.com\nb.example.com\n"

    empty = await client.get(entry.runtime_data.lists.path("deny_default"))
    assert empty.status == 200
    assert await empty.text() == ""


async def test_endpoint_refuses_everything_else_the_same_way(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    lists = entry.runtime_data.lists
    token = lists.token
    client = await hass_client_no_auth()
    base = f"/api/{DOMAIN}/lists"

    bad_paths = [
        f"{base}/{'x' * len(token)}/allow_default.txt",
        f"{base}/{token[:-1]}/allow_default.txt",
        f"{base}/{token}x/allow_default.txt",
        f"{base}/{token.swapcase()}/allow_default.txt",
        f"{base}/{token}/no_such_list.txt",
        f"{base}/{token}/allow_default",
        f"{base}/{token}/allow_default.json",
        f"{base}/{token}/.txt",
    ]
    bodies = set()
    for path in bad_paths:
        response = await client.get(path)
        assert response.status == 404, path
        bodies.add(await response.text())
    assert len(bodies) == 1

    # Home Assistant's own request filter rejects path traversal before the
    # view runs; either way nothing is served.
    traversal = await client.get(f"{base}/{token}/..%2Fallow_default.txt")
    assert traversal.status in (400, 404)

    for method in ("post", "put", "delete", "patch"):
        response = await getattr(client, method)(lists.path("allow_default"))
        assert response.status == 405, method


async def test_endpoint_is_limited_to_allowed_networks(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    entry = await _setup(
        hass, aioclient_mock, {**LIST_OPTIONS, CONF_LIST_NETWORKS: ["192.0.2.0/24"]}
    )
    client = await hass_client_no_auth()

    response = await client.get(entry.runtime_data.lists.path("allow_default"))

    assert response.status == 404


async def test_default_network_does_not_include_the_test_client(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    options = {CONF_LISTS: LIST_OPTIONS[CONF_LISTS]}
    entry = await _setup(hass, aioclient_mock, options)
    client = await hass_client_no_auth()

    response = await client.get(entry.runtime_data.lists.path("allow_default"))

    assert response.status == 404


async def test_invalid_stored_networks_serve_nobody(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    entry = await _setup(
        hass, aioclient_mock, {**LIST_OPTIONS, CONF_LIST_NETWORKS: ["0.0.0.0/0"]}
    )
    client = await hass_client_no_auth()

    response = await client.get(entry.runtime_data.lists.path("allow_default"))

    assert response.status == 404


async def test_rotating_the_token_invalidates_old_addresses(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    lists = entry.runtime_data.lists
    old_path = lists.path("allow_default")
    client = await hass_client_no_auth()
    assert (await client.get(old_path)).status == 200

    await _call(hass, "rotate_list_token")

    assert lists.path("allow_default") != old_path
    assert (await client.get(old_path)).status == 404
    assert (await client.get(lists.path("allow_default"))).status == 200


async def test_endpoint_is_gone_when_the_entry_is_unloaded(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    path = entry.runtime_data.lists.path("allow_default")
    client = await hass_client_no_auth()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert (await client.get(path)).status == 404


# --- Persistence ------------------------------------------------------------


async def test_entries_and_token_survive_a_restart(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(hass, aioclient_mock)
    await _call(hass, "block_domain", list="deny_default", domain="ads.example.net")
    token = entry.runtime_data.lists.token

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.lists.token == token
    assert (await _call(hass, "get_list", list="deny_default"))["entries"] == [
        "ads.example.net"
    ]


async def test_tampered_store_is_cleaned_on_load(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_URL: BASE_URL}, options=LIST_OPTIONS
    )
    key = storage_key(entry.entry_id)
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {
            "token": "short",
            "lists": {
                "allow_default": ["ok.example.com", "/.*/", "*", 5, "bad name"],
                "allow_quarantine": ["tv.example.com", "*.wild.example.com"],
                "deleted_list": ["leftover.example.com"],
                "deny_default": "not a list",
            },
        },
    }
    assert await async_setup_component(hass, "http", {})
    aioclient_mock.get(STATUS_URL, json=ENABLED)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    lists = entry.runtime_data.lists
    assert lists.token != "short"
    assert len(lists.token) >= 40
    assert lists.entries("allow_default") == ["ok.example.com"]
    assert lists.entries("allow_quarantine") == ["tv.example.com"]
    assert lists.entries("deny_default") == []
    stored = hass_storage[key]["data"]
    assert stored["token"] == lists.token
    assert set(stored["lists"]) == {"allow_default", "allow_quarantine", "deny_default"}


async def test_tampered_definitions_are_dropped(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(
        hass,
        aioclient_mock,
        {
            CONF_LISTS: {
                "good": {"type": "deny"},
                "../evil": {"type": "allow"},
                "Upper": {"type": "allow"},
                "weird": {"type": "regex"},
                "broken": "allow",
            },
            CONF_LIST_NETWORKS: LOOPBACK,
        },
    )

    assert list(entry.runtime_data.lists.definitions) == ["good"]


async def test_removing_the_entry_deletes_the_lists(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    entry = await _setup(hass, aioclient_mock)
    key = storage_key(entry.entry_id)
    assert key in hass_storage

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert key not in hass_storage


# --- Sensors ----------------------------------------------------------------


async def test_a_sensor_counts_each_list(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)

    state = hass.states.get("sensor.ha_blocky_list_deny_default")
    assert state.state == "0"
    assert state.attributes["list_type"] == "deny"
    assert hass.states.get("sensor.ha_blocky_list_allow_quarantine").attributes[
        "exact_only"
    ]

    await _call(hass, "block_domain", list="deny_default", domain="ads.example.net")
    await hass.async_block_till_done()

    assert hass.states.get("sensor.ha_blocky_list_deny_default").state == "1"


async def test_sensor_of_a_deleted_list_is_removed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(hass, aioclient_mock)
    registry = er.async_get(hass)
    assert registry.async_get("sensor.ha_blocky_list_deny_default") is not None

    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_LISTS: {"allow_default": {"type": "allow", "exact_only": False}},
            CONF_LIST_NETWORKS: LOOPBACK,
        },
    )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get("sensor.ha_blocky_list_deny_default") is None
    assert registry.async_get("sensor.ha_blocky_list_allow_default") is not None


# --- Options ----------------------------------------------------------------


async def test_options_define_lists(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(hass, aioclient_mock, {})
    result = await open_options_step(hass, entry, "lists")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "lists"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_ALLOW_LISTS: ["allow_default", "allow_quarantine"],
            CONF_DENY_LISTS: ["deny_default"],
            CONF_EXACT_ONLY_LISTS: ["allow_quarantine"],
            CONF_LIST_NETWORKS: ["192.0.2.0/24"],
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_LISTS: {
            "allow_default": {"type": "allow", "exact_only": False},
            "allow_quarantine": {"type": "allow", "exact_only": True},
            "deny_default": {"type": "deny", "exact_only": False},
        },
        CONF_LIST_NETWORKS: ["192.0.2.0/24"],
    }
    assert set(entry.runtime_data.lists.definitions) == {
        "allow_default",
        "allow_quarantine",
        "deny_default",
    }


async def test_options_show_current_lists_and_default_network(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(hass, aioclient_mock, {CONF_LISTS: LIST_OPTIONS[CONF_LISTS]})

    result = await open_options_step(hass, entry, "lists")

    suggested = {
        str(key): key.description.get("suggested_value")
        for key in result["data_schema"].schema
    }
    assert suggested == {
        CONF_ALLOW_LISTS: ["allow_default", "allow_quarantine"],
        CONF_DENY_LISTS: ["deny_default"],
        CONF_EXACT_ONLY_LISTS: ["allow_quarantine"],
        CONF_LIST_NETWORKS: ["172.30.32.0/23"],
    }


@pytest.mark.parametrize(
    ("user_input", "errors"),
    [
        ({CONF_ALLOW_LISTS: ["Bad Name"]}, {CONF_ALLOW_LISTS: "invalid_list_name"}),
        ({CONF_DENY_LISTS: ["../x"]}, {CONF_DENY_LISTS: "invalid_list_name"}),
        (
            {CONF_ALLOW_LISTS: ["same"], CONF_DENY_LISTS: ["same"]},
            {"base": "duplicate_list_name"},
        ),
        ({CONF_ALLOW_LISTS: ["a", "a"]}, {"base": "duplicate_list_name"}),
        (
            {CONF_ALLOW_LISTS: ["a"], CONF_EXACT_ONLY_LISTS: ["b"]},
            {CONF_EXACT_ONLY_LISTS: "unknown_list_name"},
        ),
        (
            {CONF_ALLOW_LISTS: [f"l{index}" for index in range(21)]},
            {"base": "too_many_lists"},
        ),
        ({CONF_LIST_NETWORKS: ["0.0.0.0/0"]}, {CONF_LIST_NETWORKS: "invalid_network"}),
        ({CONF_LIST_NETWORKS: ["nonsense"]}, {CONF_LIST_NETWORKS: "invalid_network"}),
    ],
)
async def test_options_reject_bad_list_settings(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    user_input: dict[str, Any],
    errors: dict[str, str],
) -> None:
    entry = await _setup(hass, aioclient_mock, {})
    result = await open_options_step(hass, entry, "lists")

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == errors
    assert entry.options == {}


async def test_options_show_list_addresses(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(hass, aioclient_mock)
    lists = entry.runtime_data.lists

    result = await open_options_step(hass, entry, "list_urls")

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "list_urls"
    urls = result["description_placeholders"]["urls"]
    for name in ("allow_default", "deny_default", "allow_quarantine"):
        assert lists.path(name) in urls

    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert entry.options == LIST_OPTIONS
