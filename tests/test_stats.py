"""Tests for the query log statistics, their sensors, options and diagnostics."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_URL, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from custom_components.ha_blocky import config_flow, db
from custom_components.ha_blocky.const import (
    CONF_DB_HOST,
    CONF_DB_NAME,
    CONF_DB_PASSWORD,
    CONF_DB_PORT,
    CONF_DB_USERNAME,
    DOMAIN,
    STATS_INTERVAL,
    TOPS_INTERVAL,
)
from custom_components.ha_blocky.diagnostics import async_get_config_entry_diagnostics
from custom_components.ha_blocky.sensor import BlockyTopSensor

from .test_db import add_rows, sqlite_url

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

BASE_URL = "http://blocky.example:4000"
STATUS_URL = f"{BASE_URL}/api/blocking/status"
ENABLED = {"enabled": True, "disabledGroups": [], "autoEnableInSec": 0}

DB_PASSWORD = "Sup3rSecretValue"
DB_OPTIONS = {
    CONF_DB_HOST: "db.example",
    CONF_DB_PORT: 3306,
    CONF_DB_NAME: "blocky",
    CONF_DB_USERNAME: "ha_blocky_ro",
    CONF_DB_PASSWORD: DB_PASSWORD,
}

STATS_KEYS = (
    "queries_total",
    "blocked_total",
    "resolved_total",
    "cached_total",
    "local_total",
    "other_total",
    "queries_24h",
    "blocked_24h",
    "blocked_ratio_24h",
    "clients_24h",
    "avg_response_time_24h",
    "top_domains",
    "top_blocked_domains",
    "top_clients",
)


def log_row(
    domain: str = "example.com",
    *,
    client: str = "192.0.2.10",
    response_type: str = "RESOLVED",
    age: timedelta = timedelta(minutes=1),
    duration_ms: int = 10,
) -> dict[str, Any]:
    """Build a log row relative to the current (possibly frozen) time."""
    return {
        "request_ts": (dt_util.utcnow() - age).replace(tzinfo=None),
        "client_ip": client,
        "client_name": client,
        "duration_ms": duration_ms,
        "reason": "",
        "response_type": response_type,
        "question_type": "A",
        "question_name": domain,
        "effective_tldp": domain,
        "answer": "",
        "response_code": "NOERROR",
        "hostname": "blocky",
    }


async def _setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    aioclient_mock.get(STATUS_URL, json=ENABLED)
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_URL: BASE_URL}, options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _entity_id(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> str:
    platform = "binary_sensor" if key == "database" else "sensor"
    entity_id = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert entity_id is not None, key
    return entity_id


def _state(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> str:
    return hass.states.get(_entity_id(hass, entry, key)).state


def _items(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> list[dict]:
    return hass.states.get(_entity_id(hass, entry, key)).attributes["items"]


async def open_options_step(
    hass: HomeAssistant, entry: MockConfigEntry, step: str
) -> dict[str, Any]:
    """Open the options menu and pick one of its steps."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == [
        "database",
        "intervals",
        "lists",
        "list_urls",
    ]
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )


async def _poll(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, step: timedelta
) -> None:
    freezer.tick(step)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


# --- Entities ---------------------------------------------------------------


