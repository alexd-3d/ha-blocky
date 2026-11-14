"""The faster dashboard: fewer statements per round and a stale answers."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator
from sqlalchemy.engine import URL

from custom_components.ha_blocky import db
from custom_components.ha_blocky.dashboard import build_window, collect
from custom_components.ha_blocky.db import QueryLogDatabase

from .test_dashboard import KIND, NOW, _command, _seed, _setup, utc  # noqa: F401
from .test_db import make_log, row

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _labels(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage().split(":")[0].removeprefix("query ")
        for r in caplog.records
        if r.name == "custom_components.ha_blocky.db"
        and r.getMessage().startswith("query ")
    ]


def test_a_top_list_is_a_rank_and_a_category_statement(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    rows = [
        row("a.example", response_type="RESOLVED"),
        row("a.example", response_type="CACHED"),
        row("a.example", response_type="BLOCKED"),
        row("a.example", response_type="REBIND"),
        row("a.example", response_type="CUSTOMDNS"),
        row("a.example", response_type="WHATEVER"),
        row("b.example", response_type="CACHED"),
    ]
    database = QueryLogDatabase(make_log(tmp_path / "log.db", rows))
    caplog.set_level(logging.DEBUG, logger="custom_components.ha_blocky.db")
    since, until = NOW - timedelta(days=1), NOW + timedelta(hours=1)

    items = database.dashboard_top("domain", since, until, 5)

    assert _labels(caplog) == [
        "dashboard_top.ranked",
        "dashboard_top.categories",
    ]
    assert items[0]["name"] == "a.example" and items[0]["count"] == 6
    assert items[0]["categories"] == {
        "resolved": 1,
        "cached": 1,
        "local": 1,
        "blocked": 2,
        "other": 1,
    }
    assert items[1]["categories"]["cached"] == 1 and items[1]["count"] == 1

    caplog.clear()
    blocked = database.dashboard_top(
        "domain", since, until, 5, blocked_only=True, with_reason=True
    )
    assert _labels(caplog) == [
        "dashboard_top.ranked",
        "dashboard_top.categories",
        "dashboard_top.reasons",
    ]
    assert blocked[0]["categories"]["blocked"] == 2
    assert sum(blocked[0]["categories"].values()) == 2
    database.close()


def test_a_round_needs_nine_statements_and_totals_match_the_hours(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    rows = [row(f"{i}.example", response_type="CACHED") for i in range(3)]
    rows.append(row("x.example", response_type="BLOCKED"))
    database = QueryLogDatabase(make_log(tmp_path / "log.db", rows))
    caplog.set_level(logging.DEBUG, logger="custom_components.ha_blocky.db")

    result = collect(database, build_window("24h", NOW), "24h", 5)

    assert _labels(caplog) == [
        "dashboard_domains",
        "dashboard_hours",
        "dashboard_top.ranked",
        "dashboard_top.categories",
        "dashboard_top.ranked",
        "dashboard_top.categories",
        "dashboard_top.ranked",
        "dashboard_top.categories",
        "dashboard_top.reasons",
    ]
    totals = result["totals"]
    assert totals["categories"]["cached"] == 3 and totals["categories"]["blocked"] == 1
    assert totals["queries"] == 4 and totals["unique_domains"] == 4
    from_buckets = sum(
        item["categories"]["cached"] for item in result["buckets"]["items"]
    )
    assert from_buckets == 3
    database.close()


@pytest.mark.usefixtures("utc")
async def test_a_stale_long_period_is_served_while_one_refresh_runs(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed(log_url)
    calls: list[int] = []
    original = db.QueryLogDatabase.dashboard_domains

    def counting(self: db.QueryLogDatabase, *args: Any) -> Any:
        calls.append(1)
        return original(self, *args)

    monkeypatch.setattr(db.QueryLogDatabase, "dashboard_domains", counting)
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    first = await _command(client, 1, type=KIND, period="7d", rows=10)
    freezer.tick(timedelta(seconds=200))
    await _command(client, 2, type=KIND, period="7d", rows=10)
    assert len(calls) == 1  # still fresh (5 minutes)

    freezer.tick(timedelta(seconds=200))  # 400 s: stale, served at once
    stale = await _command(client, 3, type=KIND, period="7d", rows=10)
    assert stale["result"]["meta"]["stale"] is True
    assert (
        stale["result"]["meta"]["generated_at"]
        == (first["result"]["meta"]["generated_at"])
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(calls) == 2  # the background round ran, once
    fresh = await _command(client, 4, type=KIND, period="7d", rows=10)
    assert (
        fresh["result"]["meta"]["generated_at"]
        != (first["result"]["meta"]["generated_at"])
    )
    assert len(calls) == 2

    # Older than an hour: no stale answer, the caller waits for a new round.
    freezer.tick(timedelta(hours=2))
    await _command(client, 5, type=KIND, period="7d", rows=10)
    assert len(calls) == 3

    # The short periods go stale after 30 seconds, too.
    await _command(client, 6, type=KIND, period="24h", rows=10)
    assert len(calls) == 4
    freezer.tick(timedelta(seconds=40))
    short = await _command(client, 7, type=KIND, period="24h", rows=10)
    assert short["result"]["meta"]["stale"] is True
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(calls) == 5
    fresh = await _command(client, 8, type=KIND, period="24h", rows=10)
    assert fresh["result"]["meta"]["stale"] is False and len(calls) == 5


@pytest.mark.usefixtures("utc")
async def test_stale_refresh_failure_keeps_the_old_answer(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed(log_url)
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    first = await _command(client, 1, type=KIND, period="30d", rows=10)

    def broken(self: db.QueryLogDatabase, *args: Any) -> Any:
        raise db.BlockyDbError("OperationalError")

    monkeypatch.setattr(db.QueryLogDatabase, "dashboard_domains", broken)
    freezer.tick(timedelta(minutes=6))
    stale = await _command(client, 2, type=KIND, period="30d", rows=10)
    await hass.async_block_till_done(wait_background_tasks=True)
    again = await _command(client, 3, type=KIND, period="30d", rows=10)

    assert stale["success"] and again["success"]
    assert (
        again["result"]["meta"]["generated_at"]
        == (first["result"]["meta"]["generated_at"])
    )


def test_the_card_shows_the_last_answer_of_a_period_from_memory_only() -> None:
    source = (
        Path(__file__).resolve().parent.parent
        / "custom_components"
        / "ha_blocky"
        / "frontend"
        / "ha-blocky-dashboard.js"
    ).read_text(encoding="utf-8")

    assert "this._seen = new Map();" in source
    assert "this._seen.get(seenKey)" in source and "this._seen.set(seenKey" in source
    # Memory only: the answers are never written to the browser's storage.
    assert "localStorage.setItem(seenKey" not in source
    assert "sessionStorage" not in source


def test_the_card_asks_again_after_a_stale_answer_with_bounded_retries() -> None:
    root = Path(__file__).resolve().parent.parent / "custom_components" / "ha_blocky"
    source = (root / "frontend" / "ha-blocky-dashboard.js").read_text(encoding="utf-8")
    data = (root / "frontend" / "ha-blocky-dashboard-data.js").read_text(
        encoding="utf-8"
    )

    assert "stale: meta.stale === true" in data
    assert "if (this._data.stale) this._retryLater();" in source
    assert "const STALE_RETRIES = 5;" in source and "STALE_RETRY_MS = 4000" in source
    # One timer at a time (setTimeout, not a loop), cleared on stop and on leaving.
    assert source.count("setTimeout(") == 1
    stop = source[source.index("  stop() {") :]
    assert "this._clearRetry();" in stop.split("}")[0]
    assert "if (!active) this._clearRetry();" in source
    assert "this._staleTries >= STALE_RETRIES" in source
