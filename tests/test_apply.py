"""Tests for "Apply now": the merge into the Blocky app's options, the run with a
faked Supervisor, the opt-in and the refusals. No network: Blocky's API is
mocked and the Supervisor client is a fake. Nothing secret may reach the log.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import aiohttp
import pytest
import yaml
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.ha_blocky import apply, levels
from custom_components.ha_blocky.apply import (
    APPLY_ERRORS,
    ApplyError,
    merge_blocking,
)
from custom_components.ha_blocky.const import (
    CONF_AUTO_APPLY,
    CONF_BASE_GROUPS,
    CONF_CLIENTS,
    CONF_LIST_NETWORKS,
    DOMAIN,
)
from custom_components.ha_blocky.levels import ClientConfig, render_block

from .test_lists import LOOPBACK

pytestmark = pytest.mark.usefixtures("enable_custom_integrations", "hass_storage")

HOST = "4d2c38a0-blocky"
SLUG = "4d2c38a0_blocky"
BASE_URL = f"http://{HOST}:4000"
STATUS_URL = f"{BASE_URL}/api/blocking/status"
REFRESH_URL = f"{BASE_URL}/api/lists/refresh"
ENABLED = {"enabled": True, "disabledGroups": [], "autoEnableInSec": 0}
INTERNAL = "http://ha.example:8123"
DB_PASSWORD = "fake-db-password-xyz"
OWN_CLIENTS = {
    "192.0.2.10": ClientConfig("restricted"),
    "198.51.100.5": ClientConfig("lockdown", True),
}
URLS = {
    "restricted_deny": "http://ha.example:8123/api/ha_blocky/lists/TOKEN/restricted_deny.txt?r=0123abcd",
    "lockdown_allow": "http://ha.example:8123/api/ha_blocky/lists/TOKEN/lockdown_allow.txt?r=0123abcd",
    "unfiltered_empty": "http://ha.example:8123/api/ha_blocky/lists/TOKEN/unfiltered_empty.txt?r=0123abcd",
}


def app_options() -> dict[str, Any]:
    """Options of the Blocky app as the user has them, with foreign content."""
    return {
        "custom_config": False,
        "log_level": "info",
        "query_log": {"type": "mysql", "target": "db", "password": DB_PASSWORD},
        "blocking": {
            "block_type": "zeroIp",
            "denylists": [
                {"name": "default", "sources": ["https://lists.example.com/ads.txt"]},
                {"name": "restricted", "sources": ["http://old.example/x?r=00000000"]},
            ],
            "allowlists": [
                {"name": "default", "sources": ["https://lists.example.com/ok.txt"]},
                {"name": "lockdown", "sources": ["http://old.example/y"]},
            ],
            "client_groups_block": [
                {"name": "default", "lists": ["default"]},
                {"name": "192.0.2.0/24", "lists": ["default", "restricted"]},
                {"name": "kid-laptop", "lists": ["restricted"]},
                {"name": "203.0.113.7", "lists": ["default"]},
                {"name": "192.0.2.10", "lists": ["default"]},
                {"name": "203.0.113.99", "lists": ["lockdown"]},
            ],
        },
    }


# --- The merge (pure) ----------------------------------------------------------


def test_merge_adds_our_entries_and_keeps_everything_else() -> None:
    options = app_options()
    before = copy.deepcopy(options)

    merged = merge_blocking(options, ("default",), OWN_CLIENTS, URLS)

    assert options == before  # the input is not mutated
    assert merged["query_log"] == before["query_log"]
    assert merged["log_level"] == "info" and merged["custom_config"] is False
    assert merged["blocking"]["block_type"] == "zeroIp"
    blocking = merged["blocking"]
    assert blocking["denylists"] == [
        before["blocking"]["denylists"][0],
        {"name": "restricted", "sources": [URLS["restricted_deny"]]},
        {"name": "unfiltered", "sources": [URLS["unfiltered_empty"]]},
    ]
    assert blocking["allowlists"] == [
        before["blocking"]["allowlists"][0],
        {"name": "lockdown", "sources": [URLS["lockdown_allow"]]},
    ]
    # Kept: default, the CIDR range, the host name, an IP that is neither ours
    # nor uses our groups. Dropped: our client's old line (192.0.2.10) and a
    # stale line that uses one of our groups (203.0.113.99).
    assert blocking["client_groups_block"] == [
        {"name": "default", "lists": ["default"]},
        {"name": "192.0.2.0/24", "lists": ["default", "restricted"]},
        {"name": "kid-laptop", "lists": ["restricted"]},
        {"name": "203.0.113.7", "lists": ["default"]},
        {"name": "192.0.2.10", "lists": ["default", "restricted"]},
        {"name": "198.51.100.5", "lists": ["lockdown"]},
    ]


def test_merge_compares_ip_addresses_normalised() -> None:
    options = {
        "blocking": {
            "client_groups_block": [
                {"name": "2001:0DB8:0:0:0:0:0:1", "lists": ["default"]},
                {"name": "::ffff:192.0.2.10", "lists": ["default"]},
            ]
        }
    }
    clients = {
        "2001:db8::1": ClientConfig("unfiltered"),
        "192.0.2.10": ClientConfig("restricted"),
    }

    merged = merge_blocking(options, ("default",), clients, URLS)

    assert [item["name"] for item in merged["blocking"]["client_groups_block"]] == [
        "192.0.2.10",
        "2001:db8::1",
    ]


def test_merge_is_idempotent() -> None:
    once = merge_blocking(app_options(), ("default",), OWN_CLIENTS, URLS)

    assert merge_blocking(once, ("default",), OWN_CLIENTS, URLS) == once


def test_merge_removes_clients_that_lost_their_level() -> None:
    once = merge_blocking(app_options(), ("default",), OWN_CLIENTS, URLS)
    twice = merge_blocking(once, ("default",), {}, URLS)

    names = [item["name"] for item in twice["blocking"]["client_groups_block"]]
    assert "192.0.2.10" not in names and "198.51.100.5" not in names
    assert "default" in names and "203.0.113.7" in names


def test_merge_equals_what_render_block_describes() -> None:
    clients = {**OWN_CLIENTS, "2001:db8::1": ClientConfig("unfiltered")}
    rendered = yaml.safe_load(render_block(("default", "ads"), clients, URLS)["app"])

    merged = merge_blocking({"blocking": {}}, ("default", "ads"), clients, URLS)

    assert merged["blocking"] == rendered["blocking"]


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"blocking": None},
        {"blocking": []},
        {"blocking": {"denylists": None}},
        {"blocking": {"denylists": "x"}},
        {"blocking": {"denylists": ["x"]}},
        {"blocking": {"denylists": [{"name": 1, "sources": []}]}},
        {"blocking": {"denylists": [{"name": "a"}]}},
        {"blocking": {"denylists": [{"name": "a", "sources": "u"}]}},
        {"blocking": {"denylists": [{"name": "a", "sources": [1]}]}},
        {"blocking": {"allowlists": {"a": ["u"]}}},
        {"blocking": {"allowlists": [{"name": "a", "sources": [None]}]}},
        {"blocking": {"client_groups_block": {"a": ["b"]}}},
        {"blocking": {"client_groups_block": [{"name": "a"}]}},
        {"blocking": {"client_groups_block": [{"name": "a", "lists": "b"}]}},
        {"blocking": {"client_groups_block": [{"name": None, "lists": []}]}},
        {"blocking": {"client_groups_block": [{"name": "a", "lists": [["b"]]}]}},
    ],
)
def test_merge_refuses_hostile_structures(options: dict[str, Any]) -> None:
    before = copy.deepcopy(options)

    with pytest.raises(ApplyError) as raised:
        merge_blocking(options, ("default",), OWN_CLIENTS, URLS)

    assert raised.value.code == "apply_unexpected"
    assert options == before


def test_merge_treats_missing_keys_as_empty_lists() -> None:
    merged = merge_blocking({"blocking": {"x": 1}}, ("default",), {}, URLS)

    assert merged["blocking"]["x"] == 1
    assert merged["blocking"]["client_groups_block"] == []
    assert len(merged["blocking"]["denylists"]) == 2


# --- The run with a faked Supervisor ---------------------------------------------


class FakeSupervisor:
    """A Supervisor client that records its calls and can be told to fail."""

    def __init__(
        self,
        options: Any,
        slugs: tuple[str, ...] = (SLUG, "core_mariadb"),
        mock: AiohttpClientMocker | None = None,
    ) -> None:
        self.options = options
        self.slugs = slugs
        self.calls: list[tuple[str, Any]] = []
        self.valid = True
        self.validate_error: Exception | None = None
        self.list_error: Exception | None = None
        self.set_errors: list[Exception | None] = []
        # After each restart: True = the API answers, False = it does not.
        self.api_after_restart: list[bool] = [True]
        self.mock = mock
        self.addons = self

    async def list(self) -> list[Any]:
        if self.list_error:
            raise self.list_error
        return [SimpleNamespace(slug=slug) for slug in self.slugs]

    async def addon_info(self, slug: str) -> Any:
        self.calls.append(("info", slug))
        return SimpleNamespace(options=copy.deepcopy(self.options))

    async def addon_config_validate(self, slug: str, config: Any) -> Any:
        self.calls.append(("validate", slug))
        if self.validate_error:
            raise self.validate_error
        return SimpleNamespace(valid=self.valid, message=f"secret {DB_PASSWORD}")

    async def set_addon_options(self, slug: str, options: Any) -> None:
        self.calls.append(("set", copy.deepcopy(options.config)))
        if self.set_errors and (error := self.set_errors.pop(0)):
            raise error
        self.options = copy.deepcopy(options.config)

    async def restart_addon(self, slug: str) -> None:
        self.calls.append(("restart", slug))
        answers = self.api_after_restart.pop(0) if self.api_after_restart else True
        assert self.mock is not None
        self.mock.clear_requests()
        if answers:
            self.mock.get(STATUS_URL, json=ENABLED)
        else:
            self.mock.get(STATUS_URL, exc=aiohttp.ClientError("down"))
        self.mock.post(REFRESH_URL, text="")

    @property
    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.calls]


async def _setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
    options: dict[str, Any] | None = None,
    app: Any = "default",
    hassio: bool = True,
) -> tuple[MockConfigEntry, FakeSupervisor]:
    assert await async_setup_component(hass, "http", {})
    hass.config.internal_url = INTERNAL
    aioclient_mock.get(STATUS_URL, json=ENABLED)
    aioclient_mock.post(REFRESH_URL, text="")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_URL: BASE_URL},
        options=(
            {
                CONF_LIST_NETWORKS: LOOPBACK,
                CONF_AUTO_APPLY: True,
                CONF_BASE_GROUPS: ["default"],
                CONF_CLIENTS: {"192.0.2.10": {"level": "restricted"}},
            }
            if options is None
            else options
        ),
        minor_version=2,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    if hassio:
        hass.config.components.add("hassio")
    fake = FakeSupervisor(
        app_options() if app == "default" else app, mock=aioclient_mock
    )
    monkeypatch.setattr(apply, "_supervisor", lambda hass: fake)
    monkeypatch.setattr(apply, "APPLY_POLL_SECONDS", 1)

    async def no_sleep(seconds: float) -> None:
        await asyncio.sleep(0)  # (a frozen clock never ends a real sleep)

    monkeypatch.setattr(apply, "_sleep", no_sleep)
    monkeypatch.setattr(apply, "APPLY_WAIT_SECONDS", 5)
    return entry, fake


async def _command(ws: Any, message_id: int, /, **message: Any) -> dict[str, Any]:
    await ws.send_json({"id": message_id, **message})
    return await ws.receive_json()


APPLY_NOW = {"type": f"{DOMAIN}/apply_now"}


async def test_happy_path_writes_then_restarts_and_reports(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    monkeypatch: pytest.MonkeyPatch,
    freezer: FrozenDateTimeFactory,
) -> None:
    entry, fake = await _setup(hass, aioclient_mock, monkeypatch)
    ws = await hass_ws_client(hass)

    response = await _command(ws, 1, **APPLY_NOW)

    assert response["success"], response
    assert response["result"]["result"] == "ok"
    assert fake.kinds == ["info", "validate", "set", "restart"]
    written = fake.calls[2][1]
    assert written["query_log"]["password"] == DB_PASSWORD  # through memory only
    names = [item["name"] for item in written["blocking"]["client_groups_block"]]
    assert "192.0.2.10" in names
    last = entry.runtime_data.last_apply
    assert last is not None and last["result"] == "ok"
    assert last["at"].endswith("+00:00")
    # The answer to the card is read from the levels command.
    levels = await _command(ws, 2, type=f"{DOMAIN}/levels")
    assert levels["result"]["auto_apply"] is True
    assert levels["result"]["apply_available"] is True
    assert levels["result"]["last_apply"]["result"] == "ok"
    # The response never carries options or addresses.
    assert DB_PASSWORD not in str(response)
    assert "TOKEN" not in str(response) and "token" not in str(response["result"])


async def test_second_run_is_unchanged_and_writes_nothing(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
    freezer: FrozenDateTimeFactory,
) -> None:
    entry, fake = await _setup(hass, aioclient_mock, monkeypatch)

    assert await apply.async_apply(hass, entry) == "ok"
    fake.calls.clear()
    freezer.tick(timedelta(seconds=61))

    assert await apply.async_apply(hass, entry) == "unchanged"
    assert fake.kinds == ["info"]
    assert entry.runtime_data.last_apply["result"] == "unchanged"


async def test_invalid_options_are_not_written(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, fake = await _setup(hass, aioclient_mock, monkeypatch)
    fake.valid = False

    with pytest.raises(ApplyError) as raised:
        await apply.async_apply(hass, entry)

    assert raised.value.code == "apply_invalid"
    assert fake.kinds == ["info", "validate"]


async def test_a_validation_error_is_invalid_too(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, fake = await _setup(hass, aioclient_mock, monkeypatch)
    fake.validate_error = RuntimeError(f"boom {DB_PASSWORD}")

    with pytest.raises(ApplyError) as raised:
        await apply.async_apply(hass, entry)

    assert raised.value.code == "apply_invalid"
    assert "set" not in fake.kinds


async def test_api_never_answers_restores_the_previous_options(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, fake = await _setup(hass, aioclient_mock, monkeypatch)
    original = app_options()
    fake.api_after_restart = [False, True]

    result = await apply.async_apply(hass, entry)

    assert result == "restored"
    assert fake.kinds == ["info", "validate", "set", "restart", "set", "restart"]
    assert fake.calls[2][1] != original
    assert fake.calls[4][1] == original
    assert fake.options == original
    assert entry.runtime_data.last_apply["result"] == "restored"


async def test_restore_that_does_not_help_is_reported(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, fake = await _setup(hass, aioclient_mock, monkeypatch)
    fake.api_after_restart = [False, False]

    assert await apply.async_apply(hass, entry) == "restore_failed"
    assert entry.runtime_data.last_apply["result"] == "restore_failed"


async def test_a_supervisor_error_after_the_write_restores(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, fake = await _setup(hass, aioclient_mock, monkeypatch)
    fake.set_errors = [RuntimeError(f"bad {DB_PASSWORD}"), None]
    original = app_options()

    assert await apply.async_apply(hass, entry) == "restored"
    assert fake.calls[-2][1] == original


async def test_a_supervisor_error_before_the_write_is_apply_failed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, fake = await _setup(hass, aioclient_mock, monkeypatch)
    fake.list_error = RuntimeError(DB_PASSWORD)

    with pytest.raises(ApplyError) as raised:
        await apply.async_apply(hass, entry)

    assert raised.value.code == "apply_failed"
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert fake.calls == []


# --- Refusals ----------------------------------------------------------------------


async def test_off_by_default(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _entry, fake = await _setup(
        hass, aioclient_mock, monkeypatch, options={CONF_LIST_NETWORKS: LOOPBACK}
    )
    ws = await hass_ws_client(hass)

    levels = await _command(ws, 1, type=f"{DOMAIN}/levels")
    response = await _command(ws, 2, **APPLY_NOW)

    assert levels["result"]["auto_apply"] is False
    assert response["error"]["code"] == "apply_off"
    assert fake.calls == []


async def test_set_auto_apply_stores_the_option(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, _ = await _setup(
        hass, aioclient_mock, monkeypatch, options={CONF_LIST_NETWORKS: LOOPBACK}
    )
    ws = await hass_ws_client(hass)

    on = await _command(ws, 1, type=f"{DOMAIN}/set_auto_apply", enabled=True)
    assert on["success"] and entry.options[CONF_AUTO_APPLY] is True
    assert entry.options[CONF_LIST_NETWORKS] == LOOPBACK
    off = await _command(ws, 2, type=f"{DOMAIN}/set_auto_apply", enabled=False)
    assert off["success"] and entry.options[CONF_AUTO_APPLY] is False
    for bad in ("yes", 1, None):
        response = await _command(ws, 3, type=f"{DOMAIN}/set_auto_apply", enabled=bad)
        assert response["success"] is False
    assert entry.options[CONF_AUTO_APPLY] is False


async def test_the_opt_in_is_neither_an_entity_nor_a_service(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup(hass, aioclient_mock, monkeypatch)

    services = hass.services.async_services_for_domain(DOMAIN)
    assert not [name for name in services if "apply" in name]
    assert not [s for s in hass.states.async_entity_ids() if "apply" in s]


@pytest.mark.parametrize(
    "message",
    [
        {"type": f"{DOMAIN}/set_auto_apply", "enabled": True},
        {"type": f"{DOMAIN}/apply_now"},
    ],
)
async def test_both_apply_commands_are_admin_only(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: MockUser,
    monkeypatch: pytest.MonkeyPatch,
    message: dict[str, Any],
) -> None:
    entry, fake = await _setup(
        hass, aioclient_mock, monkeypatch, options={CONF_LIST_NETWORKS: LOOPBACK}
    )
    hass_admin_user.groups = []
    ws = await hass_ws_client(hass)

    response = await _command(ws, 1, **message)

    assert response["error"]["code"] == "unauthorized"
    assert CONF_AUTO_APPLY not in entry.options
    assert fake.calls == []


async def test_no_supervisor(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, fake = await _setup(hass, aioclient_mock, monkeypatch, hassio=False)
    ws = await hass_ws_client(hass)

    levels = await _command(ws, 1, type=f"{DOMAIN}/levels")
    response = await _command(ws, 2, **APPLY_NOW)

    assert levels["success"] and levels["result"]["apply_available"] is False
    assert response["error"]["code"] == "apply_no_supervisor"
    assert fake.calls == []


async def test_setup_works_without_hassio(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, _ = await _setup(hass, aioclient_mock, monkeypatch, hassio=False)

    assert "hassio" not in hass.config.components
    assert entry.state.name == "LOADED"


@pytest.mark.parametrize(
    ("setup", "code"),
    [
        ({"slugs": ("core_mariadb",)}, "apply_app_not_found"),
        ({"slugs": (SLUG, "4D2C38A0-blocky")}, "apply_app_not_found"),
        ({"app": ["not", "a", "dict"]}, "apply_unexpected"),
        ({"app": {"custom_config": True, "blocking": {}}}, "apply_custom_config"),
        ({"app": {"custom_config": False, "blocking": "x"}}, "apply_unexpected"),
        ({"app": {"custom_config": False}}, "apply_unexpected"),
    ],
)
async def test_refusals_before_any_write(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
    setup: dict[str, Any],
    code: str,
) -> None:
    entry, fake = await _setup(
        hass, aioclient_mock, monkeypatch, app=setup.get("app", "default")
    )
    if "slugs" in setup:
        fake.slugs = setup["slugs"]

    with pytest.raises(ApplyError) as raised:
        await apply.async_apply(hass, entry)

    assert raised.value.code == code
    assert "set" not in fake.kinds and "restart" not in fake.kinds
    assert entry.runtime_data.last_apply is None


async def test_the_app_is_found_by_its_host_name_case_insensitively(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, fake = await _setup(hass, aioclient_mock, monkeypatch)
    fake.slugs = ("4D2C38A0_Blocky",)

    assert await apply.async_apply(hass, entry) == "ok"
    assert ("info", "4D2C38A0_Blocky") in fake.calls


async def test_no_internal_url(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry, fake = await _setup(hass, aioclient_mock, monkeypatch)

    def no_url(*args: Any, **kwargs: Any) -> str:
        raise NoURLAvailableError

    monkeypatch.setattr(levels, "get_url", no_url)

    with pytest.raises(ApplyError) as raised:
        await apply.async_apply(hass, entry)

    assert raised.value.code == "apply_no_url"
    assert "set" not in fake.kinds


async def test_too_soon_and_busy(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
    freezer: FrozenDateTimeFactory,
) -> None:
    entry, fake = await _setup(hass, aioclient_mock, monkeypatch)
    assert await apply.async_apply(hass, entry) == "ok"

    freezer.tick(timedelta(seconds=30))
    with pytest.raises(ApplyError) as raised:
        await apply.async_apply(hass, entry)
    assert raised.value.code == "apply_too_soon"

    freezer.tick(timedelta(seconds=31))
    gate = asyncio.Event()
    original = fake.addon_info

    async def slow(slug: str) -> Any:
        await gate.wait()
        return await original(slug)

    fake.addon_info = slow  # type: ignore[method-assign]
    running = hass.async_create_task(apply.async_apply(hass, entry))
    await asyncio.sleep(0)
    with pytest.raises(ApplyError) as raised:
        await apply.async_apply(hass, entry)
    assert raised.value.code == "apply_busy"
    gate.set()
    assert await running == "unchanged"


async def test_every_refusal_code_has_a_fixed_text() -> None:
    assert set(APPLY_ERRORS) == {
        "apply_off",
        "apply_no_supervisor",
        "apply_busy",
        "apply_too_soon",
        "apply_app_not_found",
        "apply_custom_config",
        "apply_no_url",
        "apply_unexpected",
        "apply_invalid",
        "apply_failed",
    }
    assert all(text.endswith(".") for text in APPLY_ERRORS.values())


async def test_nothing_secret_reaches_the_log_or_an_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    freezer: FrozenDateTimeFactory,
) -> None:
    caplog.set_level(logging.DEBUG)
    entry, fake = await _setup(hass, aioclient_mock, monkeypatch)
    ws = await hass_ws_client(hass)
    answers: list[Any] = []

    # A success, a restore, a Supervisor failure and a refusal.
    answers.append(await _command(ws, 1, **APPLY_NOW))
    freezer.tick(timedelta(seconds=61))
    fake.options = app_options()
    fake.api_after_restart = [True]
    fake.set_errors = [RuntimeError(f"x {DB_PASSWORD}")]
    answers.append(await _command(ws, 2, **APPLY_NOW))
    freezer.tick(timedelta(seconds=61))
    fake.list_error = RuntimeError(f"y {DB_PASSWORD} TOKEN")
    answers.append(await _command(ws, 3, **APPLY_NOW))

    token = entry.runtime_data.lists.path("restricted_deny").split("/")[4]
    # The test harness logs storage writes (with the token) at DEBUG; only the
    # lines of this integration are ours.
    ours = " | ".join(
        r.getMessage() for r in caplog.records if r.name.startswith("custom_components")
    )
    dumped = ours + str(answers)
    assert "Blocky apply finished: ok" in ours
    assert DB_PASSWORD not in caplog.text
    assert token not in dumped
    assert "TOKEN" not in dumped
    assert "blocking" not in ours
    codes = [
        a["result"]["result"] if a["success"] else a["error"]["code"] for a in answers
    ]
    assert codes == ["ok", "restored", "apply_failed"]