async def test_no_database_means_no_statistics_entities(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(hass, aioclient_mock)

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(entities) == 6
    assert entry.runtime_data.stats is None


async def test_statistics_entities_and_ids(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, log_url: URL
) -> None:
    entry = await _setup(hass, aioclient_mock, DB_OPTIONS)

    assert {key: _entity_id(hass, entry, key) for key in (*STATS_KEYS, "database")} == {
        "queries_total": "sensor.ha_blocky_queries",
        "blocked_total": "sensor.ha_blocky_blocked_queries",
        "resolved_total": "sensor.ha_blocky_resolved_queries",
        "cached_total": "sensor.ha_blocky_cached_queries",
        "local_total": "sensor.ha_blocky_locally_answered_queries",
        "other_total": "sensor.ha_blocky_other_queries",
        "queries_24h": "sensor.ha_blocky_queries_24_h",
        "blocked_24h": "sensor.ha_blocky_blocked_queries_24_h",
        "blocked_ratio_24h": "sensor.ha_blocky_blocked_share_24_h",
        "clients_24h": "sensor.ha_blocky_clients_24_h",
        "avg_response_time_24h": "sensor.ha_blocky_average_response_time_24_h",
        "top_domains": "sensor.ha_blocky_top_domains",
        "top_blocked_domains": "sensor.ha_blocky_top_blocked_domains",
        "top_clients": "sensor.ha_blocky_top_clients",
        "database": "binary_sensor.ha_blocky_query_log_database",
    }
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(entities) == 6 + 15
    assert _state(hass, entry, "database") == STATE_ON
    assert "items" in BlockyTopSensor._unrecorded_attributes


async def test_history_is_not_added_to_totals_on_first_run(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, log_url: URL
) -> None:
    add_rows(log_url, [log_row(), log_row(response_type="BLOCKED")])

    entry = await _setup(hass, aioclient_mock, DB_OPTIONS)

    assert _state(hass, entry, "queries_total") == "0"
    assert _state(hass, entry, "blocked_total") == "0"
    # The 24 hour summary does include what is already in the log.
    assert _state(hass, entry, "queries_24h") == "2"
    assert _state(hass, entry, "blocked_24h") == "1"
    assert _state(hass, entry, "blocked_ratio_24h") == "50.0"
    assert _state(hass, entry, "clients_24h") == "1"


async def test_new_rows_are_counted(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
) -> None:
    entry = await _setup(hass, aioclient_mock, DB_OPTIONS)

    add_rows(
        log_url,
        [
            log_row("example.com", client="192.0.2.10", duration_ms=10),
            log_row("example.com", client="192.0.2.11", duration_ms=30),
            log_row("ads.example", response_type="BLOCKED", duration_ms=2),
            log_row("rebind.example", response_type="REBIND", duration_ms=2),
        ],
    )
    await _poll(hass, freezer, STATS_INTERVAL)

    assert _state(hass, entry, "queries_total") == "4"
    assert _state(hass, entry, "blocked_total") == "2"
    assert _state(hass, entry, "queries_24h") == "4"
    assert _state(hass, entry, "clients_24h") == "2"
    assert _state(hass, entry, "avg_response_time_24h") == "11.0"

    add_rows(log_url, [log_row("more.example")])
    await _poll(hass, freezer, STATS_INTERVAL)

    assert _state(hass, entry, "queries_total") == "5"
    assert _state(hass, entry, "blocked_total") == "2"


async def test_new_rows_are_counted_by_category(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
) -> None:
    entry = await _setup(hass, aioclient_mock, DB_OPTIONS)
    categories = (
        "resolved_total",
        "cached_total",
        "local_total",
        "blocked_total",
        "other_total",
    )
    assert [_state(hass, entry, key) for key in categories] == ["0"] * 5

    add_rows(
        log_url,
        [
            log_row(response_type="RESOLVED"),
            log_row(response_type="RESOLVED"),
            log_row(response_type="CACHED"),
            log_row(response_type="CUSTOMDNS"),
            log_row(response_type="CONDITIONAL"),
            log_row(response_type="BLOCKED"),
            log_row(response_type="NOTFQDN"),
            log_row(response_type="<b>made up</b>"),
        ],
    )
    await _poll(hass, freezer, STATS_INTERVAL)

    counted = {key: int(_state(hass, entry, key)) for key in categories}
    assert counted == {
        "resolved_total": 2,
        "cached_total": 1,
        "local_total": 2,
        "blocked_total": 1,
        "other_total": 2,
    }
    assert sum(counted.values()) == int(_state(hass, entry, "queries_total")) == 8

    add_rows(log_url, [log_row(response_type="CACHED")])
    await _poll(hass, freezer, STATS_INTERVAL)

    assert _state(hass, entry, "cached_total") == "2"
    assert _state(hass, entry, "resolved_total") == "2"
    assert _state(hass, entry, "queries_total") == "9"


async def test_top_lists_refresh_on_their_own_interval(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
) -> None:
    add_rows(log_url, [log_row("first.example")])
    entry = await _setup(hass, aioclient_mock, DB_OPTIONS)
    assert _items(hass, entry, "top_domains") == [{"name": "first.example", "count": 1}]

    add_rows(
        log_url,
        [
            log_row("ads.example", response_type="BLOCKED"),
            log_row("ads.example", response_type="BLOCKED"),
        ],
    )
    await _poll(hass, freezer, STATS_INTERVAL)
    # Counters follow at once, top lists only every few minutes.
    assert _state(hass, entry, "blocked_total") == "2"
    assert _state(hass, entry, "top_domains") == "1"

    await _poll(hass, freezer, TOPS_INTERVAL)
    assert _items(hass, entry, "top_domains") == [
        {"name": "ads.example", "count": 2},
        {"name": "first.example", "count": 1},
    ]
    assert _items(hass, entry, "top_blocked_domains") == [
        {"name": "ads.example", "count": 2}
    ]
    assert _items(hass, entry, "top_clients") == [{"name": "192.0.2.10", "count": 3}]


async def test_hostile_domain_reaches_the_state_machine_as_plain_text(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, log_url: URL
) -> None:
    add_rows(
        log_url,
        [log_row("<script>alert(1)</script>\x00\r\n"), log_row("x" * 2000)],
    )

    entry = await _setup(hass, aioclient_mock, DB_OPTIONS)

    names = [item["name"] for item in _items(hass, entry, "top_domains")]
    assert "<script>alert(1)</script>" in names
    assert "x" * 253 in names
    assert all(name.isprintable() and len(name) <= 253 for name in names)


# --- Persistence ------------------------------------------------------------


async def test_totals_survive_a_restart_and_catch_up(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
) -> None:
    entry = await _setup(hass, aioclient_mock, DB_OPTIONS)
    add_rows(log_url, [log_row(), log_row(response_type="BLOCKED")])
    await _poll(hass, freezer, STATS_INTERVAL)
    assert _state(hass, entry, "queries_total") == "2"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    # Queries answered while Home Assistant was down.
    add_rows(log_url, [log_row(), log_row(), log_row(response_type="BLOCKED")])

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert _state(hass, entry, "queries_total") == "5"
    assert _state(hass, entry, "blocked_total") == "2"


async def test_emptied_table_does_not_reduce_totals(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
) -> None:
    entry = await _setup(hass, aioclient_mock, DB_OPTIONS)
    add_rows(log_url, [log_row(), log_row(), log_row()])
    await _poll(hass, freezer, STATS_INTERVAL)
    assert _state(hass, entry, "queries_total") == "3"

    engine = create_engine(log_url)
    db.LOG_TABLE.drop(engine)
    db.LOG_TABLE.create(engine)
    engine.dispose()
    add_rows(log_url, [log_row()])
    await _poll(hass, freezer, STATS_INTERVAL)

    # The cursor restarts; the single row of the new table is not double
    # counted and the total never goes down.
    assert _state(hass, entry, "queries_total") == "3"

    add_rows(log_url, [log_row()])
    await _poll(hass, freezer, STATS_INTERVAL)
    assert _state(hass, entry, "queries_total") == "4"


async def test_tampered_store_is_ignored(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    hass_storage: dict[str, Any],
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_URL: BASE_URL}, options=DB_OPTIONS
    )
    hass_storage[f"{DOMAIN}.{entry.entry_id}.stats"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}.stats",
        "data": {"last_id": "9; DROP", "queries_total": -5, "blocked_total": True},
    }
    aioclient_mock.get(STATUS_URL, json=ENABLED)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert _state(hass, entry, "queries_total") == "0"
    assert _state(hass, entry, "blocked_total") == "0"


