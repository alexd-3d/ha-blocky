"""Tests for read-only access to the query log database (on SQLite)."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, insert
from sqlalchemy.engine import URL

from custom_components.ha_blocky import db
from custom_components.ha_blocky.db import (
    LOG_TABLE,
    BlockyDbDriverError,
    BlockyDbError,
    BlockyDbSchemaError,
    BlockyDbSettingsError,
    DbSettings,
    QueryLogDatabase,
    TopItem,
    build_url,
    clean_text,
    privileges_allow_writes,
    validate_settings,
)

NOW = datetime(2026, 11, 10, 12, 0, 0)


def sqlite_url(path: Path) -> URL:
    return URL.create("sqlite", database=str(path))


def make_log(path: Path, rows: list[dict[str, Any]] | None = None) -> URL:
    """Create a query log database file and return its URL."""
    url = sqlite_url(path)
    engine = create_engine(url)
    LOG_TABLE.metadata.create_all(engine)
    if rows:
        add_rows(url, rows)
    engine.dispose()
    return url


def add_rows(url: URL, rows: list[dict[str, Any]]) -> None:
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(insert(LOG_TABLE), rows)
    engine.dispose()


def row(
    domain: str = "example.com",
    *,
    client: str = "192.0.2.10",
    response_type: str = "RESOLVED",
    age: timedelta = timedelta(minutes=1),
    duration_ms: int = 10,
) -> dict[str, Any]:
    return {
        "request_ts": NOW - age,
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


@pytest.fixture
def database(tmp_path: Path) -> QueryLogDatabase:
    url = make_log(
        tmp_path / "log.db",
        [
            row("example.com", client="192.0.2.10", duration_ms=10),
            row("example.com", client="192.0.2.11", duration_ms=30),
            row("ads.example", client="192.0.2.10", response_type="BLOCKED"),
            row("ads.example", client="192.0.2.10", response_type="BLOCKED"),
            row("rebind.example", client="192.0.2.12", response_type="REBIND"),
            row("cached.example", client="192.0.2.10", response_type="CACHED"),
            row("old.example", client="192.0.2.99", age=timedelta(days=2)),
        ],
    )
    log = QueryLogDatabase(url)
    yield log
    log.close()


# --- Settings ---------------------------------------------------------------


def test_validate_settings_accepts() -> None:
    settings = validate_settings(" core-mariadb ", 3306, "blocky", "ha_ro", "Secret123")

    assert settings == DbSettings("core-mariadb", 3306, "blocky", "ha_ro", "Secret123")


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("host", ["", "   ", "db host", "db;drop", "-db", "db/..", "a" * 300, None, 5]),
        ("port", [0, -1, 65536, "3306", 3306.5, True, None]),
        ("database", ["", "bl ocky", "blocky;", "blocky`", "a" * 65, None]),
        (
            "username",
            [
                "",
                "ro'--",
                " lead",
                "trail ",
                "semi;colon",
                "back`tick",
                "a" * 129,
                None,
            ],
        ),
        ("password", ["", "a" * 257, "line\nbreak", "nul\x00", None, 123]),
    ],
)
def test_validate_settings_rejects(field: str, values: list[Any]) -> None:
    good = {
        "host": "db.example",
        "port": 3306,
        "database": "blocky",
        "username": "ha_ro",
        "password": "Secret123",
    }
    for value in values:
        with pytest.raises(BlockyDbSettingsError) as excinfo:
            validate_settings(**{**good, field: value})
        assert str(excinfo.value) == field


@pytest.mark.parametrize(
    "username",
    ["ha_blocky_ro", "reader@host", "ha.ro", "read only", "a" * 128, "u$-1"],
)
def test_validate_settings_accepts_user_names_the_mariadb_app_allows(
    username: str,
) -> None:
    settings = validate_settings("db.example", 3306, "blocky", username, "Secret123")

    assert settings.username == username


def test_build_url_needs_a_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    with pytest.raises(BlockyDbDriverError):
        build_url(DbSettings("db.example", 3306, "blocky", "ha_ro", "Secret123"))


def test_build_url_quotes_every_component(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: object() if name == "pymysql" else None,
    )
    password = "p@ss:w/rd?#&="

    url = build_url(DbSettings("db.example", 3307, "blocky", "ha_ro", password))

    assert url.drivername == "mysql+pymysql"
    assert (url.host, url.port, url.database) == ("db.example", 3307, "blocky")
    assert url.password == password
    assert password not in url.render_as_string(hide_password=True)
    assert password not in repr(url)


# --- Privileges -------------------------------------------------------------


@pytest.mark.parametrize(
    "grants",
    [
        ["GRANT USAGE ON *.* TO `ro`@`%` IDENTIFIED BY PASSWORD '*ABC'"],
        [
            "GRANT USAGE ON *.* TO `ro`@`%`",
            "GRANT SELECT ON `blocky`.* TO `ro`@`%`",
        ],
        ["grant select, show view on `blocky`.* to `ro`@`%`"],
        ["GRANT SELECT (`id`, `question_name`) ON `blocky`.`log_entries` TO `ro`@`%`"],
        [],
    ],
)
def test_read_only_grants(grants: list[str]) -> None:
    assert privileges_allow_writes(grants) is False


@pytest.mark.parametrize(
    "grants",
    [
        ["GRANT ALL PRIVILEGES ON *.* TO `service`@`%` WITH GRANT OPTION"],
        ["GRANT SELECT, INSERT ON `blocky`.* TO `u`@`%`"],
        ["GRANT SELECT ON `blocky`.* TO `u`@`%`", "GRANT DELETE ON `x`.* TO `u`@`%`"],
        ["GRANT SELECT (`a`), UPDATE (`b`) ON `blocky`.`log_entries` TO `u`@`%`"],
        ["GRANT SELECT ON `blocky`.* TO `u`@`%` WITH GRANT OPTION"],
        ["GRANT DROP, ALTER, CREATE, INDEX ON `blocky`.* TO `u`@`%`"],
        ["GRANT `admin_role` TO `u`@`%`"],
        ["something unexpected"],
    ],
)
def test_writable_grants(grants: list[str]) -> None:
    assert privileges_allow_writes(grants) is True


# --- Cleaning ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("example.com", "example.com"),
        ("bad\x00name\r\n\t.example", "badname.example"),
        ("\x1b[31mred\x1b[0m.example", "[31mred[0m.example"),
        ("<script>alert(1)</script>", "<script>alert(1)</script>"),
        ("a" * 400, "a" * 253),
        (None, ""),
        (42, ""),
        (b"bytes", ""),
    ],
)
def test_clean_text(value: Any, expected: str) -> None:
    assert clean_text(value) == expected


# --- Schema checks ----------------------------------------------------------


def test_connect_requires_the_log_table(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path / "empty.db")
    create_engine(url).dispose()
    log = QueryLogDatabase(url)

    with pytest.raises(BlockyDbSchemaError):
        log.connect()


def test_connect_requires_the_expected_columns(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path / "other.db")
    engine = create_engine(url)
    Table("log_entries", MetaData(), Column("id", Integer, primary_key=True)).create(
        engine
    )
    engine.dispose()
    log = QueryLogDatabase(url)

    with pytest.raises(BlockyDbSchemaError):
        log.connect()


def test_unreachable_database_is_reported(tmp_path: Path) -> None:
    log = QueryLogDatabase(sqlite_url(tmp_path / "missing-dir" / "log.db"))

    with pytest.raises(BlockyDbError):
        log.max_id()


# --- Queries ----------------------------------------------------------------


def test_max_id_and_counts(database: QueryLogDatabase) -> None:
    assert database.max_id() == 7

    counts = database.counts_since(0)
    assert (counts.max_id, counts.queries, counts.blocked) == (7, 7, 3)

    counts = database.counts_since(4)
    assert (counts.max_id, counts.queries, counts.blocked) == (7, 3, 1)

    counts = database.counts_since(7)
    assert (counts.max_id, counts.queries, counts.blocked) == (7, 0, 0)


def test_empty_table(tmp_path: Path) -> None:
    log = QueryLogDatabase(make_log(tmp_path / "log.db"))
    try:
        assert log.max_id() == 0
        summary = log.summary(NOW - timedelta(hours=24))
        assert (summary.queries, summary.blocked, summary.clients) == (0, 0, 0)
        assert summary.avg_duration_ms is None
        assert summary.latest_request is None
        assert log.top_domains(NOW - timedelta(hours=24)) == []
    finally:
        log.close()


def test_summary_covers_only_the_window(database: QueryLogDatabase) -> None:
    summary = database.summary(NOW - timedelta(hours=24))

    assert summary.queries == 6
    assert summary.blocked == 3
    assert summary.clients == 3
    assert summary.avg_duration_ms == pytest.approx(80 / 6)
    assert summary.latest_request == NOW - timedelta(minutes=1)


def test_top_lists(database: QueryLogDatabase) -> None:
    since = NOW - timedelta(hours=24)

    assert database.top_domains(since) == [
        TopItem("ads.example", 2),
        TopItem("example.com", 2),
        TopItem("cached.example", 1),
        TopItem("rebind.example", 1),
    ]
    assert database.top_blocked_domains(since) == [
        TopItem("ads.example", 2),
        TopItem("rebind.example", 1),
    ]
    assert database.top_clients(since) == [
        TopItem("192.0.2.10", 4),
        TopItem("192.0.2.11", 1),
        TopItem("192.0.2.12", 1),
    ]


def test_top_list_is_limited(tmp_path: Path) -> None:
    rows = [row(f"host{index:02d}.example") for index in range(25)]
    log = QueryLogDatabase(make_log(tmp_path / "log.db", rows))
    try:
        assert len(log.top_domains(NOW - timedelta(hours=24))) == db.MAX_TOP_ITEMS
    finally:
        log.close()


def test_hostile_names_are_data_not_code(tmp_path: Path) -> None:
    hostile = [
        "x'; DROP TABLE log_entries; --",
        '" OR 1=1 --',
        "<img src=x onerror=alert(1)>",
        "evil\x00\r\n.example",
        "a" * 1000,
        "",
    ]
    url = make_log(tmp_path / "log.db", [row(name) for name in hostile])
    log = QueryLogDatabase(url)
    try:
        names = {item.name for item in log.top_domains(NOW - timedelta(hours=24))}

        assert "x'; DROP TABLE log_entries; --" in names
        assert "<img src=x onerror=alert(1)>" in names
        assert "evil.example" in names
        assert "a" * 253 in names
        assert "" not in names
        assert all(len(name) <= 253 and name.isprintable() for name in names)
        # The table is still there and complete.
        assert log.max_id() == len(hostile)
    finally:
        log.close()


def test_failure_drops_the_connection_and_recovers(tmp_path: Path) -> None:
    path = tmp_path / "log.db"
    log = QueryLogDatabase(make_log(path, [row()]))
    try:
        assert log.max_id() == 1

        engine = create_engine(sqlite_url(path))
        with engine.begin() as connection:
            LOG_TABLE.drop(connection)
        engine.dispose()
        with pytest.raises(BlockyDbError):
            log.max_id()
        # Reconnecting re-validates the schema instead of trusting the past.
        with pytest.raises(BlockyDbSchemaError):
            log.max_id()

        make_log(path, [row(), row()])
        assert log.max_id() == 2
    finally:
        log.close()
