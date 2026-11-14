"""The rule lists served to Blocky.

The lists are fixed (see ``RULE_LISTS``); their entries, the access token and
the last applied configuration live in a store. Nothing read back from it is
trusted: entries, the token and the snapshot are re-validated on load. The
fetches of Blocky are only remembered in memory, and only as (list, revision,
time) for the fixed list names.
"""

from __future__ import annotations

import hmac
import logging
import secrets
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store

from .const import (
    CLIENT_LEVELS,
    CONF_LIST_NETWORKS,
    DEFAULT_LIST_NETWORKS,
    DOMAIN,
    EXACT_ONLY_LISTS,
    LIST_TYPE_ALLOW,
    LIST_TYPE_DENY,
    LIST_UNFILTERED_EMPTY,
    MAX_BASE_GROUPS,
    MAX_CLIENTS,
    MAX_LIST_ENTRIES,
    REFRESH_DEBOUNCE_SECONDS,
    RULE_LISTS,
    SERVED_LISTS,
)
from .validation import (
    InvalidDomainError,
    InvalidGroupNameError,
    InvalidNetworkError,
    IPNetwork,
    address_in_networks,
    normalize_client,
    normalize_domain,
    parse_networks,
    validate_group_name,
)

if TYPE_CHECKING:
    from .coordinator import BlockyConfigEntry

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION: Final = 1
SAVE_DELAY_SECONDS: Final = 5
TOKEN_BYTES: Final = 32
MIN_TOKEN_LENGTH: Final = 40
_TOKEN_ALPHABET: Final = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


class ListError(Exception):
    """A list operation was refused."""


def storage_key(entry_id: str) -> str:
    """Return the store key of an entry's lists."""
    return f"{DOMAIN}.{entry_id}.lists"


def read_networks(options: Mapping[str, Any]) -> tuple[IPNetwork, ...]:
    """Read the networks allowed to fetch lists; invalid means none."""
    raw = options.get(CONF_LIST_NETWORKS, DEFAULT_LIST_NETWORKS)
    try:
        return parse_networks(raw)
    except InvalidNetworkError:
        _LOGGER.error(
            "Stored list client networks are invalid; serving lists to nobody"
        )
        return ()


def _new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def _valid_token(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) >= MIN_TOKEN_LENGTH
        and all(char in _TOKEN_ALPHABET for char in value)
    )


