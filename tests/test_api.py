"""Tests for the Blocky API client against a local fake server."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer, unused_port

from custom_components.ha_blocky import api
from custom_components.ha_blocky.api import (
    MAX_DISABLE_SECONDS,
    MAX_GROUPS,
    MAX_RESPONSE_BYTES,
    BlockingStatus,
    BlockyClient,
    BlockyConnectionError,
    BlockyInvalidUrlError,
    BlockyResponseError,
    normalize_base_url,
    validate_group_names,
)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]

GOOD_STATUS = {"enabled": True, "disabledGroups": [], "autoEnableInSec": 0}


class FakeBlocky:
    """A local HTTP server that records calls and returns canned answers."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.status_body: bytes = json.dumps(GOOD_STATUS).encode()
        self.status_code: int = 200
        self.override: Handler | None = None
        self.url: str = ""

    async def handle(self, request: web.Request) -> web.StreamResponse:
        self.calls.append((request.method, request.path, dict(request.query)))
        if self.override is not None:
            return await self.override(request)
        if request.path == "/api/blocking/status":
            return web.Response(
                body=self.status_body,
                status=self.status_code,
                content_type="application/json",
            )
        return web.Response(text="")


@pytest.fixture
async def fake_blocky(socket_enabled: None) -> AsyncIterator[FakeBlocky]:
    """Start the fake server; localhost sockets are allowed for these tests."""
    fake = FakeBlocky()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", fake.handle)
    server = TestServer(app)
    await server.start_server()
    fake.url = str(server.make_url("")).rstrip("/")
    try:
        yield fake
    finally:
        await server.close()


@pytest.fixture
async def session(socket_enabled: None) -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client_session:
        yield client_session


@pytest.fixture
def client(fake_blocky: FakeBlocky, session: aiohttp.ClientSession) -> BlockyClient:
    return BlockyClient(session, fake_blocky.url)


# --- URL validation ---------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://blocky.example:4000", "http://blocky.example:4000"),
        ("http://blocky.example:4000/", "http://blocky.example:4000"),
        ("  HTTP://Blocky.Example:4000  ", "http://blocky.example:4000"),
        ("https://blocky.example", "https://blocky.example"),
        ("http://blocky.example:80", "http://blocky.example"),
        ("http://192.0.2.10:4000", "http://192.0.2.10:4000"),
        ("http://[2001:db8::1]:4000", "http://[2001:db8::1]:4000"),
    ],
)
def test_normalize_base_url_accepts(value: str, expected: str) -> None:
    assert normalize_base_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "blocky.example:4000",
        "//blocky.example:4000",
        "ftp://blocky.example",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://",
        "http://user:secret@blocky:4000",
        "http://user@blocky:4000",
        "http://blocky.example:4000/api",
        "http://blocky.example:4000/?x=1",
        "http://blocky.example:4000/#frag",
        "http://blocky.example:99999",
        "http://blocky.example:port",
        "http://blocky\n.example:4000",
        "http://blocky.example:4000\x00",
        "http://" + "a" * 3000,
        None,
        4000,
        b"http://blocky.example:4000",
    ],
)
def test_normalize_base_url_rejects(value: Any) -> None:
    with pytest.raises(BlockyInvalidUrlError):
        normalize_base_url(value)


def test_client_rejects_bad_url(session: aiohttp.ClientSession) -> None:
    with pytest.raises(BlockyInvalidUrlError):
        BlockyClient(session, "http://blocky.example:4000/evil")


# --- Group name validation --------------------------------------------------


def test_validate_group_names_accepts() -> None:
    assert validate_group_names(["default", "iot", "kids room", "a.b_c-d"]) == (
        "default",
        "iot",
        "kids room",
        "a.b_c-d",
    )
    assert validate_group_names([]) == ()


@pytest.mark.parametrize(
    "groups",
    [
        "default",
        ["a,b"],
        [""],
        [" padded"],
        ["padded "],
        ["line\nbreak"],
        ["nul\x00"],
        ["x" * 65],
        [1],
        [None],
        ["g"] * (MAX_GROUPS + 1),
        None,
    ],
)
def test_validate_group_names_rejects(groups: Any) -> None:
    with pytest.raises(ValueError):
        validate_group_names(groups)


# --- Status -----------------------------------------------------------------


async def test_get_status(fake_blocky: FakeBlocky, client: BlockyClient) -> None:
    fake_blocky.status_body = json.dumps(
        {"enabled": False, "disabledGroups": ["default", "iot"], "autoEnableInSec": 297}
    ).encode()

    status = await client.async_get_status()

    assert status == BlockingStatus(
        enabled=False, disabled_groups=("default", "iot"), auto_enable_in_sec=297
    )
    assert fake_blocky.calls == [("GET", "/api/blocking/status", {})]


