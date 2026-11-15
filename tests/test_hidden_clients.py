"""BLO-024: hidden clients leave the card's Dashboard and Query log only."""

from __future__ import annotations

import inspect
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator
from sqlalchemy.engine import URL

from custom_components.ha_blocky import db
from custom_components.ha_blocky.const import DOMAIN, MAX_HIDDEN_CLIENTS
from custom_components.ha_blocky.db import QueryLogDatabase, not_hidden
from custom_components.ha_blocky.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.ha_blocky.settings import (
    SettingError,
    apply_operational,
    hidden_clients,
    read_operational,
)

from .test_card import _command, _setup
from .test_db import NOW, add_rows, make_log, row
from .test_stats import DB_OPTIONS, log_row

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SET = f"{DOMAIN}/set_settings"
GET = f"{DOMAIN}/settings"
LOG = f"{DOMAIN}/query_log"
DASH = f"{DOMAIN}/dashboard"
SINCE = NOW - timedelta(days=1)
UNTIL = NOW + timedelta(hours=1)
ROUTER = "192.0.2.1"
PHONE = "192.0.2.10"


# --- Validation ---------------------------------------------------------------


def test_addresses_are_normalised_and_deduplicated() -> None:
    new = apply_operational(
        {"db_password": "secret"},
        {
            "hidden_clients": [
                " 192.0.2.1 ",
                "::ffff:192.0.2.1",
                "2001:DB8::1",
                "192.0.2.2",
            ]
        },
    )

    assert new["hidden_clients"] == ["192.0.2.1", "2001:db8::1", "192.0.2.2"]
    assert new["db_password"] == "secret"


@pytest.mark.parametrize(
    "value",
    ["192.0.2.1", None, {"a": 1}, 5],
)
def test_the_value_must_be_a_list(value: Any) -> None:
    with pytest.raises(SettingError) as err:
        apply_operational({}, {"hidden_clients": value})
    assert (err.value.field, err.value.code) == ("hidden_clients", "invalid_type")


@pytest.mark.parametrize(
    "bad",
    ["", "example.com", "192.0.2.0/24", "192.0.2.x", "fe80::1%eth0", 5, None, "a" * 50],
)
def test_only_exact_addresses_are_accepted(bad: Any) -> None:
    with pytest.raises(SettingError) as err:
        apply_operational({}, {"hidden_clients": [PHONE, bad]})
    assert (err.value.field, err.value.code) == ("hidden_clients", "invalid_address")
    assert "secret" not in str(err.value)


def test_at_most_fifty_distinct_addresses() -> None:
    fifty = [f"192.0.2.{n}" for n in range(1, MAX_HIDDEN_CLIENTS + 1)]
    assert apply_operational({}, {"hidden_clients": fifty})["hidden_clients"] == fifty
    # Duplicates do not count twice.
    assert (
        len(
            apply_operational({}, {"hidden_clients": [*fifty, *fifty]})[
                "hidden_clients"
            ]
        )
        == MAX_HIDDEN_CLIENTS
    )
    with pytest.raises(SettingError) as err:
        apply_operational({}, {"hidden_clients": [*fifty, "198.51.100.1"]})
    assert err.value.code == "too_many_clients"
    with pytest.raises(SettingError) as err:
        apply_operational({}, {"hidden_clients": ["198.51.100.1"] * 200 + fifty})
    assert err.value.code == "too_many_clients"


def test_a_stored_list_is_cleaned_on_read() -> None:
    options = {"hidden_clients": [PHONE, "not-an-ip", 7, PHONE, "2001:DB8::1"]}
    assert hidden_clients(options) == [PHONE, "2001:db8::1"]
    assert hidden_clients({"hidden_clients": "192.0.2.1"}) == []
    assert hidden_clients({}) == []
    assert hidden_clients({"hidden_clients": [PHONE] * 3 + ["x"] * 100}) == [PHONE]
    assert read_operational({})["hidden_clients"] == []


# --- The SQL ------------------------------------------------------------------


