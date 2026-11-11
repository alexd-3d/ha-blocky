"""Tests for the query log card: its commands, its file and its texts."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import timedelta
from typing import Any

import pytest
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import (
    ClientSessionGenerator,
    WebSocketGenerator,
)
from sqlalchemy.engine import URL

from custom_components.ha_blocky import db
from custom_components.ha_blocky.const import DOMAIN, MAX_LOG_ROWS
from custom_components.ha_blocky.frontend import CARD_PATH, CARD_URL

from .test_db import add_rows
from .test_lists import LIST_OPTIONS
from .test_stats import DB_OPTIONS, log_row

BASE_URL = "http://blocky.example:4000"
STATUS_URL = f"{BASE_URL}/api/blocking/status"
ENABLED = {"enabled": True, "disabledGroups": [], "autoEnableInSec": 0}

SOURCE = CARD_PATH.read_text(encoding="utf-8")


async def _setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    assert await async_setup_component(hass, "http", {})
    aioclient_mock.get(STATUS_URL, json=ENABLED)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_URL: BASE_URL},
        options={**DB_OPTIONS, **LIST_OPTIONS} if options is None else options,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _command(ws: Any, message_id: int, /, **message: Any) -> dict[str, Any]:
    await ws.send_json({"id": message_id, **message})
    return await ws.receive_json()


# --- The file ---------------------------------------------------------------


def test_card_never_interprets_data_as_markup() -> None:
    """Log values are attacker-controlled; only text sinks are allowed."""
    for sink in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
        'setAttribute("on',
        "srcdoc",
        "javascript:",
    ):
        assert sink not in SOURCE, sink
    assert "textContent" in SOURCE


def test_card_loads_nothing_from_outside() -> None:
    assert not re.search(r"https?://", SOURCE)
    for loader in ("import(", "importScripts", "fetch(", "XMLHttpRequest", "<script"):
        assert loader not in SOURCE, loader
    assert not re.search(r"^\s*import\s", SOURCE, flags=re.MULTILINE)


def test_card_stays_small() -> None:
    assert len(SOURCE.splitlines()) <= 600


def _texts(language: str) -> dict[str, str]:
    match = re.search(
        rf"/\* i18n:{language} \*/\s*const \w+ = (\{{.*?\}});\s*/\* i18n:end \*/",
        SOURCE,
        flags=re.DOTALL,
    )
    assert match is not None, language
    return json.loads(match.group(1))


def test_card_texts_default_to_english_and_translations_mirror_it() -> None:
    english = _texts("en")
    ukrainian = _texts("uk")

    assert english and all(text.strip() for text in english.values())
    assert set(ukrainian) == set(english)
    assert all(text.strip() for text in ukrainian.values())
    # Every key the code asks for exists in English.
    used = set(re.findall(r'_t\("(\w+)"\)', SOURCE))
    used |= {f"status_{status}" for status in ("all", "blocked", "allowed")}
    used |= {f"hours_{hours}" for hours in (1, 6, 24, 168, 720)}
    used |= set(re.findall(r'label: "(\w+)"', SOURCE))
    assert used <= set(english)
    assert "TEXT_EN[key]" in SOURCE


def test_card_javascript_is_valid() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        [node, "--check", str(CARD_PATH)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


# --- Serving ----------------------------------------------------------------


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_card_file_is_served(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    await _setup(hass, aioclient_mock, {})
    client = await hass_client_no_auth()

    response = await client.get(CARD_URL)

    assert response.status == 200
    assert "javascript" in response.content_type
    assert "ha-blocky-card" in await response.text()


# --- Commands ---------------------------------------------------------------


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_config_command(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=f"{DOMAIN}/config")

    assert response["success"]
    assert response["result"] == {
        "entries": [
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "has_query_log": True,
                "lists": [
                    {"name": "allow_default", "type": "allow", "exact_only": False},
                    {"name": "deny_default", "type": "deny", "exact_only": False},
                    {"name": "allow_quarantine", "type": "allow", "exact_only": True},
                ],
                "zones": [],
            }
        ]
    }
    # Nothing secret is exposed to the card.
    dumped = json.dumps(response)
    assert entry.runtime_data.lists.token not in dumped
    assert DB_OPTIONS["db_password"] not in dumped
    assert "blocky.example" not in dumped


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_query_log_filters_and_pages(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    add_rows(
        log_url,
        [
            log_row("a.example.com", client="192.0.2.10"),
            log_row(
                "ads.tracker.example", client="192.0.2.10", response_type="BLOCKED"
            ),
            log_row("b.example.com", client="192.0.2.11", duration_ms=42),
            log_row("rebind.example", client="192.0.2.11", response_type="REBIND"),
            log_row("old.example.com", age=timedelta(hours=30)),
        ],
    )
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    kind = f"{DOMAIN}/query_log"

    everything = (await _command(client, 1, type=kind))["result"]
    assert [row["domain"] for row in everything["rows"]] == [
        "rebind.example",
        "b.example.com",
        "ads.tracker.example",
        "a.example.com",
    ]
    assert everything["has_more"] is False
    newest = everything["rows"][0]
    assert newest["blocked"] is True
    assert newest["response_type"] == "REBIND"
    assert newest["time"].endswith("+00:00")
    assert everything["rows"][1]["duration_ms"] == 42

    blocked = (await _command(client, 2, type=kind, status="blocked"))["result"]
    assert [row["domain"] for row in blocked["rows"]] == [
        "rebind.example",
        "ads.tracker.example",
    ]
    allowed = (await _command(client, 3, type=kind, status="allowed"))["result"]
    assert [row["domain"] for row in allowed["rows"]] == [
        "b.example.com",
        "a.example.com",
    ]
    by_client = (await _command(client, 4, type=kind, client="192.0.2.11"))["result"]
    assert len(by_client["rows"]) == 2
    by_domain = (await _command(client, 5, type=kind, domain="example.com"))["result"]
    assert [row["domain"] for row in by_domain["rows"]] == [
        "b.example.com",
        "a.example.com",
    ]
    week = (await _command(client, 6, type=kind, hours=168))["result"]
    assert len(week["rows"]) == 5

    first = (await _command(client, 7, type=kind, limit=2))["result"]
    assert [row["domain"] for row in first["rows"]] == [
        "rebind.example",
        "b.example.com",
    ]
    assert first["has_more"] is True
    second = (
        await _command(client, 8, type=kind, limit=2, before_id=first["next_before_id"])
    )["result"]
    assert [row["domain"] for row in second["rows"]] == [
        "ads.tracker.example",
        "a.example.com",
    ]


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_query_log_search_is_literal(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    add_rows(
        log_url,
        [
            log_row("plain.example.com"),
            log_row("with_underscore.example"),
            log_row("with%percent.example"),
            log_row("x'; DROP TABLE log_entries; --"),
            log_row("<img src=x onerror=alert(1)>\x00"),
        ],
    )
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    kind = f"{DOMAIN}/query_log"

    async def search(message_id: int, text: str) -> list[str]:
        response = await _command(client, message_id, type=kind, domain=text)
        assert response["success"], response
        return [row["domain"] for row in response["result"]["rows"]]

    # LIKE wildcards in the search text match themselves, not "anything".
    assert await search(1, "%") == ["with%percent.example"]
    assert await search(2, "_") == [
        "x'; DROP TABLE log_entries; --",
        "with_underscore.example",
    ]
    assert await search(3, "' OR '1'='1") == []
    assert await search(4, "DROP TABLE") == ["x'; DROP TABLE log_entries; --"]
    # Hostile names come back as cleaned plain text and the table survives.
    assert await search(5, "onerror") == ["<img src=x onerror=alert(1)>"]
    assert len(await search(6, "example")) == 3


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize(
    "message",
    [
        {"hours": 0},
        {"hours": 100000},
        {"hours": "24"},
        {"limit": 0},
        {"limit": MAX_LOG_ROWS + 1},
        {"status": "everything"},
        {"before_id": 0},
        {"before_id": -5},
        {"domain": "x" * 254},
        {"domain": "bad\x00name"},
        {"client": "y" * 65},
        {"client": ["192.0.2.1"]},
        {"unexpected": True},
    ],
)
async def test_query_log_rejects_bad_requests(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    message: dict[str, Any],
) -> None:
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=f"{DOMAIN}/query_log", **message)

    assert response["success"] is False
    assert response["error"]["code"] == "invalid_format"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_query_log_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    kind = f"{DOMAIN}/query_log"

    unknown = await _command(client, 1, type=kind, entry_id="nope")
    assert unknown["error"]["code"] == "entry_not_found"

    def broken(self: db.QueryLogDatabase, **kwargs: Any) -> list[dict[str, Any]]:
        raise db.BlockyDbError("OperationalError: secret detail")

    monkeypatch.setattr(db.QueryLogDatabase, "query_log", broken)
    failed = await _command(client, 2, type=kind)
    assert failed["error"]["code"] == "database_error"
    assert "secret detail" not in json.dumps(failed)


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_query_log_without_a_database(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
) -> None:
    await _setup(hass, aioclient_mock, {})
    client = await hass_ws_client(hass)

    config = await _command(client, 1, type=f"{DOMAIN}/config")
    assert config["result"]["entries"][0]["has_query_log"] is False
    response = await _command(client, 2, type=f"{DOMAIN}/query_log")
    assert response["error"]["code"] == "no_query_log"


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize("kind", ["config", "query_log"])
async def test_commands_are_admin_only(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: MockUser,
    log_url: URL,
    kind: str,
) -> None:
    await _setup(hass, aioclient_mock)
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=f"{DOMAIN}/{kind}")

    assert response["success"] is False
    assert response["error"]["code"] == "unauthorized"