@pytest.mark.parametrize(
    "payload",
    [
        {"enabled": True},
        {"enabled": True, "disabledGroups": None, "autoEnableInSec": None},
        {"enabled": True, "unknownField": {"nested": [1, 2, 3]}},
    ],
)
async def test_get_status_optional_fields(
    fake_blocky: FakeBlocky, client: BlockyClient, payload: dict[str, Any]
) -> None:
    fake_blocky.status_body = json.dumps(payload).encode()

    status = await client.async_get_status()

    assert status == BlockingStatus(
        enabled=True, disabled_groups=(), auto_enable_in_sec=0
    )


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"<html><script>alert(1)</script></html>",
        b"\xff\xfe\x00",
        b"[]",
        b"null",
        b'"enabled"',
        b"{}",
        b'{"enabled": "true"}',
        b'{"enabled": 1}',
        b'{"enabled": null}',
        b'{"enabled": true, "disabledGroups": "default"}',
        b'{"enabled": true, "disabledGroups": [1]}',
        b'{"enabled": true, "disabledGroups": [["nested"]]}',
        json.dumps({"enabled": True, "disabledGroups": ["x" * 65]}).encode(),
        json.dumps(
            {"enabled": True, "disabledGroups": ["g"] * (MAX_GROUPS + 1)}
        ).encode(),
        b'{"enabled": true, "autoEnableInSec": -1}',
        b'{"enabled": true, "autoEnableInSec": 1.5}',
        b'{"enabled": true, "autoEnableInSec": true}',
        b'{"enabled": true, "autoEnableInSec": "60"}',
        b'{"enabled": true, "autoEnableInSec": 99999999999999999999}',
    ],
)
async def test_get_status_rejects_bad_payload(
    fake_blocky: FakeBlocky, client: BlockyClient, body: bytes
) -> None:
    fake_blocky.status_body = body

    with pytest.raises(BlockyResponseError):
        await client.async_get_status()


@pytest.mark.parametrize("status_code", [201, 204, 400, 401, 404, 500, 503])
async def test_get_status_rejects_http_status(
    fake_blocky: FakeBlocky, client: BlockyClient, status_code: int
) -> None:
    fake_blocky.status_code = status_code

    with pytest.raises(BlockyResponseError):
        await client.async_get_status()


async def test_response_size_is_limited(
    fake_blocky: FakeBlocky, client: BlockyClient
) -> None:
    fake_blocky.status_body = b" " * (MAX_RESPONSE_BYTES + 1)

    with pytest.raises(BlockyResponseError, match="too large"):
        await client.async_get_status()


async def test_redirects_are_not_followed(
    fake_blocky: FakeBlocky, client: BlockyClient
) -> None:
    async def redirect(request: web.Request) -> web.StreamResponse:
        if request.path == "/elsewhere":
            return web.json_response(GOOD_STATUS)
        raise web.HTTPFound("/elsewhere")

    fake_blocky.override = redirect

    with pytest.raises(BlockyResponseError):
        await client.async_get_status()

    assert [call[1] for call in fake_blocky.calls] == ["/api/blocking/status"]


async def test_timeout_is_a_connection_error(
    fake_blocky: FakeBlocky, client: BlockyClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def slow(request: web.Request) -> web.StreamResponse:
        await asyncio.sleep(5)
        return web.json_response(GOOD_STATUS)

    fake_blocky.override = slow
    monkeypatch.setattr(api, "REQUEST_TIMEOUT", aiohttp.ClientTimeout(total=0.2))

    with pytest.raises(BlockyConnectionError):
        await client.async_get_status()


async def test_unreachable_server(session: aiohttp.ClientSession) -> None:
    client = BlockyClient(session, f"http://127.0.0.1:{unused_port()}")

    with pytest.raises(BlockyConnectionError):
        await client.async_get_status()


async def test_error_text_does_not_echo_response(
    fake_blocky: FakeBlocky, client: BlockyClient
) -> None:
    fake_blocky.status_body = b'{"enabled": "<img src=x onerror=alert(1)>"}'

    with pytest.raises(BlockyResponseError) as excinfo:
        await client.async_get_status()

    assert "onerror" not in str(excinfo.value)


# --- Commands ---------------------------------------------------------------


async def test_enable_blocking(fake_blocky: FakeBlocky, client: BlockyClient) -> None:
    await client.async_enable_blocking()

    assert fake_blocky.calls == [("GET", "/api/blocking/enable", {})]


async def test_disable_blocking(fake_blocky: FakeBlocky, client: BlockyClient) -> None:
    await client.async_disable_blocking(300)
    await client.async_disable_blocking(60, ["default", "kids room"])

    assert fake_blocky.calls == [
        ("GET", "/api/blocking/disable", {"duration": "300s"}),
        (
            "GET",
            "/api/blocking/disable",
            {"duration": "60s", "groups": "default,kids room"},
        ),
    ]


@pytest.mark.parametrize(
    "duration",
    [0, -1, MAX_DISABLE_SECONDS + 1, True, 1.5, "300", None],
)
async def test_disable_blocking_rejects_duration(
    fake_blocky: FakeBlocky, client: BlockyClient, duration: Any
) -> None:
    with pytest.raises(ValueError):
        await client.async_disable_blocking(duration)

    assert fake_blocky.calls == []


async def test_disable_blocking_rejects_groups(
    fake_blocky: FakeBlocky, client: BlockyClient
) -> None:
    with pytest.raises(ValueError):
        await client.async_disable_blocking(60, ["default,quarantine"])

    assert fake_blocky.calls == []


async def test_refresh_and_flush(fake_blocky: FakeBlocky, client: BlockyClient) -> None:
    await client.async_refresh_lists()
    await client.async_flush_cache()

    assert fake_blocky.calls == [
        ("POST", "/api/lists/refresh", {}),
        ("POST", "/api/cache/flush", {}),
    ]


async def test_command_failure_is_reported(
    fake_blocky: FakeBlocky, client: BlockyClient
) -> None:
    async def fail(request: web.Request) -> web.StreamResponse:
        return web.Response(status=500, text="boom")

    fake_blocky.override = fail

    with pytest.raises(BlockyResponseError):
        await client.async_refresh_lists()
