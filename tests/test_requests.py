"""Tests for the requests for new domains: tracking, decisions, caps, events,
leaks, storage, entities, services and commands."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
import voluptuous as vol
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import CONF_URL
from homeassistant.core import Context, Event, HomeAssistant
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockUser,
    async_capture_events,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator
from sqlalchemy import create_engine, delete
from sqlalchemy.engine import URL

from custom_components.ha_blocky import requests as req
from custom_components.ha_blocky.const import (
    CONF_LIST_NETWORKS,
    CONF_LISTS,
    CONF_REPORT_EXISTING_DOMAINS,
    CONF_ZONES,
    DOMAIN,
    EVENT_LIST_CHANGED,
    EVENT_NEW_DOMAIN,
    EVENT_NEW_DOMAINS_SUMMARY,
    EVENT_UNEXPECTED_DOMAIN,
    EVENT_ZONE_LEAK,
    STATS_INTERVAL,
)
from custom_components.ha_blocky.db import LOG_TABLE, BlockyDbError, QueryLogDatabase
from custom_components.ha_blocky.diagnostics import async_get_config_entry_diagnostics
from custom_components.ha_blocky.lists import ListManager, read_definitions
from custom_components.ha_blocky.requests import (
    RequestError,
    RequestTracker,
    domain_is_covered,
    normalize_client,
    storage_key,
)
from custom_components.ha_blocky.zones import ZoneDefinition, read_zones

from .test_db import add_rows, make_log
from .test_lists import LOOPBACK
from .test_stats import DB_OPTIONS, _poll, log_row

pytestmark = pytest.mark.usefixtures(
    "enable_custom_integrations", "freezer", "hass_storage", "log_url"
)

BASE_URL = "http://blocky.example:4000"
STATUS_URL = f"{BASE_URL}/api/blocking/status"
ENABLED = {"enabled": True, "disabledGroups": [], "autoEnableInSec": 0}

LAB = "198.51.100.10"
LAB_B = "198.51.100.11"
LAB_C = "198.51.100.12"
LAB2 = "198.51.100.200"
KID = "203.0.113.10"
KID_B = "203.0.113.11"
OFFICE = "192.0.2.10"
OTHER = "203.0.113.200"

LISTS = {
    CONF_LISTS: {
        "allow_a": {"type": "allow", "exact_only": True},
        "allow_b": {"type": "allow", "exact_only": True},
        "allow_wild": {"type": "allow", "exact_only": False},
        "deny_a": {"type": "deny", "exact_only": False},
    },
    CONF_LIST_NETWORKS: LOOPBACK,
}
ZONES = {
    CONF_ZONES: {
        "lab": {
            "networks": ["198.51.100.0/25"],
            "mode": "learning",
            "lists": ["deny_a"],
        },
        "lab2": {"networks": ["198.51.100.128/25"], "mode": "learning", "lists": []},
        "kids": {
            "networks": ["203.0.113.0/25"],
            "mode": "allowlist_only",
            "lists": ["allow_a", "allow_b"],
        },
        "office": {"networks": ["192.0.2.0/24"], "mode": "filter", "lists": []},
    }
}
OPTIONS = {
    **DB_OPTIONS,
    **LISTS,
    **ZONES,
    CONF_REPORT_EXISTING_DOMAINS: True,
}


def row(
    domain: str = "new.example.com",
    client: str = LAB,
    response_type: str = "RESOLVED",
    age: timedelta = timedelta(minutes=1),
) -> dict[str, Any]:
    return log_row(domain, client=client, response_type=response_type, age=age)


def blocked(domain: str = "new.example.com", client: str = KID) -> dict[str, Any]:
    return row(domain, client, "BLOCKED")


# --- A tracker without the rest of the integration ----------------------------------


@dataclass
class Harness:
    entry: MockConfigEntry
    lists: ListManager
    tracker: RequestTracker
    database: QueryLogDatabase
    url: URL

    def add(self, *rows: dict[str, Any]) -> None:
        add_rows(self.url, list(rows))


@pytest.fixture
def make(
    hass: HomeAssistant, log_url: URL, request: pytest.FixtureRequest
) -> Callable[..., Any]:
    """Return a coroutine function that builds a tracker on the test log."""
    databases: list[QueryLogDatabase] = []

    async def _make(
        *,
        options: dict[str, Any] | None = None,
        zones: dict[str, ZoneDefinition] | None = None,
        report_existing: bool = True,
        entry: MockConfigEntry | None = None,
        ready: bool = True,
        client_names: Callable[[], Mapping[str, str]] | None = None,
    ) -> Harness:
        options = OPTIONS if options is None else options
        if entry is None:
            entry = MockConfigEntry(
                domain=DOMAIN, data={CONF_URL: BASE_URL}, options=options
            )
            entry.add_to_hass(hass)
        lists = ListManager(hass, entry)
        await lists.async_load()
        database = QueryLogDatabase(log_url)
        databases.append(database)
        if zones is None:
            zones = read_zones(options, read_definitions(options))
        tracker = RequestTracker(
            hass,
            entry,
            database,
            zones,
            lists,
            report_existing=report_existing,
            client_names=client_names,
        )
        await tracker.async_load()
        harness = Harness(entry, lists, tracker, database, log_url)
        if ready:
            # The first round only finds the end of the existing history.
            await harness_round(hass, harness)
        return harness

    request.addfinalizer(lambda: [database.close() for database in databases])
    return _make


async def harness_round(hass: HomeAssistant, harness: Harness) -> None:
    await harness.tracker.async_round()
    await hass.async_block_till_done()


def data_of(events: list[Event]) -> list[dict[str, Any]]:
    return [event.data for event in events]


def only_request(harness: Harness) -> dict[str, Any]:
    requests = harness.tracker.describe_requests()
    assert len(requests) == 1
    return requests[0]


# --- Pure helpers -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("192.0.2.10", "192.0.2.10"),
        (" 192.0.2.10 ", "192.0.2.10"),
        ("::ffff:192.0.2.10", "192.0.2.10"),
        ("2001:db8::1", "2001:db8::1"),
        ("not-an-ip", None),
        ("fe80::1%eth0", None),
        ("192.0.2.0/24", None),
        ("", None),
        (None, None),
        (5, None),
        ("1" * 100, None),
    ],
)
def test_normalize_client(value: Any, expected: str | None) -> None:
    assert normalize_client(value) == expected


@pytest.mark.parametrize(
    ("domain", "covered"),
    [
        ("ok.example.com", True),
        ("sub.ok.example.com", True),
        ("deep.sub.ok.example.com", True),
        ("wild.example.org", True),
        ("a.b.wild.example.org", True),
        ("wild.example.org.evil.example", False),
        ("example.org", False),
        ("badok.example.com", False),
        ("example.com", False),
        ("other.example.net", False),
    ],
)
def test_domain_is_covered_on_label_boundaries(domain: str, covered: bool) -> None:
    assert domain_is_covered(domain, {"ok.example.com", "*.example.org"}) is covered


def test_rows_after_is_ordered_and_bounded(tmp_path: Any) -> None:
    url = make_log(tmp_path / "w.db", [row(f"d{i}.example.com") for i in range(6)])
    database = QueryLogDatabase(url)
    try:
        rows = database.rows_after(2, 3)
        assert [r.id for r in rows] == [3, 4, 5]
        assert rows[0].domain == "d2.example.com"
        assert rows[0].client == LAB
        assert database.rows_after(6, 3) == []
    finally:
        database.close()


# --- Window, cursor, filtering ------------------------------------------------------


async def test_each_round_reads_a_bounded_window(
    hass: HomeAssistant, make: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(req, "REQUEST_WINDOW_ROWS", 3)
    harness = await make(ready=False)
    harness.add(*(row(f"d{i}.example.com") for i in range(7)))

    # The first round starts three rows before the end of the history.
    await harness_round(hass, harness)
    assert harness.tracker.counters.rows_read == 3
    assert harness.tracker._cursor == 7

    harness.add(*(row(f"e{i}.example.com") for i in range(8)))
    for reads, cursor in ((6, 10), (9, 13), (11, 15), (11, 15)):
        await harness_round(hass, harness)
        assert harness.tracker.counters.rows_read == reads
        assert harness.tracker._cursor == cursor


async def test_an_emptied_table_restarts_the_cursor(
    hass: HomeAssistant, make: Callable[..., Any], log_url: URL
) -> None:
    harness = await make()
    harness.add(row("a.example.com"), row("b.example.com"))
    await harness_round(hass, harness)
    assert harness.tracker._cursor == 2
    engine = create_engine(log_url)
    with engine.begin() as connection:
        connection.execute(delete(LOG_TABLE))
    engine.dispose()

    await harness_round(hass, harness)
    assert harness.tracker._cursor == 0
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    harness.add(row("c.example.com"))
    await harness_round(hass, harness)

    assert [event["domain"] for event in data_of(events)] == ["c.example.com"]


async def test_only_learning_and_allowlist_zones_are_watched(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    harness.add(
        row("a.example.com", OFFICE),
        row("b.example.com", OTHER, "BLOCKED"),
        row("c.example.com", "198.51.100.150"),
        row("d.example.com", KID, "BLOCKED"),
    )

    await harness_round(hass, harness)

    assert harness.tracker.counters.skipped_other_zone == 2
    assert {event["domain"] for event in data_of(events)} == {
        "c.example.com",
        "d.example.com",
    }


async def test_invalid_names_and_clients_are_counted_never_stored(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    bad_names = [
        "bad name.example.com",
        "localhost",
        "a" * 300 + ".example.com",
        "*.example.com",
        "evil.example.com\x07",
        "192.0.2.1",
        "x'; DROP TABLE log_entries; --.example.com",
    ]
    harness.add(
        *(row(name) for name in bad_names),
        row("fine.example.com", "not-an-ip"),
        row("fine.example.com", "fe80::1%eth0"),
        row("fine.example.com", "198.51.100.5/24"),
        row("good.example.com"),
    )

    await harness_round(hass, harness)

    counters = harness.tracker.counters
    assert counters.invalid_domains == len(bad_names)
    assert counters.invalid_clients == 3
    assert [event["domain"] for event in data_of(events)] == ["good.example.com"]
    stored = json.dumps(harness.tracker._stored())
    for needle in ("not-an-ip", "bad name", "DROP", "evil", "fe80"):
        assert needle not in stored


async def test_trailing_dot_and_case_are_normalised(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    harness.add(row("New.Example.COM."), row("new.example.com"))

    await harness_round(hass, harness)

    assert [event["domain"] for event in data_of(events)] == ["new.example.com"]


# --- Learning zones -----------------------------------------------------------------


async def test_learning_new_pair_fires_once_and_creates_a_request(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    harness.add(row("new.example.com"), row("new.example.com", response_type="BLOCKED"))

    await harness_round(hass, harness)

    request = only_request(harness)
    assert data_of(events) == [
        {
            "config_entry_id": harness.entry.entry_id,
            "zone": "lab",
            "client": LAB,
            "client_name": None,
            "domain": "new.example.com",
            "request_id": request["id"],
            "actions": ["block", "dismiss"],
        }
    ]
    assert request["kind"] == "learning"
    assert len(request["id"]) >= 22
    # Another client asking for the same domain is a new pair.
    harness.add(row("new.example.com", LAB_B))
    await harness_round(hass, harness)
    assert len(events) == 2
    assert harness.tracker.pending_count == 2


async def test_block_adds_the_domain_to_the_first_deny_list(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    harness.add(row("ads.example.com"))
    await harness_round(hass, harness)
    changed = async_capture_events(hass, EVENT_LIST_CHANGED)

    harness.tracker.async_resolve(only_request(harness)["id"], "block")
    await hass.async_block_till_done()

    assert harness.lists.entries("deny_a") == ["ads.example.com"]
    assert data_of(changed) == [
        {
            "config_entry_id": harness.entry.entry_id,
            "action": "add",
            "list": "deny_a",
            "domain": "ads.example.com",
        }
    ]
    assert harness.tracker.pending_count == 0
    # The pair is known now.
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    harness.add(row("ads.example.com"))
    await harness_round(hass, harness)
    assert not events


async def test_dismiss_closes_the_request_and_knows_the_pair(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    harness.add(row("meh.example.com"))
    await harness_round(hass, harness)

    harness.tracker.async_resolve(only_request(harness)["id"], "reject")
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    harness.add(row("meh.example.com"))
    await harness_round(hass, harness)

    assert harness.lists.entries("deny_a") == []
    assert harness.tracker.pending_count == 0
    assert not events


async def test_block_without_a_deny_list_is_an_error(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    harness.add(row("x.example.com", LAB2))
    await harness_round(hass, harness)

    with pytest.raises(RequestError) as err:
        harness.tracker.async_resolve(only_request(harness)["id"], "block")

    assert err.value.code == "no_deny_list"
    assert harness.tracker.pending_count == 1


async def test_request_kinds_limit_the_actions(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    harness.add(row("a.example.com"), blocked("b.example.com"))
    await harness_round(hass, harness)
    by_kind = {r["kind"]: r["id"] for r in harness.tracker.describe_requests()}

    with pytest.raises(RequestError) as err:
        harness.tracker.async_resolve(by_kind["learning"], "approve")
    assert err.value.code == "request_not_approvable"
    with pytest.raises(RequestError) as err:
        harness.tracker.async_resolve(by_kind["approval"], "block")
    assert err.value.code == "request_not_blockable"
    with pytest.raises(RequestError) as err:
        harness.tracker.async_resolve(by_kind["approval"], "delete")
    assert err.value.code == "request_not_found"
    assert harness.tracker.pending_count == 2


# --- Baseline -----------------------------------------------------------------------


async def test_a_new_learning_client_starts_with_its_recent_history_as_known(
    hass: HomeAssistant, make: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(req, "REQUEST_WINDOW_ROWS", 2)
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    harness = await make(ready=False, report_existing=False)
    # Five names over the last days, more than one window; one too old; one
    # invalid; another client's name.
    harness.add(
        *(row(f"d{i}.example.com", age=timedelta(days=i + 1)) for i in range(5)),
        row("ancient.example.com", age=timedelta(days=8)),
        row("bad name", age=timedelta(days=1)),
        row("other.example.com", LAB_B, age=timedelta(days=1)),
        row("last.example.com"),
        blocked("kid-old.example.com"),
    )

    await harness_round(hass, harness)

    # Nothing of the learning clients is reported; the allowlist zone is not
    # part of the baseline and still raises a request for a blocked pair.
    assert [e["domain"] for e in data_of(events)] == ["kid-old.example.com"]
    known = set(harness.tracker._clients[LAB].known)
    assert known >= {f"d{i}.example.com" for i in range(5)}
    assert "ancient.example.com" not in known
    assert harness.tracker._clients[LAB].baselined
    events.clear()

    harness.add(row("d0.example.com"), row("fresh.example.com"))
    await harness_round(hass, harness)
    assert [e["domain"] for e in data_of(events)] == ["fresh.example.com"]


async def test_a_zone_added_later_does_not_report_everyday_domains(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make(report_existing=False)
    harness.add(row("everyday.example.com", age=timedelta(days=3)))
    # A busy log: the client is first tracked well after its first query.
    harness.add(row("everyday.example.com", LAB_B))
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)

    await harness_round(hass, harness)
    harness.add(row("everyday.example.com"), row("new.example.com"))
    await harness_round(hass, harness)

    assert [e["domain"] for e in data_of(events)] == ["new.example.com"]


async def test_report_option_means_no_baseline_at_all(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    harness = await make(ready=False, report_existing=True)
    harness.add(row("old.example.com", age=timedelta(days=2)))

    await harness_round(hass, harness)

    assert [e["domain"] for e in data_of(events)] == ["old.example.com"]
    assert harness.tracker.pending_count == 1
    assert harness.tracker._clients[LAB].baselined


async def test_at_most_ten_baselines_per_round_and_waiting_rows_stay_silent(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make(report_existing=False)
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    clients = [f"198.51.100.{20 + i}" for i in range(12)]
    harness.add(*(row("a.example.com", client) for client in clients))

    await harness_round(hass, harness)

    waiting = [c for c in clients if not harness.tracker._clients[c].baselined]
    assert len(waiting) == 2
    assert not events
    harness.add(*(row("b.example.com", client) for client in waiting))
    await harness_round(hass, harness)

    assert not events
    assert all(harness.tracker._clients[c].baselined for c in clients)
    assert harness.tracker.pending_count == 0


async def test_a_failing_baseline_is_retried_and_reports_nothing_meanwhile(
    hass: HomeAssistant, make: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = await make(report_existing=False)
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    real = harness.database.client_domains

    def broken(*_args: Any) -> Any:
        raise BlockyDbError("OperationalError")

    monkeypatch.setattr(harness.database, "client_domains", broken)
    harness.add(row("a.example.com", age=timedelta(days=2)))
    await harness_round(hass, harness)

    assert harness.tracker.counters.failures == 1
    assert not harness.tracker._clients[LAB].baselined
    harness.add(row("b.example.com"))
    await harness_round(hass, harness)
    assert not events
    assert harness.tracker.counters.failures == 2

    monkeypatch.setattr(harness.database, "client_domains", real)
    await harness_round(hass, harness)

    assert harness.tracker._clients[LAB].baselined
    assert {"a.example.com", "b.example.com"} <= set(
        harness.tracker._clients[LAB].known
    )
    assert not events


async def test_baseline_state_survives_a_restart(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make(report_existing=False)
    harness.add(row("a.example.com"))
    await harness_round(hass, harness)
    await harness.tracker.async_close()

    again = await make(entry=harness.entry, ready=False, report_existing=False)

    assert again.tracker._clients[LAB].baselined


async def test_settings_set_the_baseline_option(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, settings_ws: Any
) -> None:
    entry = await _setup(hass, aioclient_mock, OPTIONS)
    assert entry.runtime_data.requests is not None

    response = await settings_ws(**{CONF_REPORT_EXISTING_DOMAINS: True})

    assert response["success"]
    assert entry.options[CONF_REPORT_EXISTING_DOMAINS] is True
    assert entry.options["db_host"] == "db.example"
    assert entry.runtime_data.requests._report_existing is True

    await settings_ws(**{CONF_REPORT_EXISTING_DOMAINS: False})
    assert entry.options[CONF_REPORT_EXISTING_DOMAINS] is False


async def test_options_survive_other_settings(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, settings_ws: Any
) -> None:
    entry = await _setup(
        hass, aioclient_mock, {**OPTIONS, CONF_REPORT_EXISTING_DOMAINS: True}
    )

    response = await settings_ws(status_interval=30, stats_interval=60)

    assert response["success"]
    assert entry.options[CONF_REPORT_EXISTING_DOMAINS] is True


# --- Allowlist-only zones -----------------------------------------------------------


async def test_learning_phase_blocked_pair_becomes_an_approval_request(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    harness.add(
        blocked("wanted.example.com"),
        row("fine.example.com", KID, "CONDITIONAL"),
        row("local.example.com", KID, "CUSTOMDNS"),
    )

    await harness_round(hass, harness)

    request = only_request(harness)
    assert request["kind"] == "approval"
    assert request["actions"] == ["approve", "reject"]
    assert data_of(events) == [
        {
            "config_entry_id": harness.entry.entry_id,
            "zone": "kids",
            "client": KID,
            "client_name": None,
            "domain": "wanted.example.com",
            "request_id": request["id"],
            "actions": ["approve", "reject"],
        }
    ]
    assert harness.tracker.describe_clients() == [
        {"client": KID, "client_name": None, "zone": "kids", "phase": "learning"}
    ]
    # Asking again while the request is pending changes nothing.
    harness.add(blocked("wanted.example.com"))
    await harness_round(hass, harness)
    assert len(events) == 1
    assert harness.tracker.pending_count == 1


async def test_approve_uses_the_first_allow_list_or_the_named_one(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    harness.add(blocked("one.example.com"), blocked("two.example.com"))
    await harness_round(hass, harness)
    ids = {r["domain"]: r["id"] for r in harness.tracker.describe_requests()}
    changed = async_capture_events(hass, EVENT_LIST_CHANGED)

    harness.tracker.async_resolve(ids["one.example.com"], "approve")
    harness.tracker.async_resolve(ids["two.example.com"], "approve", "allow_b")
    await hass.async_block_till_done()

    assert harness.lists.entries("allow_a") == ["one.example.com"]
    assert harness.lists.entries("allow_b") == ["two.example.com"]
    assert [(e["list"], e["domain"]) for e in data_of(changed)] == [
        ("allow_a", "one.example.com"),
        ("allow_b", "two.example.com"),
    ]
    assert harness.tracker.pending_count == 0


@pytest.mark.parametrize("name", ["allow_wild", "deny_a", "nope", "ALLOW_A", ""])
async def test_named_list_must_be_an_allow_list_of_the_zone(
    hass: HomeAssistant, make: Callable[..., Any], name: str
) -> None:
    harness = await make()
    harness.add(blocked("one.example.com"))
    await harness_round(hass, harness)

    with pytest.raises(RequestError) as err:
        harness.tracker.async_resolve(only_request(harness)["id"], "approve", name)

    assert err.value.code == "list_not_in_zone"
    assert harness.tracker.pending_count == 1
    assert harness.lists.entries("allow_wild") == []
    assert harness.lists.entries("deny_a") == []


async def test_reject_remembers_the_pair_for_good(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    harness.add(blocked("no.example.com"))
    await harness_round(hass, harness)
    harness.tracker.async_resolve(only_request(harness)["id"], "reject")
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)

    harness.add(blocked("no.example.com"), blocked("no.example.com"))
    await harness_round(hass, harness)

    assert not events
    assert harness.tracker.pending_count == 0
    for entries in (harness.lists.entries("allow_a"), harness.lists.entries("allow_b")):
        assert entries == []
    # Another client is another pair.
    harness.add(blocked("no.example.com", KID_B))
    await harness_round(hass, harness)
    assert len(events) == 1


async def test_locked_clients_raise_no_request_only_one_event_per_pair(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    harness.tracker.async_set_client_phase(KID, "locked")
    unexpected = async_capture_events(hass, EVENT_UNEXPECTED_DOMAIN)
    new = async_capture_events(hass, EVENT_NEW_DOMAIN)
    harness.add(blocked("odd.example.com"), blocked("odd.example.com"))

    await harness_round(hass, harness)
    harness.add(blocked("odd.example.com"))
    await harness_round(hass, harness)

    assert harness.tracker.pending_count == 0
    assert not new
    assert data_of(unexpected) == [
        {
            "config_entry_id": harness.entry.entry_id,
            "zone": "kids",
            "client": KID,
            "client_name": None,
            "domain": "odd.example.com",
            "request_id": None,
            "actions": [],
        }
    ]
    # Another client of the zone is still being learned.
    harness.add(blocked("odd.example.com", KID_B))
    await harness_round(hass, harness)
    assert harness.tracker.pending_count == 1


async def test_phase_changes_only_through_the_service_call(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    harness.tracker.async_set_client_phase(KID, "locked")
    harness.add(blocked("a.example.com"), row("b.example.com", KID))
    await harness_round(hass, harness)
    assert harness.tracker.describe_clients()[0]["phase"] == "locked"

    harness.tracker.async_set_client_phase(" 203.0.113.10 ", "learning")
    assert harness.tracker.describe_clients()[0]["phase"] == "learning"


@pytest.mark.parametrize(
    ("client", "code"),
    [
        ("nonsense", "invalid_client"),
        (LAB, "client_not_in_allowlist_zone"),
        (OFFICE, "client_not_in_allowlist_zone"),
        (OTHER, "client_not_in_allowlist_zone"),
        ("8.8.8.8", "client_not_in_allowlist_zone"),
    ],
)
async def test_set_client_phase_refuses_other_clients(
    hass: HomeAssistant, make: Callable[..., Any], client: str, code: str
) -> None:
    harness = await make()

    with pytest.raises(RequestError) as err:
        harness.tracker.async_set_client_phase(client, "locked")

    assert err.value.code == code
    assert harness.tracker.describe_clients() == []


# --- Ids, single use, expiry --------------------------------------------------------


async def test_ids_are_exact_and_single_use(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    harness.add(blocked("one.example.com"), blocked("two.example.com"))
    await harness_round(hass, harness)
    first, second = harness.tracker.describe_requests()
    assert first["id"] != second["id"]

    for wrong in (
        first["id"][:10],
        first["id"] + "x",
        first["id"].upper(),
        "",
        5,
        None,
    ):
        with pytest.raises(RequestError) as err:
            harness.tracker.async_resolve(wrong, "approve")
        assert err.value.code == "request_not_found"

    harness.tracker.async_resolve(first["id"], "approve")
    with pytest.raises(RequestError) as err:
        harness.tracker.async_resolve(first["id"], "approve")
    assert err.value.code == "request_not_found"
    assert harness.lists.entries("allow_a") == ["one.example.com"]
    assert harness.tracker.pending_count == 1


async def test_expired_learning_request_marks_the_pair_known(
    hass: HomeAssistant, make: Callable[..., Any], freezer: FrozenDateTimeFactory
) -> None:
    harness = await make()
    harness.add(row("slow.example.com"))
    await harness_round(hass, harness)
    request_id = only_request(harness)["id"]

    freezer.tick(timedelta(hours=23, minutes=59))
    await harness_round(hass, harness)
    assert harness.tracker.pending_count == 1
    freezer.tick(timedelta(minutes=2))
    await harness_round(hass, harness)

    assert harness.tracker.pending_count == 0
    with pytest.raises(RequestError):
        harness.tracker.async_resolve(request_id, "reject")
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    harness.add(row("slow.example.com"))
    await harness_round(hass, harness)
    assert not events


async def test_expired_approval_request_is_raised_again(
    hass: HomeAssistant, make: Callable[..., Any], freezer: FrozenDateTimeFactory
) -> None:
    harness = await make()
    harness.add(blocked("slow.example.com"))
    await harness_round(hass, harness)
    old_id = only_request(harness)["id"]

    freezer.tick(timedelta(hours=25))
    await harness_round(hass, harness)
    assert harness.tracker.pending_count == 0
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    harness.add(blocked("slow.example.com"))
    await harness_round(hass, harness)

    assert len(events) == 1
    assert only_request(harness)["id"] != old_id


async def test_an_expired_request_cannot_be_used_before_the_next_round(
    hass: HomeAssistant, make: Callable[..., Any], freezer: FrozenDateTimeFactory
) -> None:
    harness = await make()
    harness.add(blocked("slow.example.com"))
    await harness_round(hass, harness)
    request_id = only_request(harness)["id"]

    freezer.tick(timedelta(hours=24, seconds=1))
    with pytest.raises(RequestError) as err:
        harness.tracker.async_resolve(request_id, "approve")

    assert err.value.code == "request_not_found"
    assert harness.lists.entries("allow_a") == []
    assert harness.tracker.pending_count == 0


async def test_a_request_is_dropped_when_its_zone_changed(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    harness.add(blocked("one.example.com"))
    await harness_round(hass, harness)
    request_id = only_request(harness)["id"]
    zones = harness.tracker._zones
    assert isinstance(zones, dict)
    zones["kids"] = ZoneDefinition(
        "kids", zones["kids"].networks, "learning", zones["kids"].lists
    )

    with pytest.raises(RequestError) as err:
        harness.tracker.async_resolve(request_id, "approve")

    assert err.value.code == "zone_changed"
    assert harness.tracker.pending_count == 0
    assert harness.lists.entries("allow_a") == []


# --- Caps ---------------------------------------------------------------------------


async def test_pending_requests_are_capped(
    hass: HomeAssistant, make: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(req, "MAX_PENDING_REQUESTS", 3)
    harness = await make()
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    harness.add(*(row(f"d{i}.example.com") for i in range(5)))

    await harness_round(hass, harness)

    assert harness.tracker.pending_count == 3
    assert harness.tracker.counters.pending_cap_hits == 2
    assert len(events) == 3
    # Room again: a capped pair is not lost, it is raised when asked again.
    harness.tracker.async_resolve(
        harness.tracker.describe_requests()[0]["id"], "reject"
    )
    harness.add(row("d4.example.com"))
    await harness_round(hass, harness)
    assert harness.tracker.pending_count == 3


async def test_known_pairs_are_capped_and_least_recently_seen_go_first(
    hass: HomeAssistant,
    make: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
    freezer: FrozenDateTimeFactory,
) -> None:
    monkeypatch.setattr(req, "MAX_KNOWN_PAIRS_PER_CLIENT", 3)
    harness = await make()
    harness.add(*(row(f"d{i}.example.com") for i in range(5)))
    await harness_round(hass, harness)
    for request in harness.tracker.describe_requests():
        harness.tracker.async_resolve(request["id"], "reject")
    state = harness.tracker._clients[LAB]
    assert list(state.known) == ["d2.example.com", "d3.example.com", "d4.example.com"]

    freezer.tick(timedelta(minutes=11))  # out of the event flood window
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    harness.add(row("d2.example.com"), row("d5.example.com"))
    await harness_round(hass, harness)

    # Seeing d2 again made it the most recent one.
    assert list(state.known) == ["d3.example.com", "d4.example.com", "d2.example.com"]
    assert [e["domain"] for e in data_of(events)] == ["d5.example.com"]

    # Knowing d5 as well pushes out d3, the least recently seen.
    harness.tracker.async_resolve(only_request(harness)["id"], "reject")
    assert list(state.known) == ["d4.example.com", "d2.example.com", "d5.example.com"]


async def test_rejected_pairs_are_capped(
    hass: HomeAssistant, make: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(req, "MAX_REJECTED_PAIRS_PER_CLIENT", 2)
    harness = await make()
    harness.add(*(blocked(f"d{i}.example.com") for i in range(3)))
    await harness_round(hass, harness)
    for request in harness.tracker.describe_requests():
        harness.tracker.async_resolve(request["id"], "reject")
    assert list(harness.tracker._clients[KID].rejected) == [
        "d1.example.com",
        "d2.example.com",
    ]

    harness.add(blocked("d0.example.com"), blocked("d1.example.com"))
    await harness_round(hass, harness)

    assert [r["domain"] for r in harness.tracker.describe_requests()] == [
        "d0.example.com"
    ]


async def test_clients_are_capped_and_idle_ones_make_room(
    hass: HomeAssistant,
    make: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
    freezer: FrozenDateTimeFactory,
) -> None:
    monkeypatch.setattr(req, "MAX_REQUEST_CLIENTS", 2)
    harness = await make(ready=False, report_existing=False)
    harness.add(row("a.example.com", LAB), row("a.example.com", LAB_B))
    await harness_round(hass, harness)
    assert set(harness.tracker._clients) == {LAB, LAB_B}

    freezer.tick(timedelta(minutes=1))
    harness.add(row("b.example.com", LAB_B), row("b.example.com", LAB_C))
    await harness_round(hass, harness)

    assert len(harness.tracker._clients) == 2
    assert LAB_C in harness.tracker._clients
    assert LAB not in harness.tracker._clients
    assert harness.tracker.counters.clients_refused == 0


async def test_clients_with_pending_requests_are_never_evicted(
    hass: HomeAssistant, make: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(req, "MAX_REQUEST_CLIENTS", 2)
    harness = await make()
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    harness.add(row("a.example.com", LAB), row("a.example.com", LAB_B))
    await harness_round(hass, harness)

    harness.add(row("a.example.com", LAB_C))
    await harness_round(hass, harness)

    assert len(events) == 2
    assert set(harness.tracker._clients) == {LAB, LAB_B}
    assert harness.tracker.counters.clients_refused == 1
    assert harness.tracker.pending_count == 2


# --- Event flood limit --------------------------------------------------------------


async def test_events_are_limited_per_client_and_summarised_once(
    hass: HomeAssistant, make: Callable[..., Any], freezer: FrozenDateTimeFactory
) -> None:
    harness = await make()
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    summaries = async_capture_events(hass, EVENT_NEW_DOMAINS_SUMMARY)
    harness.add(*(row(f"d{i}.example.com") for i in range(8)))
    harness.add(row("other.example.com", LAB_B))

    await harness_round(hass, harness)

    # Five events for the flooding client, the other client is unaffected,
    # and every request exists anyway.
    assert len([e for e in data_of(events) if e["client"] == LAB]) == 5
    assert len([e for e in data_of(events) if e["client"] == LAB_B]) == 1
    assert harness.tracker.pending_count == 9
    assert not summaries

    freezer.tick(timedelta(minutes=9))
    await harness_round(hass, harness)
    assert not summaries
    freezer.tick(timedelta(minutes=2))
    await harness_round(hass, harness)
    await harness_round(hass, harness)

    assert data_of(summaries) == [
        {
            "config_entry_id": harness.entry.entry_id,
            "zone": "lab",
            "client": LAB,
            "client_name": None,
            "suppressed": 3,
        }
    ]
    # The window is over: events flow again.
    harness.add(row("later.example.com"))
    await harness_round(hass, harness)
    assert data_of(events)[-1]["domain"] == "later.example.com"


async def test_the_limit_counts_all_three_per_domain_event_types(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    harness.tracker.async_set_client_phase(KID, "locked")
    new = async_capture_events(hass, EVENT_NEW_DOMAIN)
    unexpected = async_capture_events(hass, EVENT_UNEXPECTED_DOMAIN)
    leaks = async_capture_events(hass, EVENT_ZONE_LEAK)
    harness.add(
        *(blocked(f"u{i}.example.com") for i in range(3)),
        *(row(f"l{i}.example.com", KID) for i in range(4)),
    )

    await harness_round(hass, harness)

    assert len(unexpected) == 3
    assert len(leaks) == 2
    assert not new
    assert harness.tracker.counters.events_suppressed == 2
    # All four leaks still count for the sensor.
    assert harness.tracker.leak_count() == 4


# --- Leaks --------------------------------------------------------------------------


async def _with_allowed(
    hass: HomeAssistant, make: Callable[..., Any], *domains: str
) -> Harness:
    harness = await make()
    for domain in domains:
        harness.lists.async_add("allow_a", domain, "allow")
    return harness


async def test_a_resolved_domain_outside_the_allow_lists_is_a_leak(
    hass: HomeAssistant, make: Callable[..., Any], freezer: FrozenDateTimeFactory
) -> None:
    harness = await _with_allowed(hass, make, "ok.example.com")
    harness.lists.async_add("allow_b", "also.example.net", "allow")
    leaks = async_capture_events(hass, EVENT_ZONE_LEAK)
    new = async_capture_events(hass, EVENT_NEW_DOMAIN)
    harness.add(
        row("ok.example.com", KID),
        row("sub.ok.example.com", KID),
        row("also.example.net", KID, "CACHED"),
        row("badok.example.com", KID),
        row("leak.example.com", KID, "CACHED"),
        row("leak2.example.com", KID, "CUSTOMDNS"),
        row("blocked.example.com", KID, "BLOCKED"),
    )

    await harness_round(hass, harness)

    assert [e["domain"] for e in data_of(leaks)] == [
        "badok.example.com",
        "leak.example.com",
    ]
    assert data_of(leaks)[0] == {
        "config_entry_id": harness.entry.entry_id,
        "zone": "kids",
        "client": KID,
        "client_name": None,
        "domain": "badok.example.com",
        "request_id": None,
        "actions": [],
    }
    assert harness.tracker.leak_count() == 2
    # A leak is no request; the blocked row is one.
    assert [e["domain"] for e in data_of(new)] == ["blocked.example.com"]

    # Once per pair until it clears.
    harness.add(row("leak.example.com", KID))
    await harness_round(hass, harness)
    assert len(leaks) == 2
    freezer.tick(timedelta(minutes=30))
    harness.add(row("leak.example.com", KID))
    await harness_round(hass, harness)
    assert len(leaks) == 2
    freezer.tick(timedelta(minutes=61))
    assert harness.tracker.leak_count() == 0
    harness.add(row("leak.example.com", KID))
    await harness_round(hass, harness)
    assert len(leaks) == 3
    assert harness.tracker.leak_count() == 1


async def test_old_rows_are_no_leak(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make(ready=False)
    leaks = async_capture_events(hass, EVENT_ZONE_LEAK)
    harness.add(row("old.example.com", KID, age=timedelta(hours=3)))

    await harness_round(hass, harness)

    assert not leaks
    assert harness.tracker.leak_count() == 0


async def test_leak_detection_is_off_when_a_zone_list_is_not_known(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    zones = {
        "kids": ZoneDefinition(
            "kids",
            (ipaddress.ip_network("203.0.113.0/25"),),
            "allowlist_only",
            ("allow_a", "ghost"),
        )
    }
    harness = await make(zones=zones)
    leaks = async_capture_events(hass, EVENT_ZONE_LEAK)
    harness.add(row("leak.example.com", KID))

    await harness_round(hass, harness)

    assert not leaks
    assert harness.tracker.leak_count() == 0


async def test_leak_detection_covers_every_phase(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    harness.tracker.async_set_client_phase(KID, "locked")
    leaks = async_capture_events(hass, EVENT_ZONE_LEAK)
    harness.add(row("leak.example.com", KID))
    await harness_round(hass, harness)
    harness.tracker.async_set_client_phase(KID_B, "learning")
    harness.add(row("leak.example.com", KID_B))
    await harness_round(hass, harness)

    assert [e["client"] for e in data_of(leaks)] == [KID, KID_B]


# --- Failures -----------------------------------------------------------------------


async def test_a_failing_round_is_counted_and_logged(
    hass: HomeAssistant,
    make: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = await make()

    def broken(*_args: Any) -> Any:
        raise BlockyDbError("OperationalError")

    monkeypatch.setattr(harness.database, "rows_after", broken)
    await harness_round(hass, harness)
    assert harness.tracker.counters.failures == 1

    def surprising(*_args: Any) -> Any:
        raise RuntimeError("secret.example.com")

    monkeypatch.setattr(harness.database, "rows_after", surprising)
    await harness_round(hass, harness)

    assert harness.tracker.counters.failures == 2
    assert "RuntimeError" in caplog.text
    assert "secret.example.com" not in caplog.text


async def test_a_poison_row_does_not_stall_the_cursor(
    hass: HomeAssistant, make: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = await make()
    harness.add(row("a.example.com"), row("b.example.com"))

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError

    monkeypatch.setattr(harness.tracker, "_learning_row", boom)
    await harness_round(hass, harness)

    assert harness.tracker.counters.failures == 1
    assert harness.tracker._cursor == 2


async def test_statistics_survive_a_failing_tracker(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    monkeypatch: pytest.MonkeyPatch,
    log_url: URL,
) -> None:
    entry = await _setup(hass, aioclient_mock, OPTIONS)
    stats = entry.runtime_data.stats

    def broken(*_args: Any) -> Any:
        raise BlockyDbError("OperationalError")

    monkeypatch.setattr(stats.database, "rows_after", broken)
    add_rows(log_url, [row("a.example.com")])
    await _poll(hass, freezer, STATS_INTERVAL)

    assert stats.last_update_success
    assert stats.data.queries_total == 1
    assert entry.runtime_data.requests.counters.failures == 1


# --- Storage ------------------------------------------------------------------------


async def test_state_survives_a_restart(
    hass: HomeAssistant,
    make: Callable[..., Any],
    hass_storage: dict[str, Any],
) -> None:
    harness = await make()
    harness.add(
        row("a.example.com"), blocked("b.example.com"), row("leak.example.com", KID)
    )
    await harness_round(hass, harness)
    harness.tracker.async_set_client_phase(KID_B, "locked")
    harness.tracker.async_resolve(
        harness.tracker.describe_requests()[0]["id"], "reject"
    )
    await harness.tracker.async_close()
    assert storage_key(harness.entry.entry_id) in hass_storage

    again = await make(entry=harness.entry, ready=False)

    assert again.tracker.describe_requests() == harness.tracker.describe_requests()
    assert again.tracker.describe_clients() == harness.tracker.describe_clients()
    assert again.tracker.diagnostics() == harness.tracker.diagnostics() | {
        "counters": again.tracker.diagnostics()["counters"],
        "baseline_last_duration_ms": None,
    }
    assert again.tracker._cursor == harness.tracker._cursor
    # Known pairs came back: no new request, no new event.
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    again.add(row("a.example.com"))
    await harness_round(hass, again)
    assert not events


async def test_tampered_store_is_validated(
    hass: HomeAssistant, make: Callable[..., Any], hass_storage: dict[str, Any]
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_URL: BASE_URL}, options=OPTIONS)
    entry.add_to_hass(hass)
    key = storage_key(entry.entry_id)
    good_id = "A" * 22
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {
            "cursor": "9; DROP",
            "clients": {
                "not-an-ip": {"zone": "lab", "mode": "learning", "last_seen": 1.0},
                LAB: {
                    "zone": "lab",
                    "mode": "learning",
                    "phase": "locked",
                    "last_seen": 1.0,
                    "known": ["good.example.com", "bad name", 5, None],
                    "rejected": "x",
                    "leaks": ["x"],
                },
                LAB_B: {"zone": ["lab"], "mode": "learning", "last_seen": 1.0},
                LAB_C: {"zone": "ghost", "mode": "learning", "last_seen": 1.0},
                KID: {"zone": "kids", "mode": "learning", "last_seen": 1.0},
                KID_B: {"zone": "kids", "mode": "allowlist_only", "last_seen": -1},
                OFFICE: {"zone": "office", "mode": "filter", "last_seen": 1.0},
            },
            "requests": [
                "junk",
                {"id": "short", "client": LAB, "domain": "a.example.com"},
                {
                    "id": good_id,
                    "client": LAB,
                    "domain": "Req.Example.com.",
                    "kind": "learning",
                    "created": 5.0,
                },
                {
                    "id": "B" * 22,
                    "client": LAB,
                    "domain": "wrong-kind.example.com",
                    "kind": "approval",
                    "created": 5.0,
                },
                {
                    "id": "C" * 22,
                    "client": LAB,
                    "domain": "bad name",
                    "kind": "learning",
                    "created": 5.0,
                },
                {
                    "id": "D" * 22,
                    "client": "198.51.100.77",
                    "domain": "nobody.example.com",
                    "kind": "learning",
                    "created": 5.0,
                },
                {
                    "id": "E" * 22,
                    "client": LAB,
                    "domain": "nan.example.com",
                    "kind": "learning",
                    "created": float("nan"),
                },
            ],
        },
    }

    harness = await make(entry=entry, ready=False)

    assert harness.tracker._cursor is None
    assert [r["id"] for r in harness.tracker.describe_requests()] == [good_id]
    assert harness.tracker.describe_requests()[0]["domain"] == "req.example.com"
    assert list(harness.tracker._clients) == [LAB]
    state = harness.tracker._clients[LAB]
    assert list(state.known) == ["good.example.com"]
    assert state.phase == "learning"


async def test_stored_caps_are_enforced_on_load(
    hass: HomeAssistant,
    make: Callable[..., Any],
    hass_storage: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(req, "MAX_KNOWN_PAIRS_PER_CLIENT", 2)
    monkeypatch.setattr(req, "MAX_PENDING_REQUESTS", 1)
    monkeypatch.setattr(req, "MAX_REQUEST_CLIENTS", 1)
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_URL: BASE_URL}, options=OPTIONS)
    entry.add_to_hass(hass)
    key = storage_key(entry.entry_id)
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {
            "cursor": 4,
            "clients": {
                address: {
                    "zone": "lab",
                    "mode": "learning",
                    "last_seen": 1.0,
                    "known": [f"d{i}.example.com" for i in range(5)],
                }
                for address in (LAB, LAB_B)
            },
            "requests": [
                {
                    "id": letter * 22,
                    "client": LAB,
                    "domain": f"{letter}.example.com",
                    "kind": "learning",
                    "created": 5.0,
                }
                for letter in "AB"
            ],
        },
    }

    harness = await make(entry=entry, ready=False)

    assert harness.tracker._cursor == 4
    assert list(harness.tracker._clients) == [LAB]
    assert list(harness.tracker._clients[LAB].known) == [
        "d3.example.com",
        "d4.example.com",
    ]
    assert harness.tracker.pending_count == 1


# --- Entities, diagnostics ----------------------------------------------------------


async def _setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    assert await async_setup_component(hass, "http", {})
    aioclient_mock.get(STATUS_URL, json=ENABLED)
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_URL: BASE_URL}, options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


PENDING_SENSOR = "sensor.ha_blocky_pending_domain_requests"
LEAK_SENSOR = "binary_sensor.ha_blocky_zone_leak"


async def test_sensors_follow_requests_and_leaks_without_naming_them(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
) -> None:
    entry = await _setup(hass, aioclient_mock, OPTIONS)
    assert hass.states.get(PENDING_SENSOR).state == "0"
    assert hass.states.get(LEAK_SENSOR).state == "off"
    add_rows(
        log_url,
        [
            row("one.example.com"),
            blocked("two.example.com"),
            row("leak.example.com", KID),
        ],
    )

    await _poll(hass, freezer, STATS_INTERVAL)

    assert hass.states.get(PENDING_SENSOR).state == "2"
    leak = hass.states.get(LEAK_SENSOR)
    assert leak.state == "on"
    assert leak.attributes["device_class"] == "problem"
    assert leak.attributes["count"] == 1
    dumped = json.dumps(
        [dict(hass.states.get(e).attributes) for e in (PENDING_SENSOR, LEAK_SENSOR)]
    )
    for needle in ("leak.example.com", KID, "one.example.com"):
        assert needle not in dumped

    request_id = entry.runtime_data.requests.describe_requests()[0]["id"]
    await hass.services.async_call(
        DOMAIN, "reject_request", {"request_id": request_id}, blocking=True
    )
    assert hass.states.get(PENDING_SENSOR).state == "1"

    await _poll(hass, freezer, timedelta(minutes=61))
    assert hass.states.get(LEAK_SENSOR).state == "off"
    assert hass.states.get(LEAK_SENSOR).attributes["count"] == 0


async def test_no_database_means_no_request_entities(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(hass, aioclient_mock, LISTS)

    assert entry.runtime_data.requests is None
    assert hass.states.get(PENDING_SENSOR) is None
    assert hass.states.get(LEAK_SENSOR) is None


async def test_diagnostics_show_counts_only(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
) -> None:
    entry = await _setup(hass, aioclient_mock, OPTIONS)
    add_rows(
        log_url,
        [
            row("secret-one.example.com"),
            blocked("secret-two.example.com"),
            row("secret-leak.example.com", KID),
            row("bad name", LAB_B),
        ],
    )
    await _poll(hass, freezer, STATS_INTERVAL)
    entry.runtime_data.requests.async_set_client_phase(KID_B, "locked")

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(diagnostics, default=str)

    for needle in (LAB, KID, KID_B, "secret", "example.com/"):
        assert needle not in dumped, needle
    requests = diagnostics["query_log"]["requests"]
    assert requests["clients"] == 3
    assert requests["pending_requests"] == 2
    assert requests["leaks_last_hour"] == 1
    assert requests["counters"]["invalid_domains"] == 1
    assert requests["has_cursor"] is True
    assert all(
        isinstance(value, (int, float, bool, dict, type(None)))
        for value in requests.values()
    )


async def test_removing_the_entry_deletes_the_saved_requests(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    hass_storage: dict[str, Any],
) -> None:
    entry = await _setup(hass, aioclient_mock, OPTIONS)
    key = storage_key(entry.entry_id)
    await entry.runtime_data.requests.async_close()
    assert key in hass_storage

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert key not in hass_storage


async def test_state_is_saved_when_the_entry_unloads(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    entry = await _setup(hass, aioclient_mock, OPTIONS)
    add_rows(log_url, [blocked("kept.example.com")])
    await _poll(hass, freezer, STATS_INTERVAL)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.requests.describe_requests()[0]["domain"] == (
        "kept.example.com"
    )
    assert hass.states.get(PENDING_SENSOR).state == "1"


# --- Services -----------------------------------------------------------------------


async def _call(hass: HomeAssistant, service: str, **data: Any) -> Any:
    return await hass.services.async_call(
        DOMAIN,
        service,
        data,
        blocking=True,
        return_response=service == "get_requests",
    )


async def _with_requests(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
) -> tuple[MockConfigEntry, dict[str, str]]:
    entry = await _setup(hass, aioclient_mock, OPTIONS)
    add_rows(log_url, [row("learn.example.com"), blocked("kid.example.com")])
    await _poll(hass, freezer, STATS_INTERVAL)
    ids = {r["kind"]: r["id"] for r in entry.runtime_data.requests.describe_requests()}
    assert set(ids) == {"learning", "approval"}
    return entry, ids


async def test_services_resolve_requests(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
) -> None:
    entry, ids = await _with_requests(hass, aioclient_mock, log_url, freezer)
    changed = async_capture_events(hass, EVENT_LIST_CHANGED)
    context = Context(user_id=None)

    response = await _call(hass, "get_requests")
    assert {r["domain"] for r in response["requests"]} == {
        "learn.example.com",
        "kid.example.com",
    }
    assert response["clients"] == [
        {"client": KID, "client_name": None, "zone": "kids", "phase": "learning"}
    ]

    await hass.services.async_call(
        DOMAIN,
        "approve_request",
        {"request_id": ids["approval"], "list": "allow_b"},
        blocking=True,
        context=context,
    )
    await _call(hass, "block_request", request_id=ids["learning"])
    await hass.async_block_till_done()

    lists = entry.runtime_data.lists
    assert lists.entries("allow_b") == ["kid.example.com"]
    assert lists.entries("deny_a") == ["learn.example.com"]
    assert changed[0].context is context
    assert (await _call(hass, "get_requests"))["requests"] == []


async def test_reject_service_in_both_kinds_of_zone(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
) -> None:
    entry, ids = await _with_requests(hass, aioclient_mock, log_url, freezer)

    await _call(hass, "reject_request", request_id=ids["learning"])
    await _call(hass, "reject_request", request_id=ids["approval"])

    assert (await _call(hass, "get_requests"))["requests"] == []
    assert entry.runtime_data.lists.entries("deny_a") == []
    assert entry.runtime_data.lists.entries("allow_a") == []


@pytest.mark.parametrize(
    ("service", "kind", "extra", "key"),
    [
        ("approve_request", "learning", {}, "request_not_approvable"),
        ("block_request", "approval", {}, "request_not_blockable"),
        ("approve_request", "approval", {"list": "allow_wild"}, "list_not_in_zone"),
        ("approve_request", "approval", {"list": "deny_a"}, "list_not_in_zone"),
    ],
)
async def test_service_refusals_carry_a_translation_key(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
    service: str,
    kind: str,
    extra: dict[str, str],
    key: str,
) -> None:
    entry, ids = await _with_requests(hass, aioclient_mock, log_url, freezer)

    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, service, request_id=ids[kind], **extra)

    assert err.value.translation_key == key
    assert err.value.translation_domain == DOMAIN
    assert entry.runtime_data.requests.pending_count == 2


@pytest.mark.parametrize(
    "service", ["approve_request", "reject_request", "block_request"]
)
async def test_service_with_an_unknown_request_id(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
    service: str,
) -> None:
    await _with_requests(hass, aioclient_mock, log_url, freezer)

    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, service, request_id="does-not-exist")

    assert err.value.translation_key == "request_not_found"


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("approve_request", {}),
        ("approve_request", {"request_id": ""}),
        ("approve_request", {"request_id": "x" * 65}),
        ("reject_request", {"request_id": ["a"]}),
        ("block_request", {}),
        ("set_client_phase", {"client": KID}),
        ("set_client_phase", {"client": KID, "phase": "open"}),
        ("set_client_phase", {"phase": "locked"}),
        ("set_client_phase", {"client": "x" * 65, "phase": "locked"}),
        ("get_requests", {"extra": 1}),
    ],
)
async def test_service_schemas_reject_bad_input(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    service: str,
    data: dict[str, Any],
) -> None:
    await _setup(hass, aioclient_mock, OPTIONS)

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            service,
            data,
            blocking=True,
            return_response=service == "get_requests",
        )


async def test_set_client_phase_service(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(hass, aioclient_mock, OPTIONS)

    await _call(hass, "set_client_phase", client=KID, phase="locked")
    assert (await _call(hass, "get_requests"))["clients"] == [
        {"client": KID, "client_name": None, "zone": "kids", "phase": "locked"}
    ]
    await _call(hass, "set_client_phase", client=KID, phase="learning")
    assert entry.runtime_data.requests.describe_clients()[0]["phase"] == "learning"

    for client, key in (
        ("garbage", "invalid_client"),
        (LAB, "client_not_in_allowlist_zone"),
    ):
        with pytest.raises(ServiceValidationError) as err:
            await _call(hass, "set_client_phase", client=client, phase="locked")
        assert err.value.translation_key == key


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("approve_request", {"request_id": "abc"}),
        ("reject_request", {"request_id": "abc"}),
        ("block_request", {"request_id": "abc"}),
        ("get_requests", {}),
        ("set_client_phase", {"client": KID, "phase": "locked"}),
    ],
)
async def test_request_services_are_admin_only(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_read_only_user: MockUser,
    service: str,
    data: dict[str, Any],
) -> None:
    entry = await _setup(hass, aioclient_mock, OPTIONS)

    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            service,
            data,
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
            return_response=service == "get_requests",
        )
    assert entry.runtime_data.requests.describe_clients() == []


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("approve_request", {"request_id": "abc"}),
        ("get_requests", {}),
        ("set_client_phase", {"client": KID, "phase": "locked"}),
    ],
)
async def test_services_need_the_query_log(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    service: str,
    data: dict[str, Any],
) -> None:
    await _setup(hass, aioclient_mock, LISTS)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            service,
            data,
            blocking=True,
            return_response=service == "get_requests",
        )

    assert err.value.translation_key == "no_query_log"


async def test_services_need_a_known_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock, OPTIONS)

    with pytest.raises(ServiceValidationError):
        await _call(hass, "get_requests", config_entry_id="nope")


# --- WebSocket commands -------------------------------------------------------------


async def _command(ws: Any, message_id: int, /, **message: Any) -> dict[str, Any]:
    await ws.send_json({"id": message_id, **message})
    return await ws.receive_json()


async def test_commands_list_and_resolve_requests(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
    hass_ws_client: WebSocketGenerator,
) -> None:
    entry, ids = await _with_requests(hass, aioclient_mock, log_url, freezer)
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=f"{DOMAIN}/requests")

    assert response["success"]
    result = response["result"]
    assert result["entry_id"] == entry.entry_id
    assert {r["id"] for r in result["requests"]} == set(ids.values())
    assert result["clients"] == [
        {"client": KID, "client_name": None, "zone": "kids", "phase": "learning"}
    ]
    assert set(result["requests"][0]) == {
        "id",
        "zone",
        "client",
        "client_name",
        "domain",
        "kind",
        "actions",
        "created",
        "expires",
    }

    response = await _command(
        client,
        2,
        type=f"{DOMAIN}/resolve_request",
        request_id=ids["approval"],
        action="approve",
        list="allow_b",
    )
    assert response["success"]
    assert [r["id"] for r in response["result"]["requests"]] == [ids["learning"]]
    assert entry.runtime_data.lists.entries("allow_b") == ["kid.example.com"]

    response = await _command(
        client,
        3,
        type=f"{DOMAIN}/resolve_request",
        request_id=ids["learning"],
        action="block",
    )
    assert response["success"]
    assert entry.runtime_data.lists.entries("deny_a") == ["learn.example.com"]


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ({"request_id": "unknown", "action": "approve"}, "request_not_found"),
        ({"request_id": "unknown", "action": "block"}, "request_not_found"),
        ({"request_id": "x" * 65, "action": "approve"}, "invalid_format"),
        ({"request_id": "", "action": "approve"}, "invalid_format"),
        ({"request_id": "abc", "action": "delete"}, "invalid_format"),
        ({"request_id": "abc", "action": "approve", "list": 5}, "invalid_format"),
        ({"action": "approve"}, "invalid_format"),
        (
            {"request_id": "abc", "action": "approve", "entry_id": "nope"},
            "entry_not_found",
        ),
    ],
)
async def test_resolve_command_failures(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
    hass_ws_client: WebSocketGenerator,
    message: dict[str, Any],
    code: str,
) -> None:
    entry, _ids = await _with_requests(hass, aioclient_mock, log_url, freezer)
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=f"{DOMAIN}/resolve_request", **message)

    assert response["success"] is False
    assert response["error"]["code"] == code
    assert entry.runtime_data.requests.pending_count == 2


async def test_resolve_command_errors_name_no_log_data(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
    hass_ws_client: WebSocketGenerator,
) -> None:
    _entry, ids = await _with_requests(hass, aioclient_mock, log_url, freezer)
    client = await hass_ws_client(hass)

    response = await _command(
        client,
        1,
        type=f"{DOMAIN}/resolve_request",
        request_id=ids["learning"],
        action="approve",
    )

    assert response["error"]["code"] == "request_not_approvable"
    assert "example.com" not in response["error"]["message"]


COMMANDS = {
    "requests": {},
    "resolve_request": {"request_id": "abc", "action": "approve"},
}


@pytest.mark.parametrize("kind", ["requests", "resolve_request"])
async def test_request_commands_are_admin_only(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: MockUser,
    kind: str,
) -> None:
    await _setup(hass, aioclient_mock, OPTIONS)
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=f"{DOMAIN}/{kind}", **COMMANDS[kind])

    assert response["success"] is False
    assert response["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("kind", ["requests", "resolve_request"])
async def test_request_commands_need_the_query_log(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    kind: str,
) -> None:
    await _setup(hass, aioclient_mock, LISTS)
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=f"{DOMAIN}/{kind}", **COMMANDS[kind])

    assert response["success"] is False
    assert response["error"]["code"] == "no_query_log"


# --- Known domains ------------------------------------------------------------------


async def _learn(
    hass: HomeAssistant, harness: Harness, client: str, *domains: str
) -> None:
    """Make a learning client know the domains (each dismissed once)."""
    harness.add(*(row(domain, client) for domain in domains))
    await harness_round(hass, harness)
    for request in harness.tracker.describe_requests():
        if request["client"] == client:
            harness.tracker.async_resolve(request["id"], "reject")


async def test_known_domains_come_newest_first_with_zone_and_mode(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make(client_names=lambda: {LAB: "Lab PC"})
    await _learn(hass, harness, LAB, "a.example.com", "b.example.com", "c.example.com")

    known = harness.tracker.describe_known(LAB)

    assert known == {
        "client": LAB,
        "client_name": "Lab PC",
        "zone": "lab",
        "mode": "learning",
        "total": 3,
        "domains": ["c.example.com", "b.example.com", "a.example.com"],
    }
    # Another spelling of the address finds the same client.
    assert harness.tracker.describe_known(f"::ffff:{LAB}") == known
    assert harness.tracker.describe_tracked() == [
        {
            "client": LAB,
            "client_name": "Lab PC",
            "zone": "lab",
            "mode": "learning",
            "known": 3,
        }
    ]


async def test_known_domains_are_capped_and_validated(
    hass: HomeAssistant, make: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = await make()
    await _learn(hass, harness, LAB, "a.example.com", "b.example.com", "c.example.com")
    state = harness.tracker._clients[LAB]
    # The store is validated on load, but the answer checks each name again.
    state.known["<img src=x onerror=alert(1)>"] = None
    state.known["bad name.example.com"] = None
    monkeypatch.setattr(req, "MAX_KNOWN_DOMAINS_SHOWN", 3)

    known = harness.tracker.describe_known(LAB)

    assert known["domains"] == ["c.example.com", "b.example.com", "a.example.com"]
    assert known["total"] == 5
    monkeypatch.setattr(req, "MAX_KNOWN_DOMAINS_SHOWN", 2)
    assert harness.tracker.describe_known(LAB)["domains"] == [
        "c.example.com",
        "b.example.com",
    ]


@pytest.mark.parametrize(
    ("client", "code"),
    [
        ("not-an-ip", "invalid_client"),
        (None, "invalid_client"),
        ("192.0.2.0/24", "invalid_client"),
        (OTHER, "client_not_tracked"),
        ("198.51.100.99", "client_not_tracked"),
    ],
)
async def test_known_domains_of_an_untracked_client_is_refused(
    make: Callable[..., Any], client: Any, code: str
) -> None:
    harness = await make()

    with pytest.raises(RequestError) as err:
        harness.tracker.describe_known(client)

    assert err.value.code == code


async def test_allowlist_clients_list_their_known_domains_read_only(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    harness.add(blocked("kid.example.com"))
    await harness_round(hass, harness)
    harness.tracker.async_resolve(only_request(harness)["id"], "approve")

    known = harness.tracker.describe_known(KID)

    assert known["mode"] == "allowlist_only"
    assert known["domains"] == ["kid.example.com"]


async def test_block_known_adds_to_the_first_deny_list(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    await _learn(hass, harness, LAB, "a.example.com", "b.example.com")
    changed = async_capture_events(hass, EVENT_LIST_CHANGED)
    context = Context()

    name = harness.tracker.async_block_known(LAB, "A.Example.com.", context)
    await hass.async_block_till_done()

    assert name == "a.example.com"
    assert harness.lists.entries("deny_a") == ["a.example.com"]
    assert data_of(changed) == [
        {
            "config_entry_id": harness.entry.entry_id,
            "action": "add",
            "list": "deny_a",
            "domain": "a.example.com",
        }
    ]
    assert changed[0].context is context
    # The domain stays known (and counts as just used).
    assert harness.tracker.describe_known(LAB)["domains"] == [
        "a.example.com",
        "b.example.com",
    ]
    # Blocking it again adds nothing and fires nothing.
    harness.tracker.async_block_known(LAB, "a.example.com")
    await hass.async_block_till_done()
    assert harness.lists.entries("deny_a") == ["a.example.com"]
    assert len(changed) == 1


async def test_block_known_refuses_what_is_not_a_known_domain_of_a_learning_client(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    await _learn(hass, harness, LAB, "a.example.com")
    harness.add(blocked("kid.example.com"))
    await harness_round(hass, harness)
    harness.tracker.async_resolve(only_request(harness)["id"], "approve")

    def refused(client: Any, domain: Any) -> str:
        with pytest.raises(RequestError) as err:
            harness.tracker.async_block_known(client, domain)
        return err.value.code

    assert refused("nope", "a.example.com") == "invalid_client"
    assert refused(LAB, "bad name") == "invalid_domain"
    assert refused(LAB, "*.example.com") == "invalid_domain"
    assert refused(LAB, 5) == "invalid_domain"
    assert refused(OTHER, "a.example.com") == "client_not_tracked"
    assert refused(LAB, "other.example.com") == "domain_not_known"
    # The allowlist client knows the domain, but Block is for learning zones.
    assert refused(KID, "kid.example.com") == "client_not_in_learning_zone"
    assert harness.lists.entries("deny_a") == []
    assert harness.lists.entries("allow_a") == ["kid.example.com"]


async def test_block_known_needs_a_deny_list_and_the_same_zone(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    zones = read_zones(OPTIONS, read_definitions(OPTIONS))
    harness = await make(zones=zones)
    await _learn(hass, harness, LAB2, "x.example.com")
    await _learn(hass, harness, LAB, "a.example.com")

    with pytest.raises(RequestError) as err:
        harness.tracker.async_block_known(LAB2, "x.example.com")
    assert err.value.code == "no_deny_list"

    # The zone was removed after the client was tracked.
    del zones["lab"]
    with pytest.raises(RequestError) as err:
        harness.tracker.async_block_known(LAB, "a.example.com")
    assert err.value.code == "zone_changed"
    assert harness.lists.entries("deny_a") == []


async def test_block_known_reports_a_full_list(
    hass: HomeAssistant, make: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from custom_components.ha_blocky.lists import ListError

    harness = await make()
    await _learn(hass, harness, LAB, "a.example.com")

    def full(*args: Any) -> None:
        raise ListError("list_full")

    monkeypatch.setattr(harness.lists, "async_add", full)
    with pytest.raises(RequestError) as err:
        harness.tracker.async_block_known(LAB, "a.example.com")

    assert err.value.code == "list_failed"


async def _tracked_entry(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
) -> MockConfigEntry:
    entry, ids = await _with_requests(hass, aioclient_mock, log_url, freezer)
    tracker = entry.runtime_data.requests
    tracker.async_resolve(ids["learning"], "reject")
    tracker.async_resolve(ids["approval"], "approve")
    return entry


async def test_known_domains_commands(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
    hass_ws_client: WebSocketGenerator,
) -> None:
    entry = await _tracked_entry(hass, aioclient_mock, log_url, freezer)
    client = await hass_ws_client(hass)

    tracked = (await _command(client, 1, type=f"{DOMAIN}/requests"))["result"][
        "tracked"
    ]
    assert {(item["client"], item["mode"], item["known"]) for item in tracked} == {
        (LAB, "learning", 1),
        (KID, "allowlist_only", 1),
    }

    response = await _command(
        client, 2, type=f"{DOMAIN}/known_domains", client=f"::ffff:{LAB}"
    )
    assert response["success"]
    assert response["result"] == {
        "client": LAB,
        "client_name": None,
        "zone": "lab",
        "mode": "learning",
        "total": 1,
        "domains": ["learn.example.com"],
    }

    response = await _command(
        client, 3, type=f"{DOMAIN}/block_known", client=LAB, domain="LEARN.example.com."
    )
    assert response["success"]
    assert response["result"] == {"client": LAB, "domain": "learn.example.com"}
    assert entry.runtime_data.lists.entries("deny_a") == ["learn.example.com"]

    # An allowlist-only client's list can be read but not blocked from.
    response = await _command(client, 4, type=f"{DOMAIN}/known_domains", client=KID)
    assert response["result"]["domains"] == ["kid.example.com"]
    response = await _command(
        client, 5, type=f"{DOMAIN}/block_known", client=KID, domain="kid.example.com"
    )
    assert response["success"] is False
    assert response["error"]["code"] == "client_not_in_learning_zone"
    assert "example.com" not in response["error"]["message"]
    assert entry.runtime_data.lists.entries("deny_a") == ["learn.example.com"]


@pytest.mark.parametrize(
    ("kind", "message", "code"),
    [
        ("known_domains", {"client": "nope"}, "invalid_format"),
        ("known_domains", {"client": 5}, "invalid_format"),
        ("known_domains", {"client": "1" * 100}, "invalid_format"),
        ("known_domains", {}, "invalid_format"),
        ("known_domains", {"client": LAB, "extra": 1}, "invalid_format"),
        ("known_domains", {"client": OTHER}, "client_not_tracked"),
        ("known_domains", {"client": LAB, "entry_id": "nope"}, "entry_not_found"),
        (
            "block_known",
            {"client": "nope", "domain": "a.example.com"},
            "invalid_format",
        ),
        ("block_known", {"client": LAB, "domain": "bad name"}, "invalid_format"),
        ("block_known", {"client": LAB, "domain": "*.example.com"}, "invalid_format"),
        ("block_known", {"client": LAB, "domain": "x" * 300}, "invalid_format"),
        ("block_known", {"client": LAB, "domain": ["a.example.com"]}, "invalid_format"),
        ("block_known", {"client": LAB}, "invalid_format"),
        ("block_known", {"domain": "a.example.com"}, "invalid_format"),
        (
            "block_known",
            {"client": OTHER, "domain": "a.example.com"},
            "client_not_tracked",
        ),
        (
            "block_known",
            {"client": LAB, "domain": "zzz.example.com"},
            "domain_not_known",
        ),
        (
            "block_known",
            {"client": LAB, "domain": "learn.example.com", "entry_id": "nope"},
            "entry_not_found",
        ),
    ],
)
async def test_known_domain_commands_fail_closed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
    hass_ws_client: WebSocketGenerator,
    kind: str,
    message: dict[str, Any],
    code: str,
) -> None:
    entry = await _tracked_entry(hass, aioclient_mock, log_url, freezer)
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=f"{DOMAIN}/{kind}", **message)

    assert response["success"] is False
    assert response["error"]["code"] == code
    assert entry.runtime_data.lists.entries("deny_a") == []


NEW_COMMANDS = {
    "known_domains": {"client": LAB},
    "block_known": {"client": LAB, "domain": "a.example.com"},
    "overview": {},
}


@pytest.mark.parametrize("kind", sorted(NEW_COMMANDS))
async def test_known_domain_and_overview_commands_are_admin_only(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: MockUser,
    kind: str,
) -> None:
    await _setup(hass, aioclient_mock, OPTIONS)
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=f"{DOMAIN}/{kind}", **NEW_COMMANDS[kind])

    assert response["success"] is False
    assert response["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("kind", sorted(NEW_COMMANDS))
async def test_known_domain_and_overview_commands_need_the_query_log(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    kind: str,
) -> None:
    await _setup(hass, aioclient_mock, LISTS)
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=f"{DOMAIN}/{kind}", **NEW_COMMANDS[kind])

    assert response["success"] is False
    assert response["error"]["code"] == "no_query_log"


async def test_overview_command(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    log_url: URL,
    freezer: FrozenDateTimeFactory,
    hass_ws_client: WebSocketGenerator,
) -> None:
    add_rows(
        log_url,
        [
            log_row("busy.example.com", client=LAB),
            log_row("busy.example.com", client=LAB),
            log_row("busy.example.com", client=KID),
            log_row("ads.example.com", client=KID, response_type="BLOCKED"),
            log_row("ads.example.com", client=KID, response_type="BLOCKED"),
        ],
    )
    entry = await _setup(hass, aioclient_mock, OPTIONS)
    await _poll(hass, freezer, STATS_INTERVAL)
    client = await hass_ws_client(hass)
    await _command(client, 1, type=f"{DOMAIN}/set_client_name", ip=LAB, name="Lab PC")

    response = await _command(client, 2, type=f"{DOMAIN}/overview")

    assert response["success"]
    result = response["result"]
    assert result["entry_id"] == entry.entry_id
    assert result["top_domains"][0] == {"name": "busy.example.com", "count": 3}
    assert result["top_blocked_domains"] == [{"name": "ads.example.com", "count": 2}]
    clients = {
        item["name"]: (item["count"], item["client_name"])
        for item in result["top_clients"]
    }
    assert clients == {LAB: (2, "Lab PC"), KID: (3, None)}
    assert result["requests"] == entry.runtime_data.requests.describe_requests()
    assert set(result) == {
        "entry_id",
        "top_domains",
        "top_blocked_domains",
        "top_clients",
        "requests",
    }
    # An unknown entry and a bad message fail closed.
    unknown = await _command(client, 3, type=f"{DOMAIN}/overview", entry_id="nope")
    assert unknown["error"]["code"] == "entry_not_found"
    bad = await _command(client, 4, type=f"{DOMAIN}/overview", entry_id=5)
    assert bad["error"]["code"] == "invalid_format"


# --- Source checks ------------------------------------------------------------------


def test_the_tracker_builds_no_sql_and_adds_no_dependencies() -> None:
    from pathlib import Path

    root = Path(req.__file__).parent
    source = (root / "requests.py").read_text(encoding="utf-8")
    for forbidden in ("text(", "execute(", "eval(", "exec(", "pickle", "subprocess"):
        assert forbidden not in source, forbidden
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["requirements"] == []


# --- Client names ----------------------------------------------------------------


async def test_events_and_descriptions_carry_the_client_name(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    calls: list[int] = []

    def names() -> dict[str, str]:
        calls.append(1)
        return {LAB: "Lab PC", KID: "Kid Tablet"}

    harness = await make(client_names=names)
    harness.tracker.async_set_client_phase(KID_B, "locked")
    new = async_capture_events(hass, EVENT_NEW_DOMAIN)
    unexpected = async_capture_events(hass, EVENT_UNEXPECTED_DOMAIN)
    harness.add(
        row("one.example.com"),
        row("two.example.com", LAB_B),
        blocked("three.example.com"),
        blocked("four.example.com", KID_B),
    )
    calls.clear()

    await harness_round(hass, harness)

    # One map per round, however many events it raised.
    assert len(calls) == 1
    assert {(e["client"], e["client_name"]) for e in data_of(new)} == {
        (LAB, "Lab PC"),
        (LAB_B, None),
        (KID, "Kid Tablet"),
    }
    assert [(e["client"], e["client_name"]) for e in data_of(unexpected)] == [
        (KID_B, None)
    ]
    described = {
        r["client"]: r["client_name"] for r in harness.tracker.describe_requests()
    }
    assert described == {LAB: "Lab PC", LAB_B: None, KID: "Kid Tablet"}
    phases = {c["client"]: c["client_name"] for c in harness.tracker.describe_clients()}
    assert phases[KID] == "Kid Tablet"
    assert phases[KID_B] is None


async def test_leak_and_summary_events_carry_the_client_name(
    hass: HomeAssistant, make: Callable[..., Any], freezer: FrozenDateTimeFactory
) -> None:
    harness = await make(client_names=lambda: {LAB: "Lab PC", KID: "Kid Tablet"})
    harness.lists.async_add("allow_a", "ok.example.com", "allow")
    leaks = async_capture_events(hass, EVENT_ZONE_LEAK)
    summaries = async_capture_events(hass, EVENT_NEW_DOMAINS_SUMMARY)
    harness.add(row("leak.example.com", KID, "CACHED"))
    harness.add(*(row(f"d{i}.example.com") for i in range(8)))

    await harness_round(hass, harness)
    freezer.tick(timedelta(minutes=11))
    await harness_round(hass, harness)
    await harness_round(hass, harness)

    assert [e["client_name"] for e in data_of(leaks)] == ["Kid Tablet"]
    assert [e["client_name"] for e in data_of(summaries)] == ["Lab PC"]


async def test_without_a_name_source_the_name_is_none(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make()
    events = async_capture_events(hass, EVENT_NEW_DOMAIN)
    harness.add(row("one.example.com"))

    await harness_round(hass, harness)

    assert data_of(events)[0]["client_name"] is None


async def test_the_baseline_query_is_timed_for_diagnostics(
    hass: HomeAssistant, make: Callable[..., Any]
) -> None:
    harness = await make(report_existing=False)
    assert harness.tracker.diagnostics()["baseline_last_duration_ms"] is None
    harness.add(row("everyday.example.com"))

    await harness_round(hass, harness)

    assert harness.tracker._clients[LAB].baselined
    duration = harness.tracker.diagnostics()["baseline_last_duration_ms"]
    assert isinstance(duration, float)
    assert duration >= 0