class ListManager:
    """Hold the manual lists of one config entry."""

    def __init__(self, hass: HomeAssistant, entry: BlockyConfigEntry) -> None:
        """Initialize from the entry options; entries are loaded later."""
        self._hass = hass
        self._entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry.entry_id)
        )
        self._networks = read_networks(entry.options)
        self._entries: dict[str, set[str]] = {name: set() for name in RULE_LISTS}
        # In memory only: the latest (revision, time) Blocky fetched, per list.
        self._fetched: dict[str, tuple[str, float]] = {}
        # What was last known to be applied: base groups and client levels.
        self._applied: dict[str, Any] | None = None
        self._token = _new_token()
        self._listeners: list[Callable[[], None]] = []
        self._cancel_refresh: CALLBACK_TYPE | None = None
        self._refresh: Callable[[], Any] | None = None

    # --- persistence --------------------------------------------------------

    async def async_load(self) -> None:
        """Load token and entries, validating everything that was stored."""
        stored = await self._store.async_load()
        dirty = True
        if isinstance(stored, dict):
            token = stored.get("token")
            if _valid_token(token):
                self._token = token
                dirty = False
            lists = stored.get("lists")
            if isinstance(lists, dict):
                for name in RULE_LISTS:
                    raw_entries = lists.get(name)
                    if not isinstance(raw_entries, list):
                        continue
                    for raw in raw_entries[:MAX_LIST_ENTRIES]:
                        try:
                            self._entries[name].add(
                                normalize_domain(
                                    raw, allow_wildcard=name not in EXACT_ONLY_LISTS
                                )
                            )
                        except InvalidDomainError:
                            dirty = True
                if set(lists) - set(RULE_LISTS):
                    # Entries of lists that no longer exist are dropped.
                    dirty = True
            self._applied = _read_applied(stored.get("applied"))
        if dirty:
            await self._store.async_save(self._data())

    def _data(self) -> dict[str, Any]:
        return {
            "token": self._token,
            "lists": {name: sorted(entries) for name, entries in self._entries.items()},
            "applied": self._applied,
        }

    def _changed(self) -> None:
        self._store.async_delay_save(self._data, SAVE_DELAY_SECONDS)
        for listener in list(self._listeners):
            listener()

    async def async_close(self) -> None:
        """Write pending changes and stop the pending refresh."""
        if self._cancel_refresh is not None:
            self._cancel_refresh()
            self._cancel_refresh = None
        await self._store.async_save(self._data())

    # --- reading ------------------------------------------------------------

    @property
    def token(self) -> str:
        """Return the secret path component of the list URLs."""
        return self._token

    def token_matches(self, candidate: str) -> bool:
        """Compare a presented token in constant time."""
        return hmac.compare_digest(candidate.encode(), self._token.encode())

    def client_allowed(self, address: object) -> bool:
        """Return whether a client address may fetch lists."""
        return address_in_networks(address, self._networks)

    def count(self, name: str) -> int:
        """Return the number of entries in a list."""
        return len(self._entries[name])

    def entries(self, name: str) -> list[str]:
        """Return the sorted entries of a list."""
        if name not in self._entries:
            raise ListError("unknown list")
        return sorted(self._entries[name])

    def render(self, name: str) -> str | None:
        """Return the list as Blocky reads it, or None for an unknown list.

        The list of the Unfiltered level is always served empty.
        """
        if name == LIST_UNFILTERED_EMPTY:
            return ""
        if name not in self._entries:
            return None
        return "".join(f"{entry}\n" for entry in sorted(self._entries[name]))

    def path(self, name: str) -> str:
        """Return the URL path Blocky fetches a list from."""
        return f"/api/{DOMAIN}/lists/{self._token}/{name}.txt"

    # --- what Blocky fetched, and what was applied ---------------------------

    def record_fetch(self, name: str, rev: str) -> None:
        """Remember that Blocky fetched ``name`` with revision ``rev``.

        Only the fixed served lists are recorded, one entry each; ``rev`` must
        already be validated by the caller.
        """
        if name in SERVED_LISTS:
            self._fetched[name] = (rev, time.time())

    def fetched(self, name: str) -> tuple[str, float] | None:
        """Return the latest (revision, time) Blocky fetched for a list."""
        return self._fetched.get(name)

    @property
    def applied(self) -> dict[str, Any] | None:
        """Return the base groups and client levels last known to be applied."""
        return self._applied

    def set_applied(self, snapshot: dict[str, Any]) -> None:
        """Remember what is applied now (saved with the next store write)."""
        if snapshot != self._applied:
            self._applied = snapshot
            self._store.async_delay_save(self._data, SAVE_DELAY_SECONDS)

    # --- changing -----------------------------------------------------------

    @staticmethod
    def _checked(name: object, expected_type: str | None) -> str:
        if not isinstance(name, str) or name not in RULE_LISTS:
            raise ListError("unknown list")
        if expected_type is not None and RULE_LISTS[name] != expected_type:
            raise ListError(f"list is not a {expected_type} list")
        return name

    @callback
    def async_add(self, name: object, domain: object, expected_type: str) -> str | None:
        """Add an entry; return it, or None when it was already present."""
        checked = self._checked(name, expected_type)
        try:
            entry = normalize_domain(
                domain, allow_wildcard=checked not in EXACT_ONLY_LISTS
            )
        except InvalidDomainError as err:
            raise ListError(f"invalid domain: {err}") from err
        entries = self._entries[checked]
        if entry in entries:
            return None
        if len(entries) >= MAX_LIST_ENTRIES:
            raise ListError("list is full")
        entries.add(entry)
        self._changed()
        self._schedule_refresh()
        return entry

    @callback
    def async_remove(self, name: object, domain: object) -> str | None:
        """Remove an entry; return it, or None when it was not present."""
        checked = self._checked(name, None)
        try:
            entry = normalize_domain(domain)
        except InvalidDomainError as err:
            raise ListError(f"invalid domain: {err}") from err
        entries = self._entries[checked]
        if entry not in entries:
            return None
        entries.remove(entry)
        self._changed()
        self._schedule_refresh()
        return entry

    async def async_rotate_token(self) -> None:
        """Replace the token; every list URL changes."""
        self._token = _new_token()
        await self._store.async_save(self._data())

    # --- side effects -------------------------------------------------------

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call ``listener`` after every change of an entry."""
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            self._listeners.remove(listener)

        return remove

    def set_refresh(self, refresh: Callable[[], Any]) -> None:
        """Set the coroutine function that makes Blocky reload its lists."""
        self._refresh = refresh

    @callback
    def _schedule_refresh(self) -> None:
        """Ask Blocky to reload, once, a little after the last change.

        A reload makes Blocky fetch every list again, including large remote
        ones, so a burst of changes must not cause a burst of reloads.
        """
        if self._refresh is None:
            return
        if self._cancel_refresh is not None:
            self._cancel_refresh()

        async def _run(_now: datetime) -> None:
            self._cancel_refresh = None
            if self._refresh is None:
                return
            try:
                await self._refresh()
            except Exception:
                _LOGGER.warning("Blocky did not reload its lists after a change")

        self._cancel_refresh = async_call_later(
            self._hass, REFRESH_DEBOUNCE_SECONDS, _run
        )


def _read_applied(raw: object) -> dict[str, Any] | None:
    """Validate a stored applied snapshot; anything off means unknown."""
    if not isinstance(raw, dict):
        return None
    groups = raw.get("base_groups")
    clients = raw.get("clients")
    if not isinstance(groups, list) or not isinstance(clients, dict):
        return None
    if len(groups) > MAX_BASE_GROUPS or len(clients) > MAX_CLIENTS:
        return None
    try:
        names = [validate_group_name(name) for name in groups]
    except InvalidGroupNameError:
        return None
    levels: dict[str, str] = {}
    for key, level in clients.items():
        address = normalize_client(key)
        if address is None or level not in CLIENT_LEVELS:
            return None
        levels[address] = level
    return {"base_groups": names, "clients": levels}


def find_list_body(
    managers: list[ListManager],
    remote: object,
    token: str,
    filename: str,
    rev: str | None = None,
) -> str | None:
    """Return the list a request is entitled to, or None.

    Every reason for refusal yields the same None, and every manager's token
    is compared, so a response does not reveal which check failed. ``rev`` is
    already validated (8 hex characters) or None; it is only recorded, after
    the request was found entitled, and never changes the body.
    """
    name = filename.removesuffix(".txt")
    name_ok = filename.endswith(".txt") and bool(name)
    body: str | None = None
    for manager in managers:
        token_ok = manager.token_matches(token)
        client_ok = manager.client_allowed(remote)
        if token_ok and client_ok and name_ok and body is None:
            body = manager.render(name)
            if body is not None and rev is not None:
                manager.record_fetch(name, rev)
    return body


__all__ = [
    "LIST_TYPE_ALLOW",
    "LIST_TYPE_DENY",
    "ListError",
    "ListManager",
    "find_list_body",
    "read_networks",
    "storage_key",
]
