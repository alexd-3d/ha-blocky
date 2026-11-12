"""Tests for the dashboard command: windows, aggregation, cache and input."""

from __future__ import annotations

import json
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator
from sqlalchemy.engine import URL

from custom_components.ha_blocky import db
from custom_components.ha_blocky.const import DOMAIN
from custom_components.ha_blocky.dashboard import build_window

from .test_db import add_rows
from .test_stats import DB_OPTIONS, log_row

BASE_URL = "http://blocky.example:4000"
ENABLED = {"enabled": True, "disabledGroups": [], "autoEnableInSec": 0}
NOW = datetime(2026, 11, 10, 12, 30, 0, tzinfo=UTC)
KIND = f"{DOMAIN}/dashboard"


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
        options=DB_OPTIONS if options is None else options,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _command(ws: Any, message_id: int, /, **message: Any) -> dict[str, Any]:
    await ws.send_json({"id": message_id, **message})
    return await ws.receive_json()


def _row(
    domain: str,
    *,
    client: str = "192.0.2.10",
    response_type: str = "RESOLVED",
    age: timedelta = timedelta(minutes=10),
    duration_ms: int = 10,
    reason: str = "",
) -> dict[str, Any]:
    return {
        **log_row(
            domain,
            client=client,
            response_type=response_type,
            age=age,
            duration_ms=duration_ms,
        ),
        "reason": reason,
    }


def _seed(log_url: URL) -> None:
    ads = "BLOCKED (ads)"
    add_rows(
        log_url,
        [
            _row("a.example.com", client="192.0.2.10", duration_ms=10),
            _row("a.example.com", client="192.0.2.10", response_type="CACHED"),
            _row("b.example.com", client="192.0.2.12", age=timedelta(minutes=70)),
            _row(
                "ads.example",
                client="192.0.2.11",
                response_type="BLOCKED",
                age=timedelta(minutes=30),
                duration_ms=2,
                reason=ads,
            ),
            _row(
                "ads.example",
                client="192.0.2.11",
                response_type="BLOCKED",
                age=timedelta(minutes=40),
                reason=ads,
            ),
            _row(
                "ads.example",
                client="192.0.2.11",
                response_type="REBIND",
                age=timedelta(minutes=50),
                reason="BLOCKED (other)",
            ),
            _row("local.example", response_type="CUSTOMDNS", age=timedelta(hours=2)),
            _row("weird.example", response_type="WEIRD", age=timedelta(hours=3)),
            # 23:30 yesterday: in the last 24 hours, not today.
            _row("late.example", age=timedelta(hours=13)),
            # Two days ago: only the week and the month see it.
            _row("old.example", age=timedelta(hours=40)),
        ],
    )