async def test_removing_the_entry_deletes_saved_statistics(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    hass_storage: dict[str, Any],
) -> None:
    entry = await _setup(hass, aioclient_mock, DB_OPTIONS)
    key = f"{DOMAIN}.{entry.entry_id}.stats"
    await entry.runtime_data.stats.async_save()
    assert key in hass_storage

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert key not in hass_storage


# --- Failures ---------------------------------------------------------------


async def test_database_outage_does_not_affect_control(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = await _setup(hass, aioclient_mock, DB_OPTIONS)
    original = db.QueryLogDatabase.max_id

    def broken(self: db.QueryLogDatabase) -> int:
        raise db.BlockyDbError("OperationalError")

    monkeypatch.setattr(db.QueryLogDatabase, "max_id", broken)
    await _poll(hass, freezer, STATS_INTERVAL)

    assert _state(hass, entry, "database") == STATE_OFF
    assert _state(hass, entry, "queries_total") == STATE_UNAVAILABLE
    assert hass.states.get("switch.ha_blocky_blocking").state == STATE_ON
    assert hass.states.get("binary_sensor.ha_blocky_connection").state == STATE_ON

    monkeypatch.setattr(db.QueryLogDatabase, "max_id", original)
    await _poll(hass, freezer, STATS_INTERVAL)

    assert _state(hass, entry, "database") == STATE_ON
    assert _state(hass, entry, "queries_total") == "0"


async def test_entry_loads_when_database_is_down_at_startup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = sqlite_url(tmp_path / "no-such-dir" / "log.db")
    monkeypatch.setattr(db, "build_url", lambda settings: missing)

    entry = await _setup(hass, aioclient_mock, DB_OPTIONS)

    assert _state(hass, entry, "database") == STATE_OFF
    assert _state(hass, entry, "queries_total") == STATE_UNAVAILABLE
    assert hass.states.get("switch.ha_blocky_blocking").state == STATE_ON


async def test_entry_loads_without_a_database_driver(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def no_driver(settings: db.DbSettings) -> URL:
        raise db.BlockyDbDriverError("no MySQL driver installed")

    monkeypatch.setattr(db, "build_url", no_driver)

    entry = await _setup(hass, aioclient_mock, DB_OPTIONS)

    assert entry.runtime_data.stats is None
    assert "Query log database is not usable" in caplog.text
    assert DB_PASSWORD not in caplog.text


async def test_tampered_options_do_not_break_setup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, log_url: URL
) -> None:
    entry = await _setup(
        hass, aioclient_mock, {**DB_OPTIONS, CONF_DB_NAME: "blocky; DROP TABLE x"}
    )

    assert entry.runtime_data.stats is None


# --- Options flow -----------------------------------------------------------


async def test_options_flow_enables_the_query_log(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, log_url: URL
) -> None:
    entry = await _setup(hass, aioclient_mock)

    result = await open_options_step(hass, entry, "database")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "database"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**DB_OPTIONS, CONF_DB_HOST: "  db.example  "}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == DB_OPTIONS
    # The entry was reloaded with statistics.
    assert entry.runtime_data.stats is not None
    assert _state(hass, entry, "database") == STATE_ON


