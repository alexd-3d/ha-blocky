"""Short group keys: the dashboard statements give the same numbers, bounded."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy.engine import URL

from custom_components.ha_blocky import db
from custom_components.ha_blocky.db import (
    CATEGORIES,
    MAX_DOMAIN_KEY,
    QueryLogDatabase,
)

from .test_db import NOW, make_log, row

SINCE = NOW - timedelta(days=1)
UNTIL = NOW + timedelta(hours=1)


def _database(tmp_path: Path, rows: list[dict[str, Any]]) -> QueryLogDatabase:
    return QueryLogDatabase(make_log(tmp_path / "log.db", rows))


def _with_reason(row_: dict[str, Any], reason: str) -> dict[str, Any]:
    return {**row_, "reason": reason}


def _mixed() -> list[dict[str, Any]]:
    return [
        row("a.example.com", client="192.0.2.10", response_type="RESOLVED"),
        row("a.example.com", client="192.0.2.10", response_type="CACHED"),
        row("a.example.com", client="192.0.2.10", response_type="CACHED"),
        row("a.example.com", client="192.0.2.11", response_type="BLOCKED"),
        row("a.example.com", client="192.0.2.11", response_type="REBIND"),
        row("a.example.com", client="192.0.2.11", response_type="CUSTOMDNS"),
        row("a.example.com", client="192.0.2.11", response_type="HOSTSFILE"),
        row("a.example.com", client="192.0.2.11", response_type="WHATEVER"),
        row("b.example.com", client="192.0.2.10", response_type="CONDITIONAL"),
        row("b.example.com", client="192.0.2.10", response_type="SPECIAL"),
        row("c.example.com", client="198.51.100.5", response_type="SYNTHESIZED"),
    ]


def test_the_category_fold_gives_the_numbers_of_the_old_sums(tmp_path: Path) -> None:
    database = _database(tmp_path, _mixed())

    domains = database.dashboard_top("domain", SINCE, UNTIL, 10)

    assert [(item["name"], item["count"]) for item in domains] == [
        ("a.example.com", 8),
        ("b.example.com", 2),
        ("c.example.com", 1),
    ]
    assert domains[0]["categories"] == {
        "resolved": 1,
        "cached": 2,
        "local": 2,
        "blocked": 2,
        "other": 1,
    }
    assert domains[1]["categories"]["local"] == 2
    assert domains[2]["categories"]["local"] == 1
    for item in domains:
        assert set(item["categories"]) == set(CATEGORIES)
        assert sum(item["categories"].values()) == item["count"]
        assert item["last_seen"].endswith("+00:00")
        assert "reason" not in item
    database.close()


def test_clients_are_ranked_and_counted_per_category(tmp_path: Path) -> None:
    database = _database(tmp_path, _mixed())

    clients = database.dashboard_top("client", SINCE, UNTIL, 10)

    assert [(item["name"], item["count"]) for item in clients] == [
        ("192.0.2.10", 5),
        ("192.0.2.11", 5),
        ("198.51.100.5", 1),
    ]  # a tie is broken by the key
    assert clients[0]["categories"] == {
        "resolved": 1,
        "cached": 2,
        "local": 2,
        "blocked": 0,
        "other": 0,
    }
    assert clients[1]["categories"] == {
        "resolved": 0,
        "cached": 0,
        "local": 2,
        "blocked": 2,
        "other": 1,
    }
    database.close()


def test_the_rank_is_limited_and_in_order(tmp_path: Path) -> None:
    rows = [row(f"d{i}.example.com") for i in range(1, 6)]
    for i in range(1, 6):
        rows += [row(f"d{i}.example.com") for _ in range(i)]
    database = _database(tmp_path, rows)

    items = database.dashboard_top("domain", SINCE, UNTIL, 3)

    assert [(item["name"], item["count"]) for item in items] == [
        ("d5.example.com", 6),
        ("d4.example.com", 5),
        ("d3.example.com", 4),
    ]
    assert database.dashboard_top("domain", SINCE, UNTIL, 1)[0]["count"] == 6
    database.close()


def test_blocked_only_ranks_and_counts_only_blocked_queries(tmp_path: Path) -> None:
    database = _database(tmp_path, _mixed())

    items = database.dashboard_top("domain", SINCE, UNTIL, 10, blocked_only=True)

    assert [(item["name"], item["count"]) for item in items] == [("a.example.com", 2)]
    assert items[0]["categories"] == {
        "resolved": 0,
        "cached": 0,
        "local": 0,
        "blocked": 2,
        "other": 0,
    }
    database.close()


def test_the_most_frequent_reason_is_kept_per_name(tmp_path: Path) -> None:
    ads = "BLOCKED (ads)"
    rows = [
        _with_reason(row("ads.example.com", response_type="BLOCKED"), ads),
        _with_reason(row("ads.example.com", response_type="BLOCKED"), ads),
        _with_reason(row("ads.example.com", response_type="REBIND"), "BLOCKED (other)"),
        row("quiet.example.com", response_type="BLOCKED"),
    ]
    database = _database(tmp_path, rows)

    items = database.dashboard_top(
        "domain", SINCE, UNTIL, 10, blocked_only=True, with_reason=True
    )

    by_name = {item["name"]: item for item in items}
    assert by_name["ads.example.com"]["reason"] == ads
    assert by_name["ads.example.com"]["count"] == 3
    assert by_name["quiet.example.com"]["reason"] == ""
    database.close()


def test_a_long_name_is_cut_and_names_that_share_the_cut_merge(
    tmp_path: Path,
) -> None:
    prefix = "x" * MAX_DOMAIN_KEY
    rows = [
        row(f"{prefix}-one.example.com"),
        row(f"{prefix}-two.example.com", response_type="BLOCKED"),
        row(f"{prefix}-two.example.com", response_type="CACHED"),
        row("short.example.com"),
    ]
    database = _database(tmp_path, rows)

    items = database.dashboard_top("domain", SINCE, UNTIL, 10)

    assert [(item["name"], item["count"]) for item in items] == [
        (prefix, 3),
        ("short.example.com", 1),
    ]
    assert len(items[0]["name"]) == MAX_DOMAIN_KEY
    assert items[0]["categories"] == {
        "resolved": 1,
        "cached": 1,
        "local": 0,
        "blocked": 1,
        "other": 0,
    }
    unique, _average = database.dashboard_domains(SINCE, UNTIL)
    assert unique == 2  # the cut key and the short name
    database.close()


def test_unique_domains_count_cut_names_once(tmp_path: Path) -> None:
    prefix = "y" * MAX_DOMAIN_KEY
    rows = [
        row(f"{prefix}-a.example.com", duration_ms=10),
        row(f"{prefix}-b.example.com", duration_ms=30),
        row("one.example.com", duration_ms=20),
        row("one.example.com", duration_ms=20),
    ]
    database = _database(tmp_path, rows)

    unique, average = database.dashboard_domains(SINCE, UNTIL)

    assert unique == 2
    assert average == 20
    database.close()


def test_the_categories_statement_only_gets_the_ranked_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [row(f"d{i}.example.com") for i in range(1, 8)]
    rows += [row("d1.example.com"), row("d2.example.com"), row("d1.example.com")]
    database = _database(tmp_path, rows)
    seen: list[tuple[str, list[Any], Any]] = []
    original = QueryLogDatabase._run

    def recording(self: QueryLogDatabase, statement: Any, **kwargs: Any) -> Any:
        values = list(statement.compile().params.values())
        seen.append((kwargs["label"], values, statement._limit_clause))
        return original(self, statement, **kwargs)

    monkeypatch.setattr(QueryLogDatabase, "_run", recording)

    items = database.dashboard_top("domain", SINCE, UNTIL, 2)

    assert [item["name"] for item in items] == ["d1.example.com", "d2.example.com"]
    labels = [label for label, _values, _limit in seen]
    assert labels == ["dashboard_top.ranked", "dashboard_top.categories"]
    categories_values = seen[1][1]
    names = [
        v
        for value in categories_values
        for v in (value if isinstance(value, list) else [value])
    ]
    assert "d1.example.com" in names and "d2.example.com" in names
    assert not any(isinstance(n, str) and n.startswith("d3") for n in names)
    assert seen[1][2].value == 2 * db.MAX_TYPES_PER_ITEM
    database.close()


def test_a_cut_guard_still_makes_the_categories_add_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        row("a.example.com", response_type="RESOLVED"),
        row("a.example.com", response_type="CACHED"),
        row("a.example.com", response_type="BLOCKED"),
    ]
    database = _database(tmp_path, rows)
    monkeypatch.setattr(db, "MAX_TYPES_PER_ITEM", 1)

    (item,) = database.dashboard_top("domain", SINCE, UNTIL, 1)

    assert item["count"] == 3
    assert sum(item["categories"].values()) == 3
    database.close()


def test_an_empty_range_gives_no_items_and_no_second_statement(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    database = _database(tmp_path, [row("a.example.com", client="")])
    caplog.set_level(logging.DEBUG, logger="custom_components.ha_blocky.db")

    assert database.dashboard_top("domain", UNTIL, UNTIL + timedelta(days=1), 5) == []
    assert database.dashboard_top("client", SINCE, UNTIL, 5) == []  # "" is no client
    assert database.dashboard_top("domain", SINCE, UNTIL, 5, blocked_only=True) == []
    labels = [
        r.getMessage().split(":")[0]
        for r in caplog.records
        if r.getMessage().startswith("query ")
    ]
    assert labels == ["query dashboard_top.ranked"] * 3
    database.close()


def test_the_short_key_is_left_on_mysql_and_substr_elsewhere() -> None:
    column = db.LOG_TABLE.c.question_name
    mysql_db = QueryLogDatabase(URL.create("mysql+pymysql", host="db.example.com"))
    other_db = QueryLogDatabase(URL.create("sqlite", database=":memory:"))

    on_mysql = str(
        mysql_db._short(column, 127).compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    on_other = str(
        other_db._short(column, 127).compile(compile_kwargs={"literal_binds": True})
    )

    assert on_mysql == "left(log_entries.question_name, 127)"
    assert on_other == "substr(log_entries.question_name, ?, 127)".replace("?", "1")