def _rows() -> list[dict[str, Any]]:
    return [
        row("a.example.com", client=ROUTER, response_type="BLOCKED"),
        row("a.example.com", client=ROUTER, response_type="BLOCKED"),
        row("online-check.example.com", client=ROUTER),
        row("online-check.example.com", client=ROUTER),
        row("b.example.com", client=PHONE, response_type="BLOCKED"),
        row("c.example.com", client=PHONE, response_type="CACHED"),
        {**row("d.example.com"), "client_ip": None},
    ]


def _database(tmp_path: Path) -> QueryLogDatabase:
    return QueryLogDatabase(make_log(tmp_path / "log.db", _rows()))


def test_no_hidden_clients_means_no_condition() -> None:
    assert not_hidden(()) is None
    assert not_hidden([]) is None


def test_the_condition_binds_every_address() -> None:
    condition = not_hidden([ROUTER, "x' OR '1'='1"])
    compiled = condition.compile()
    assert "client_ip IS NULL" in str(compiled)
    assert "NOT IN" in str(compiled)
    assert "OR '1'" not in str(compiled)
    assert [ROUTER, "x' OR '1'='1"] in compiled.params.values()


def test_the_query_log_leaves_hidden_rows_out_but_keeps_rows_without_a_client(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)

    shown = database.query_log(since=SINCE, hidden=[ROUTER])
    everything = database.query_log(since=SINCE)

    assert sorted(item["domain"] for item in shown) == [
        "b.example.com",
        "c.example.com",
        "d.example.com",
    ]
    assert len(everything) == 7
    assert database.query_log(since=SINCE, hidden=[ROUTER, PHONE]) == [
        item for item in everything if item["domain"] == "d.example.com"
    ]