async def test_options_flow_empty_host_disables_the_query_log(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, log_url: URL
) -> None:
    entry = await _setup(hass, aioclient_mock, DB_OPTIONS)

    result = await open_options_step(hass, entry, "database")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DB_PORT: 3306}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {}
    assert entry.runtime_data.stats is None


async def test_options_flow_never_returns_the_stored_password(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, log_url: URL
) -> None:
    entry = await _setup(hass, aioclient_mock, DB_OPTIONS)

    result = await open_options_step(hass, entry, "database")

    suggested = {
        str(key): key.description.get("suggested_value")
        for key in result["data_schema"].schema
        if key.description
    }
    assert suggested[CONF_DB_HOST] == "db.example"
    assert CONF_DB_PASSWORD not in suggested
    assert DB_PASSWORD not in repr(result)


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({CONF_DB_HOST: "db host; rm"}, CONF_DB_HOST),
        ({CONF_DB_PORT: 70000.0}, CONF_DB_PORT),
        ({CONF_DB_NAME: "blocky`"}, CONF_DB_NAME),
        ({CONF_DB_USERNAME: "root'--"}, CONF_DB_USERNAME),
        ({CONF_DB_PASSWORD: "line\nbreak"}, CONF_DB_PASSWORD),
    ],
)
async def test_options_flow_rejects_bad_settings(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    change: dict[str, Any],
    field: str,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    result = await open_options_step(hass, entry, "database")

    schema_errors: InvalidData | None = None
    try:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**DB_OPTIONS, **change}
        )
    except InvalidData as err:
        # The form schema itself rejects values such as an out-of-range port.
        schema_errors = err

    if schema_errors is None:
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {field: "invalid_db_setting"}
    assert entry.options == {}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (db.BlockyDbDriverError("x"), "db_driver_missing"),
        (db.BlockyDbSchemaError("x"), "db_schema"),
        (db.BlockyDbNotReadOnlyError("x"), "db_not_read_only"),
        (db.BlockyDbError("OperationalError"), "db_cannot_connect"),
    ],
)
async def test_options_flow_reports_database_problems(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected: str,
) -> None:
    def fail(settings: db.DbSettings) -> None:
        raise error

    monkeypatch.setattr(config_flow, "_test_database", fail)
    entry = await _setup(hass, aioclient_mock)
    result = await open_options_step(hass, entry, "database")

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], DB_OPTIONS
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}
    assert entry.options == {}
    assert DB_PASSWORD not in repr(result["data_schema"].schema)


# --- Diagnostics ------------------------------------------------------------


async def test_diagnostics_redact_everything_private(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, log_url: URL
) -> None:
    add_rows(
        log_url,
        [log_row("private.example", client="192.0.2.77", response_type="BLOCKED")],
    )
    entry = await _setup(hass, aioclient_mock, DB_OPTIONS)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(diagnostics, default=str)

    for secret in (
        DB_PASSWORD,
        "db.example",
        "ha_blocky_ro",
        "blocky.example",
        "private.example",
        "192.0.2.77",
    ):
        assert secret not in dumped
    assert diagnostics["blocking"]["enabled"] is True
    assert diagnostics["query_log"]["queries_24h"] == 1
    assert diagnostics["query_log"]["blocked_24h"] == 1
    assert diagnostics["query_log"]["top_list_sizes"] == [1, 1, 1]
    assert diagnostics["query_log"]["dialect"] == "sqlite"


async def test_diagnostics_without_a_database(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(hass, aioclient_mock)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["query_log"] is None
    assert "blocky.example" not in json.dumps(diagnostics)