@pytest.fixture
async def utc(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Freeze the time and use UTC, so that the windows are easy to state."""
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to(NOW)


# --- Windows ----------------------------------------------------------------


@pytest.fixture
def utc_zone() -> Any:
    original = dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(ZoneInfo("UTC"))
    yield
    dt_util.set_default_time_zone(original)


@pytest.mark.usefixtures("utc_zone")
def test_windows_in_utc() -> None:
    today = build_window("today", NOW)
    assert today.unit == "hour"
    assert today.since == datetime(2026, 11, 10, tzinfo=UTC)
    assert len(today.starts) == 13
    assert today.starts[-1] == datetime(2026, 11, 10, 12, tzinfo=UTC)
    assert today.until == datetime(2026, 11, 10, 13, tzinfo=UTC)

    day = build_window("24h", NOW)
    assert day.unit == "hour"
    assert len(day.starts) == 24
    assert day.starts[0] == datetime(2026, 11, 9, 13, tzinfo=UTC)
    assert day.until == datetime(2026, 11, 10, 13, tzinfo=UTC)

    week = build_window("7d", NOW)
    assert week.unit == "day"
    assert [start.day for start in week.starts] == [4, 5, 6, 7, 8, 9, 10]
    assert week.until == datetime(2026, 11, 11, tzinfo=UTC)
    assert len(build_window("30d", NOW).starts) == 30


def test_day_buckets_start_at_local_midnight_across_summer_time() -> None:
    zone = ZoneInfo("Europe/Kyiv")
    original = dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(zone)
    try:
        window = build_window("30d", NOW)
        assert len(window.starts) == 30
        for start in window.starts:
            assert start.astimezone(zone).time() == time(0, 0)
        gaps = {
            (later - earlier)
            for earlier, later in zip(window.starts, window.starts[1:], strict=False)
        }
        # Ordinary days are 24 hours; the day summer time ends is 25 hours.
        assert gaps == {timedelta(hours=24), timedelta(hours=25)}
        assert window.until - window.starts[-1] == timedelta(hours=24)
    finally:
        dt_util.set_default_time_zone(original)


# --- The command ------------------------------------------------------------


@pytest.mark.usefixtures("enable_custom_integrations", "utc")
async def test_dashboard_aggregates_the_last_24_hours(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    _seed(log_url)
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=KIND, period="24h", rows=5)

    assert response["success"], response
    result = response["result"]
    assert result["state"] == "ok"
    assert (result["period"], result["rows"]) == ("24h", 5)
    assert result["since"] == "2026-11-09T13:00:00+00:00"
    assert result["until"] == "2026-11-10T13:00:00+00:00"
    totals = result["totals"]
    assert totals["queries"] == 9
    assert totals["categories"] == {
        "resolved": 3,
        "cached": 1,
        "local": 1,
        "blocked": 3,
        "other": 1,
    }
    assert sum(totals["categories"].values()) == totals["queries"]
    assert totals["unique_domains"] == 6
    assert totals["avg_duration_ms"] == 9.1

    buckets = result["buckets"]
    assert buckets["unit"] == "hour"
    items = buckets["items"]
    assert len(items) == 24
    assert items[0]["start"] == "2026-11-09T13:00:00+00:00"
    assert items[-1]["start"] == "2026-11-10T12:00:00+00:00"
    assert sum(sum(item["categories"].values()) for item in items) == 9
    last = items[-1]["categories"]
    assert (last["resolved"], last["cached"], last["blocked"]) == (1, 1, 1)
    before = items[-2]["categories"]
    assert (before["resolved"], before["blocked"]) == (1, 2)  # 11:20, 11:40, 11:50
    assert items[10]["categories"]["resolved"] == 1  # late.example, 23:30

    clients = {item["address"]: item for item in result["top_clients"]}
    assert [item["address"] for item in result["top_clients"]][:2] == [
        "192.0.2.10",
        "192.0.2.11",
    ]
    assert clients["192.0.2.11"]["count"] == 3
    assert clients["192.0.2.11"]["categories"]["blocked"] == 3
    assert clients["192.0.2.11"]["client_name"] is None
    assert clients["192.0.2.11"]["last_seen"] == "2026-11-10T12:00:00+00:00"
    assert clients["192.0.2.10"]["count"] == 5

    domains = result["top_domains"]
    assert [item["name"] for item in domains][:2] == ["ads.example", "a.example.com"]
    assert domains[1]["categories"]["cached"] == 1
    assert domains[1]["categories"]["resolved"] == 1
    assert "reason" not in domains[0]

    blocked = result["top_blocked"]
    assert [item["name"] for item in blocked] == ["ads.example"]
    assert blocked[0]["count"] == 3
    assert blocked[0]["categories"]["blocked"] == 3
    assert blocked[0]["reason"] == "BLOCKED (ads)"

    meta = result["meta"]
    assert meta["blocky_version"] is None
    assert meta["version"]
    assert meta["generated_at"] == "2026-11-10T12:30:00+00:00"
    assert "generated_at" not in result


@pytest.mark.usefixtures("enable_custom_integrations", "utc")
async def test_dashboard_periods_and_rows(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    _seed(log_url)
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    today = (await _command(client, 1, type=KIND, period="today"))["result"]
    assert today["totals"]["queries"] == 8  # without late.example and old.example
    assert len(today["buckets"]["items"]) == 13

    week = (await _command(client, 2, type=KIND, period="7d"))["result"]
    assert week["totals"]["queries"] == 10
    assert week["buckets"]["unit"] == "day"
    days = week["buckets"]["items"]
    assert [item["start"][:10] for item in days] == [
        "2026-11-04",
        "2026-11-05",
        "2026-11-06",
        "2026-11-07",
        "2026-11-08",
        "2026-11-09",
        "2026-11-10",
    ]
    assert sum(item["categories"]["resolved"] for item in days) == 4
    assert days[4]["categories"]["resolved"] == 1  # old.example
    assert days[5]["categories"]["resolved"] == 1  # late.example
    assert sum(sum(item["categories"].values()) for item in days) == 10

    month = (await _command(client, 3, type=KIND, period="30d"))["result"]
    assert len(month["buckets"]["items"]) == 30
    assert month["totals"]["queries"] == 10

    one = (await _command(client, 4, type=KIND, period="7d", rows=5))["result"]
    assert len(one["top_domains"]) == 5
    assert len(one["top_clients"]) == 3


@pytest.mark.usefixtures("enable_custom_integrations", "utc")
async def test_dashboard_names_clients_without_caching_the_names(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    _seed(log_url)
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    await _command(client, 1, type=KIND)
    named = await _command(
        client, 2, type=f"{DOMAIN}/set_client_name", ip="192.0.2.11", name="Laptop"
    )
    assert named["success"]
    result = (await _command(client, 3, type=KIND))["result"]

    by_address = {item["address"]: item for item in result["top_clients"]}
    assert by_address["192.0.2.11"]["client_name"] == "Laptop"
    assert by_address["192.0.2.10"]["client_name"] is None


@pytest.mark.usefixtures("enable_custom_integrations", "utc")
async def test_dashboard_is_cached_for_a_short_time(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed(log_url)
    calls: list[int] = []
    original = db.QueryLogDatabase.dashboard_totals

    def counting(self: db.QueryLogDatabase, *args: Any) -> Any:
        calls.append(1)
        return original(self, *args)

    monkeypatch.setattr(db.QueryLogDatabase, "dashboard_totals", counting)
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    first = await _command(client, 1, type=KIND, period="24h", rows=10)
    again = await _command(client, 2, type=KIND, period="24h", rows=10)
    assert len(calls) == 1
    assert again["result"] == first["result"]

    await _command(client, 3, type=KIND, period="24h", rows=5)
    await _command(client, 4, type=KIND, period="7d", rows=10)
    assert len(calls) == 3

    add_rows(log_url, [_row("fresh.example", age=timedelta(seconds=5))])
    await _command(client, 5, type=KIND, period="24h", rows=10)
    assert len(calls) == 3

    freezer.tick(timedelta(seconds=31))
    refreshed = await _command(client, 6, type=KIND, period="24h", rows=10)
    assert len(calls) == 4
    assert refreshed["result"]["totals"]["queries"] == 10
    assert refreshed["result"]["meta"]["generated_at"] == "2026-11-10T12:30:31+00:00"


@pytest.mark.usefixtures("enable_custom_integrations", "utc")
async def test_dashboard_without_a_database(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
) -> None:
    await _setup(hass, aioclient_mock, {})
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=KIND, period="7d", rows=20)

    assert response["success"]
    result = response["result"]
    assert result["state"] == "no_database"
    assert (result["period"], result["rows"]) == ("7d", 20)
    assert result["meta"]["version"]
    assert "totals" not in result
    assert "top_clients" not in result


@pytest.mark.usefixtures("enable_custom_integrations", "utc")
async def test_dashboard_errors_are_not_cached_and_hide_details(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    unknown = await _command(client, 1, type=KIND, entry_id="nope")
    assert unknown["error"]["code"] == "entry_not_found"

    def broken(self: db.QueryLogDatabase, *args: Any) -> Any:
        raise db.BlockyDbError("OperationalError: secret detail")

    original = db.QueryLogDatabase.dashboard_totals
    monkeypatch.setattr(db.QueryLogDatabase, "dashboard_totals", broken)
    failed = await _command(client, 2, type=KIND)
    assert failed["error"]["code"] == "database_error"
    assert "secret detail" not in json.dumps(failed)

    monkeypatch.setattr(db.QueryLogDatabase, "dashboard_totals", original)
    recovered = await _command(client, 3, type=KIND)
    assert recovered["success"]
    assert recovered["result"]["totals"]["queries"] == 0


@pytest.mark.usefixtures("enable_custom_integrations", "utc")
async def test_dashboard_cleans_hostile_text_from_the_log(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    hostile_reason = "BLOCKED\n<script>alert(1)</script>\x00\x1b[31m" + "x" * 500
    add_rows(
        log_url,
        [
            _row(
                "evil\x00.example\x1b[0m\n.com",
                client="<img src=x onerror=1>\x07",
                response_type="BLOCKED",
                reason=hostile_reason,
            ),
            _row("x" * 400 + ".example", response_type="BLOCKED"),
            _row("'; DROP TABLE log_entries; --", client="198.51.100.7"),
            # Names that clean to nothing are dropped, not shown empty.
            _row("\x00\x01", client="\x02"),
        ],
    )
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    result = (await _command(client, 1, type=KIND, rows=20))["result"]

    def texts(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [text for item in value.values() for text in texts(item)]
        if isinstance(value, list):
            return [text for item in value for text in texts(item)]
        return []

    for text in texts(
        result["top_clients"] + result["top_domains"] + result["top_blocked"]
    ):
        assert all(char.isprintable() for char in text), repr(text)
        assert len(text) <= 253
    names = [item["name"] for item in result["top_domains"]]
    assert "evil.example[0m.com" in names
    assert "'; DROP TABLE log_entries; --" in names  # data, never SQL
    assert all(len(name) <= 253 for name in names)
    assert "" not in names
    assert [item["address"] for item in result["top_clients"]].count("") == 0
    evil = next(
        item for item in result["top_blocked"] if item["name"].startswith("evil")
    )
    assert evil["reason"].startswith("BLOCKED<script>")
    assert len(evil["reason"]) <= 120
    assert evil["reason"].isprintable()
    odd_client = next(
        item for item in result["top_clients"] if item["address"].startswith("<img")
    )
    assert odd_client["client_name"] is None
    # The table is still there.
    assert (await _command(client, 2, type=KIND, period="7d"))["success"]
    assert result["totals"]["queries"] == 4


@pytest.mark.usefixtures("enable_custom_integrations", "utc")
@pytest.mark.parametrize(
    "message",
    [
        {"period": "1y"},
        {"period": "Today"},
        {"period": 24},
        {"period": ["24h"]},
        {"rows": 7},
        {"rows": 0},
        {"rows": 21},
        {"rows": "10"},
        {"rows": 10.0},
        {"rows": True},
        {"entry_id": 5},
        {"unexpected": True},
    ],
)
async def test_dashboard_rejects_bad_requests(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    message: dict[str, Any],
) -> None:
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=KIND, **message)

    assert response["success"] is False
    assert response["error"]["code"] == "invalid_format"


@pytest.mark.usefixtures("enable_custom_integrations", "utc")
async def test_dashboard_is_admin_only(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: MockUser,
    log_url: URL,
) -> None:
    await _setup(hass, aioclient_mock)
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=KIND)

    assert response["success"] is False
    assert response["error"]["code"] == "unauthorized"


# --- The database layer -----------------------------------------------------


def test_top_rejects_an_unknown_column(log_url: URL) -> None:
    database = db.QueryLogDatabase(log_url)
    since = datetime(2026, 11, 1)
    with pytest.raises(ValueError, match="password"):
        database.dashboard_top("password", since, since + timedelta(days=30), 5)
    database.close()
