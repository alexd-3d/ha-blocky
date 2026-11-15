"""Timing lines of the database and the dashboard, and the table diagnostics."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator
from sqlalchemy import text
from sqlalchemy.engine import URL

from custom_components.ha_blocky import db
from custom_components.ha_blocky.dashboard import collect
from custom_components.ha_blocky.db import QueryLogDatabase
from custom_components.ha_blocky.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .test_dashboard import KIND, _command, _seed, _setup, utc  # noqa: F401
from .test_db import make_log, row
from .test_stats import DB_OPTIONS

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

DOMAIN_TEXT = "secret-domain.example"
CLIENT_TEXT = "192.0.2.99"
NOW = datetime(2026, 11, 10, 12, 0, 0)


def _ours(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The messages of this integration (SQLAlchemy's own echo is not ours)."""
    return [
        r.getMessage() for r in caplog.records if r.name.startswith("custom_components")
    ]


@pytest.fixture
def database(tmp_path: Path) -> QueryLogDatabase:
    url = make_log(
        tmp_path / "log.db",
        [row(DOMAIN_TEXT, client=CLIENT_TEXT)],
    )
    database = QueryLogDatabase(url)
    yield database
    database.close()


def test_every_statement_logs_a_label_milliseconds_and_rows(
    database: QueryLogDatabase, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="custom_components.ha_blocky.db")

    database.max_id()
    database.client_domains(CLIENT_TEXT, NOW - timedelta(days=1), 10)
    database.dashboard_top("domain", NOW - timedelta(days=1), NOW, 5)

    lines = [
        r.getMessage() for r in caplog.records if r.getMessage().startswith("query")
    ]
    assert lines[0].startswith("query max_id: ") and lines[0].endswith("1 rows")
    assert "ms" in lines[0]
    labels = {line.split(":")[0] for line in lines}
    assert {
        "query max_id",
        "query client_domains",
        "query dashboard_top.groups",
    } <= labels
    dumped = " | ".join(_ours(caplog))
    for private in (DOMAIN_TEXT, CLIENT_TEXT, "SELECT", "log_entries", "WHERE"):
        assert private not in dumped


def test_a_label_is_required() -> None:
    with pytest.raises(TypeError):
        QueryLogDatabase(URL.create("sqlite", database=":memory:"))._run(
            text("select 1")
        )


def test_dashboard_collect_logs_the_round(
    database: QueryLogDatabase, caplog: pytest.LogCaptureFixture
) -> None:
    from custom_components.ha_blocky.dashboard import build_window

    caplog.set_level(logging.DEBUG, logger="custom_components.ha_blocky.dashboard")

    collect(database, build_window("24h", NOW), "24h", 5)

    messages = _ours(caplog)
    assert any(
        m.startswith("dashboard round for 24h: ") and m.endswith(" ms")
        for m in messages
    )
    assert all(DOMAIN_TEXT not in m for m in messages)


@pytest.mark.usefixtures("enable_custom_integrations", "utc")
async def test_dashboard_logs_cache_hit_and_miss(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _seed(log_url)
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    caplog.set_level(logging.DEBUG, logger="custom_components.ha_blocky.dashboard")

    await _command(client, 1, type=KIND, period="7d", rows=5)
    await _command(client, 2, type=KIND, period="7d", rows=5)

    messages = _ours(caplog)
    assert "dashboard cache miss for 7d" in messages
    assert "dashboard cache hit for 7d" in messages
    # The table facts are logged once, not on every round.
    assert messages.count("query log table facts: None") == 1


def test_table_info_is_none_outside_mysql(database: QueryLogDatabase) -> None:
    assert database.table_info() is None


def test_table_info_reads_indexes_and_estimate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    database = QueryLogDatabase(URL.create("sqlite", database=":memory:"))
    monkeypatch.setattr(QueryLogDatabase, "dialect", property(lambda self: "mysql"))
    seen: list[tuple[str, str]] = []

    def fake_run(self: Any, statement: Any, *, label: str, one: bool = True) -> Any:
        seen.append((label, str(statement)))
        assert one is False
        if label == "table_info.indexes":
            return [
                ("PRIMARY", "id", 0),
                ("ix_ts", "request_ts", 1),
                ("ix_ts", "client_ip\x00", 1),
            ]
        return [(12345,)]

    monkeypatch.setattr(QueryLogDatabase, "_run", fake_run)

    info = database.table_info()

    assert info == {
        "indexes": [
            {"name": "PRIMARY", "columns": ["id"], "unique": True},
            {"name": "ix_ts", "columns": ["request_ts", "client_ip"], "unique": False},
        ],
        "estimated_rows": 12345,
    }
    # Parameterised: the table name is a bound value, not part of the text.
    assert all(":table" in sql and "log_entries" not in sql for _, sql in seen)
    assert all("LIMIT" in sql for _, sql in seen)


async def test_diagnostics_shape_on_sqlite_and_database_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = await _setup(hass, aioclient_mock, DB_OPTIONS)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["query_log"]["table"] is None

    def broken(self: QueryLogDatabase) -> Any:
        raise db.BlockyDbError("OperationalError")

    monkeypatch.setattr(QueryLogDatabase, "table_info", broken)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["query_log"]["table"] is None
    json.dumps(diagnostics, default=str)
