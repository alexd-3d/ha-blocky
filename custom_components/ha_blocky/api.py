"""Client for the Blocky REST API.

Blocky's API has no authentication and its responses are not trusted: every
response is size-limited, parsed strictly and validated before use.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

import aiohttp
from yarl import URL

REQUEST_TIMEOUT: Final = aiohttp.ClientTimeout(total=10)
# Reloading all lists is synchronous on the Blocky side and can take a while.
REFRESH_TIMEOUT: Final = aiohttp.ClientTimeout(total=120)

MAX_URL_LENGTH: Final = 2048
MAX_RESPONSE_BYTES: Final = 64 * 1024
MAX_DISABLE_SECONDS: Final = 24 * 60 * 60
MAX_GROUPS: Final = 64
MAX_GROUP_NAME_LENGTH: Final = 64

_ALLOWED_SCHEMES: Final = frozenset({"http", "https"})


class BlockyError(Exception):
    """Base error for the Blocky client."""


class BlockyInvalidUrlError(BlockyError):
    """The configured API URL is not acceptable."""


class BlockyConnectionError(BlockyError):
    """Blocky could not be reached."""


class BlockyResponseError(BlockyError):
    """Blocky answered with something unexpected."""


@dataclass(frozen=True, slots=True)
class BlockingStatus:
    """State of blocking as reported by Blocky."""

    enabled: bool
    disabled_groups: tuple[str, ...]
    auto_enable_in_sec: int


def normalize_base_url(value: object) -> str:
    """Validate a Blocky base URL and return its canonical form.

    Only ``http(s)://host[:port]`` is accepted: no credentials, path, query or
    fragment.
    """
    if not isinstance(value, str):
        raise BlockyInvalidUrlError("URL must be a string")
    text = value.strip()
    if not text or len(text) > MAX_URL_LENGTH:
        raise BlockyInvalidUrlError("URL is empty or too long")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in text):
        raise BlockyInvalidUrlError("URL contains control characters")

    try:
        url = URL(text)
        port = url.port
    except (ValueError, TypeError) as err:
        raise BlockyInvalidUrlError("URL cannot be parsed") from err

    if url.scheme not in _ALLOWED_SCHEMES:
        raise BlockyInvalidUrlError("URL scheme must be http or https")
    if not url.host:
        raise BlockyInvalidUrlError("URL has no host")
    if url.user is not None or url.password is not None:
        raise BlockyInvalidUrlError("URL must not contain credentials")
    if url.path not in ("", "/"):
        raise BlockyInvalidUrlError("URL must not contain a path")
    if url.query_string or url.fragment:
        raise BlockyInvalidUrlError("URL must not contain a query or fragment")

    return str(URL.build(scheme=url.scheme, host=url.host, port=port))


def validate_group_names(groups: Sequence[str]) -> tuple[str, ...]:
    """Validate client group names sent to Blocky.

    Blocky separates names with commas, so a comma inside a name cannot be
    expressed. Control characters and surrounding whitespace are rejected.
    """
    if isinstance(groups, str) or not isinstance(groups, Sequence):
        raise ValueError("groups must be a sequence of names")
    if len(groups) > MAX_GROUPS:
        raise ValueError("too many groups")
    validated: list[str] = []
    for name in groups:
        if not isinstance(name, str):
            raise ValueError("group name must be a string")
        if not name or len(name) > MAX_GROUP_NAME_LENGTH:
            raise ValueError("group name is empty or too long")
        if name != name.strip() or "," in name:
            raise ValueError("group name has a comma or surrounding whitespace")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in name):
            raise ValueError("group name contains control characters")
        validated.append(name)
    return tuple(validated)


def _parse_blocking_status(payload: Any) -> BlockingStatus:
    """Strictly validate the /blocking/status payload."""
    if not isinstance(payload, dict):
        raise BlockyResponseError("status is not an object")

    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise BlockyResponseError("status.enabled is not a boolean")

    raw_groups = payload.get("disabledGroups")
    if raw_groups is None:
        raw_groups = []
    if not isinstance(raw_groups, list) or len(raw_groups) > MAX_GROUPS:
        raise BlockyResponseError("status.disabledGroups is not a short list")
    for name in raw_groups:
        if not isinstance(name, str) or len(name) > MAX_GROUP_NAME_LENGTH:
            raise BlockyResponseError("status.disabledGroups has a bad entry")

    auto_enable = payload.get("autoEnableInSec")
    if auto_enable is None:
        auto_enable = 0
    if (
        isinstance(auto_enable, bool)
        or not isinstance(auto_enable, int)
        or not 0 <= auto_enable <= MAX_DISABLE_SECONDS * 366
    ):
        raise BlockyResponseError("status.autoEnableInSec is not a valid integer")

    return BlockingStatus(
        enabled=enabled,
        disabled_groups=tuple(raw_groups),
        auto_enable_in_sec=auto_enable,
    )


class BlockyClient:
    """Minimal async client for the Blocky REST API."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str) -> None:
        """Create a client for the Blocky instance at ``base_url``."""
        self._session = session
        self._base_url = URL(normalize_base_url(base_url))

    @property
    def base_url(self) -> str:
        """Return the canonical base URL."""
        return str(self._base_url)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        timeout: aiohttp.ClientTimeout | None = None,
    ) -> bytes:
        """Send a request and return the size-limited response body."""
        url = self._base_url.with_path(f"/api/{path}")
        if params:
            url = url.with_query(params)

        try:
            response = await self._session.request(
                method,
                url,
                timeout=timeout or REQUEST_TIMEOUT,
                allow_redirects=False,
                headers={"Accept": "application/json"},
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise BlockyConnectionError(type(err).__name__) from err

        try:
            if response.status != 200:
                raise BlockyResponseError(f"unexpected HTTP status {response.status}")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.content.iter_chunked(8192):
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    raise BlockyResponseError("response is too large")
                chunks.append(chunk)
        except (aiohttp.ClientError, TimeoutError) as err:
            response.close()
            raise BlockyConnectionError(type(err).__name__) from err
        except BlockyResponseError:
            response.close()
            raise
        response.release()
        return b"".join(chunks)

    async def async_get_status(self) -> BlockingStatus:
        """Return the current blocking status."""
        body = await self._request("GET", "blocking/status")
        try:
            payload = json.loads(body)
        except ValueError as err:
            raise BlockyResponseError("status is not valid JSON") from err
        return _parse_blocking_status(payload)

    async def async_enable_blocking(self) -> None:
        """Enable blocking for all groups."""
        await self._request("GET", "blocking/enable")

    async def async_disable_blocking(
        self, duration_seconds: int, groups: Sequence[str] = ()
    ) -> None:
        """Disable blocking for a limited time.

        A duration is mandatory: this client never disables blocking forever.
        """
        if (
            isinstance(duration_seconds, bool)
            or not isinstance(duration_seconds, int)
            or not 1 <= duration_seconds <= MAX_DISABLE_SECONDS
        ):
            raise ValueError("duration must be between 1 second and 24 hours")
        names = validate_group_names(groups)

        params = {"duration": f"{duration_seconds}s"}
        if names:
            params["groups"] = ",".join(names)
        await self._request("GET", "blocking/disable", params=params)

    async def async_refresh_lists(self) -> None:
        """Reload all allow and deny lists."""
        await self._request("POST", "lists/refresh", timeout=REFRESH_TIMEOUT)

    async def async_flush_cache(self) -> None:
        """Clear the DNS response cache."""
        await self._request("POST", "cache/flush")