@pytest.fixture(params=["one pass", "two steps"])
def path(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    if request.param == "two steps":
        monkeypatch.setattr(db, "MAX_FAST_GROUPS", 0)
    return str(request.param)


@pytest.mark.usefixtures("path")
def test_the_dashboard_statements_leave_hidden_clients_out(tmp_path: Path) -> None:
    database = _database(tmp_path)
    hidden = [ROUTER]

    unique, _average = database.dashboard_domains(SINCE, UNTIL, hidden)
    hours = database.dashboard_hours(SINCE, UNTIL, hidden)
    clients = database.dashboard_top("client", SINCE, UNTIL, 10, hidden=hidden)
    domains = database.dashboard_top("domain", SINCE, UNTIL, 10, hidden=hidden)
    blocked = database.dashboard_top(
        "domain", SINCE, UNTIL, 10, blocked_only=True, with_reason=True, hidden=hidden
    )

    assert unique == 3  # b, c and d; not a or online-check
    assert sum(count for _h, _c, count in hours) == 3
    assert [item["name"] for item in clients] == [PHONE]
    # A row without a client is no hidden client: it stays.
    assert {item["name"] for item in domains} == {
        "b.example.com",
        "c.example.com",
        "d.example.com",
    }
    assert [item["name"] for item in blocked] == ["b.example.com"]
    assert blocked[0]["count"] == 1

    # And without a list nothing changes.
    all_clients = database.dashboard_top("client", SINCE, UNTIL, 10)
    assert {item["name"] for item in all_clients} == {ROUTER, PHONE}
    assert database.dashboard_domains(SINCE, UNTIL)[0] == 5
    assert sum(c for _h, _k, c in database.dashboard_hours(SINCE, UNTIL)) == 7


def test_only_the_card_statements_take_a_hidden_list() -> None:
    """Counters, sensors and new-domain requests never get one."""
    for name in (
        "counts_since",
        "rows_after",
        "client_domains",
        "summary",
        "client_counts",
        "top_domains",
        "top_blocked_domains",
        "top_clients",
    ):
        assert (
            "hidden"
            not in inspect.signature(getattr(QueryLogDatabase, name)).parameters
        )
    for name in ("query_log", "dashboard_domains", "dashboard_hours", "dashboard_top"):
        assert "hidden" in inspect.signature(getattr(QueryLogDatabase, name)).parameters


def test_new_domain_requests_still_see_a_hidden_client(tmp_path: Path) -> None:
    database = _database(tmp_path)

    rows = database.rows_after(0, 100)
    names = database.client_domains(ROUTER, SINCE, 50)

    assert ROUTER in {item.client for item in rows}
    assert "online-check.example.com" in names


# --- The commands -------------------------------------------------------------


async def test_settings_save_a_list_reload_the_entry_and_name_the_clients(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    await _command(
        client, 1, type=f"{DOMAIN}/set_client_name", ip=ROUTER, name="Router"
    )

    saved = await _command(client, 2, type=SET, hidden_clients=[ROUTER, ROUTER])
    await hass.async_block_till_done()

    assert saved["success"], saved
    assert saved["result"]["reloading"] is True
    assert entry.options["hidden_clients"] == [ROUTER]
    described = (await _command(client, 3, type=GET))["result"]["entry"]
    assert described["hidden_clients"] == [{"address": ROUTER, "client_name": "Router"}]

    # The same list again is no change and no reload.
    again = await _command(client, 4, type=SET, hidden_clients=[ROUTER])
    assert again["result"]["reloading"] is False


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (["zzz-secret"], "invalid_address"),
        ("192.0.2.1", "invalid_type"),
        ([f"192.0.2.{n}" for n in range(1, 52)], "too_many_clients"),
    ],
)
async def test_a_bad_list_is_refused_without_echo_and_changes_nothing(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    value: Any,
    code: str,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    before = dict(entry.options)

    response = await _command(client, 1, type=SET, hidden_clients=value)

    assert response["success"] is False
    assert response["error"] == {"code": code, "message": "hidden_clients"}
    assert "zzz-secret" not in json.dumps(response)
    assert entry.options == before


async def test_the_dashboard_and_the_log_leave_hidden_clients_out(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    add_rows(
        log_url,
        [
            log_row("a.example.com", client=ROUTER),
            log_row("a.example.com", client=ROUTER),
            log_row("b.example.com", client=PHONE, response_type="BLOCKED"),
        ],
    )
    await _setup(hass, aioclient_mock, {**DB_OPTIONS, "hidden_clients": [ROUTER]})
    client = await hass_ws_client(hass)

    dashboard = (await _command(client, 1, type=DASH, period="24h"))["result"]
    log = (await _command(client, 2, type=LOG))["result"]
    shown = (await _command(client, 3, type=LOG, show_hidden=True))["result"]

    assert dashboard["totals"]["queries"] == 1
    assert [item["address"] for item in dashboard["top_clients"]] == [PHONE]
    assert dashboard["meta"]["hidden_clients"] == 1
    assert [item["client"] for item in log["rows"]] == [PHONE]
    assert log["hidden_clients"] == 1
    assert len(shown["rows"]) == 3
    assert shown["hidden_clients"] == 1


async def test_without_a_list_nothing_is_hidden_and_the_count_is_zero(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    add_rows(log_url, [log_row("a.example.com", client=ROUTER)])
    await _setup(hass, aioclient_mock, DB_OPTIONS)
    client = await hass_ws_client(hass)

    dashboard = (await _command(client, 1, type=DASH, period="24h"))["result"]
    log = (await _command(client, 2, type=LOG))["result"]

    assert dashboard["totals"]["queries"] == 1
    assert dashboard["meta"]["hidden_clients"] == 0
    assert len(log["rows"]) == 1
    assert log["hidden_clients"] == 0


async def test_sensors_and_counters_still_count_a_hidden_client(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
) -> None:
    add_rows(log_url, [log_row("a.example.com", client=ROUTER) for _ in range(3)])
    entry = await _setup(
        hass, aioclient_mock, {**DB_OPTIONS, "hidden_clients": [ROUTER]}
    )
    stats = entry.runtime_data.stats
    assert stats is not None

    await stats.async_refresh()

    assert stats.data.summary.queries == 3
    assert [item.name for item in stats.data.top_clients] == [ROUTER]


async def test_diagnostics_show_the_count_and_never_the_addresses(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
) -> None:
    entry = await _setup(
        hass, aioclient_mock, {**DB_OPTIONS, "hidden_clients": [ROUTER, PHONE]}
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    dumped = json.dumps(diagnostics, default=str)
    assert diagnostics["hidden_client_count"] == 2
    assert ROUTER not in dumped
    assert PHONE not in dumped
