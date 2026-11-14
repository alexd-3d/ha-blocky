"""Requests for new domains.

The clients of the Restricted and Lockdown levels are watched through the
query log. A domain a client asks for the first time becomes an event (unless
the level's notification is Off) and a request that an administrator approves,
rejects or blocks. For Lockdown clients an answer that got through although the
domain is on the lockdown allow list is reported as a leak.

Everything read from the log, the store and service calls is hostile: names go
through the exact-domain validator, client addresses must parse as IP
addresses, and every count is capped. A failing round is logged and counted;
it never reaches the statistics.
"""

from __future__ import annotations

import logging
import math
import re
import secrets
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Collection, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_ACTION,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DOMAIN,
    ATTR_LIST,
    BASELINE_WINDOW,
    DOMAIN,
    EVENT_LIST_CHANGED,
    EVENT_LOCKDOWN_LEAK,
    EVENT_NEW_DOMAIN,
    EVENT_NEW_DOMAINS_SUMMARY,
    EVENT_RATE_LIMIT,
    EVENT_RATE_WINDOW,
    EVENT_UNEXPECTED_DOMAIN,
    LEAK_WINDOW,
    LEVEL_LOCKDOWN,
    LEVEL_RESTRICTED,
    LIST_LOCKDOWN_ALLOW,
    LIST_RESTRICTED_DENY,
    LIST_TYPE_ALLOW,
    LIST_TYPE_DENY,
    MAX_BASELINE_CLIENTS_PER_ROUND,
    MAX_KNOWN_DOMAINS_SHOWN,
    MAX_KNOWN_PAIRS_PER_CLIENT,
    MAX_LEAKS_PER_CLIENT,
    MAX_PENDING_REQUESTS,
    MAX_REJECTED_PAIRS_PER_CLIENT,
    MAX_REQUEST_CLIENTS,
    REQUEST_ACTION_APPROVE,
    REQUEST_ACTION_BLOCK,
    REQUEST_ACTIONS,
    REQUEST_TTL,
    REQUEST_WINDOW_ROWS,
    TRACKED_LEVELS,
)
from .db import (
    CATEGORY_BLOCKED,
    CATEGORY_CACHED,
    CATEGORY_RESOLVED,
    BlockyDbError,
    LogRow,
    QueryLogDatabase,
    response_category,
)
from .levels import LevelConfig
from .lists import ListError, ListManager
from .validation import InvalidDomainError, normalize_client, normalize_domain

if TYPE_CHECKING:
    from .coordinator import BlockyConfigEntry

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION: Final = 1
SAVE_DELAY_SECONDS: Final = 300

KIND_LEARNING: Final = "learning"
KIND_APPROVAL: Final = "approval"
_KINDS: Final = (KIND_LEARNING, KIND_APPROVAL)
_ACTIONS_OF_KIND: Final = {
    KIND_LEARNING: ("block", "dismiss"),
    KIND_APPROVAL: ("approve", "reject"),
}

_REQUEST_ID_RE: Final = re.compile(r"[A-Za-z0-9_-]{16,64}")

# Reasons a request could not be resolved. Each one is also a key of the
# "exceptions" translations.
ERROR_MESSAGES: Final = {
    "request_not_found": (
        "The request does not exist, was already resolved or expired."
    ),
    "request_not_approvable": "Only a request of a Lockdown client can be approved.",
    "request_not_blockable": "Only a request of a Restricted client can be blocked.",
    "level_changed": "The level of this client has changed; the request was dropped.",
    "list_failed": "The list refused the entry, for example because it is full.",
    "invalid_client": "The client is not a valid IP address.",
    "client_not_lockdown": "The client is not at the Lockdown level.",
    "too_many_clients": "Too many clients are tracked already.",
    "client_not_tracked": "The client is not tracked.",
    "client_not_restricted": "The client is not at the Restricted level.",
    "invalid_domain": "The domain is not a valid name.",
    "domain_not_known": "The domain is not one of the known domains of the client.",
}


class RequestError(Exception):
    """An operation on a request was refused; ``code`` says why."""

    def __init__(self, code: str) -> None:
        """Remember the reason."""
        super().__init__(code)
        self.code = code

    @property
    def message(self) -> str:
        """Return a fixed English text that never contains log data."""
        return ERROR_MESSAGES.get(self.code, "The request could not be resolved.")


@dataclass(slots=True)
class Request:
    """One decision waiting for an administrator."""

    id: str
    client: str
    level: str
    domain: str
    kind: str
    created: float


@dataclass(slots=True)
class ClientState:
    """What is known about one client of a tracked level."""

    level: str
    last_seen: float
    known: OrderedDict[str, None] = field(default_factory=OrderedDict)
    rejected: OrderedDict[str, None] = field(default_factory=OrderedDict)
    leaks: dict[str, float] = field(default_factory=dict)
    # Not stored: recent event times and the events held back since.
    events: deque[float] = field(default_factory=deque)
    suppressed: int = 0
    suppressed_since: float = 0.0
    # Restricted clients: whether the client's recent history was taken as known.
    baselined: bool = True


@dataclass(slots=True)
class Counters:
    """Counts of what was skipped or went wrong; nothing here is stored."""

    rows_read: int = 0
    skipped_other_level: int = 0
    invalid_domains: int = 0
    invalid_clients: int = 0
    pending_cap_hits: int = 0
    clients_refused: int = 0
    events_suppressed: int = 0
    failures: int = 0


def domain_is_covered(domain: str, entries: Collection[str]) -> bool:
    """Return whether an entry equals the domain or one of its parents.

    Matching is on label boundaries: ``example.com`` covers ``a.example.com``
    but not ``badexample.com``. A wildcard entry ``*.example.com`` covers the
    subdomains of ``example.com`` but not the apex ``example.com`` itself.
    Not verified against Blocky's own matching.
    """
    entry_set = entries if isinstance(entries, (set, frozenset)) else set(entries)
    labels = domain.split(".")
    for index in range(len(labels)):
        suffix = ".".join(labels[index:])
        if suffix in entry_set or (index > 0 and f"*.{suffix}" in entry_set):
            return True
    return False


def _utc_timestamp(value: datetime) -> float:
    return value.replace(tzinfo=UTC).timestamp()


def _load_domains(raw: object, limit: int) -> OrderedDict[str, None]:
    """Read a stored list of domains, oldest first, validating each."""
    domains: OrderedDict[str, None] = OrderedDict()
    if not isinstance(raw, list):
        return domains
    for item in raw[-limit:]:
        try:
            domains[normalize_domain(item, allow_wildcard=False)] = None
        except InvalidDomainError:
            continue
    return domains


def _as_time(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


class RequestTracker:
    """Find new domains in the query log and manage the resulting requests."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: BlockyConfigEntry,
        database: QueryLogDatabase,
        levels: LevelConfig,
        lists: ListManager,
        *,
        report_existing: bool = False,
        client_names: Callable[[], Mapping[str, str]] | None = None,
    ) -> None:
        """Initialize empty; state is loaded later."""
        self._hass = hass
        self._entry_id = entry.entry_id
        self._database = database
        self._levels = levels
        self._lists = lists
        self._report_existing = report_existing
        self._client_names = client_names or dict
        # Address -> name, rebuilt once per round and per answer.
        self._names: Mapping[str, str] = {}
        self.baseline_seconds: float | None = None
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry.entry_id)
        )
        self._cursor: int | None = None
        self._clients: dict[str, ClientState] = {}
        self._requests: dict[str, Request] = {}
        self._pending: dict[tuple[str, str], str] = {}
        self._allow_cache: frozenset[str] | bool | None = False
        self._listeners: list[Callable[[], None]] = []
        self.counters = Counters()

    # --- persistence --------------------------------------------------------

    async def async_load(self) -> None:
        """Restore the saved state, validating everything that was stored."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        cursor = stored.get("cursor")
        if isinstance(cursor, int) and not isinstance(cursor, bool) and cursor >= 0:
            self._cursor = cursor
        clients = stored.get("clients")
        if isinstance(clients, dict):
            for raw_address, raw in list(clients.items())[:MAX_REQUEST_CLIENTS]:
                self._load_client(raw_address, raw)
        requests = stored.get("requests")
        if isinstance(requests, list):
            for raw_request in requests[:MAX_PENDING_REQUESTS]:
                self._load_request(raw_request)

    def _load_client(self, raw_address: object, raw: object) -> None:
        address = normalize_client(raw_address)
        if address is None or not isinstance(raw, dict) or address in self._clients:
            return
        config = self._levels.clients.get(address)
        last_seen = _as_time(raw.get("last_seen"))
        if (
            config is None
            or config.level not in TRACKED_LEVELS
            or raw.get("level") != config.level
            or last_seen is None
        ):
            return
        leaks: dict[str, float] = {}
        raw_leaks = raw.get("leaks")
        if isinstance(raw_leaks, dict) and config.level == LEVEL_LOCKDOWN:
            for name, seen in list(raw_leaks.items())[-MAX_LEAKS_PER_CLIENT:]:
                moment = _as_time(seen)
                try:
                    leaks[normalize_domain(name, allow_wildcard=False)] = moment or 0.0
                except InvalidDomainError:
                    continue
        self._clients[address] = ClientState(
            baselined=(
                raw.get("baselined") is True
                or config.level != LEVEL_RESTRICTED
                or self._report_existing
            ),
            level=config.level,
            last_seen=last_seen,
            known=_load_domains(raw.get("known"), MAX_KNOWN_PAIRS_PER_CLIENT),
            rejected=_load_domains(raw.get("rejected"), MAX_REJECTED_PAIRS_PER_CLIENT),
            leaks=leaks,
        )

    def _load_request(self, raw: object) -> None:
        if not isinstance(raw, dict):
            return
        request_id = raw.get("id")
        address = normalize_client(raw.get("client"))
        created = _as_time(raw.get("created"))
        kind = raw.get("kind")
        state = self._clients.get(address) if address else None
        if (
            not isinstance(request_id, str)
            or _REQUEST_ID_RE.fullmatch(request_id) is None
            or request_id in self._requests
            or address is None
            or state is None
            or created is None
            or kind not in _KINDS
            or kind != _kind_of_level(state.level)
        ):
            return
        try:
            domain = normalize_domain(raw.get("domain"), allow_wildcard=False)
        except InvalidDomainError:
            return
        if (address, domain) in self._pending:
            return
        self._requests[request_id] = Request(
            request_id, address, state.level, domain, kind, created
        )
        self._pending[(address, domain)] = request_id

    def _stored(self) -> dict[str, Any]:
        return {
            "cursor": self._cursor,
            "clients": {
                address: {
                    "level": state.level,
                    "last_seen": state.last_seen,
                    "baselined": state.baselined,
                    "known": list(state.known),
                    "rejected": list(state.rejected),
                    "leaks": dict(state.leaks),
                }
                for address, state in self._clients.items()
            },
            "requests": [
                {
                    "id": request.id,
                    "client": request.client,
                    "domain": request.domain,
                    "kind": request.kind,
                    "created": request.created,
                }
                for request in self._requests.values()
            ],
        }

    def _save_later(self) -> None:
        self._store.async_delay_save(self._stored, SAVE_DELAY_SECONDS)

    async def async_close(self) -> None:
        """Write the state now."""
        await self._store.async_save(self._stored())

    # --- listeners ----------------------------------------------------------

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call ``listener`` whenever requests or leaks may have changed."""
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            self._listeners.remove(listener)

        return remove

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # --- reading ------------------------------------------------------------

    @property
    def pending_count(self) -> int:
        """Return the number of requests waiting for a decision."""
        return len(self._requests)

    def leak_count(self, now: float | None = None) -> int:
        """Return how many (client, domain) leaks were seen in the last hour."""
        moment = dt_util.utcnow().timestamp() if now is None else now
        horizon = moment - LEAK_WINDOW.total_seconds()
        return sum(
            1
            for state in self._clients.values()
            for seen in state.leaks.values()
            if seen >= horizon
        )

    def describe_requests(self) -> list[dict[str, Any]]:
        """Return the pending requests as plain data, oldest first."""
        names = self._client_names()
        return [
            {
                "id": request.id,
                "level": request.level,
                "client": request.client,
                "client_name": names.get(request.client),
                "domain": request.domain,
                "kind": request.kind,
                "actions": list(_ACTIONS_OF_KIND[request.kind]),
                "created": datetime.fromtimestamp(request.created, UTC).isoformat(),
                "expires": datetime.fromtimestamp(
                    request.created + REQUEST_TTL.total_seconds(), UTC
                ).isoformat(),
            }
            for request in self._requests.values()
        ]

    def describe_tracked(self) -> list[dict[str, Any]]:
        """Return every tracked client with its level and known count."""
        names = self._client_names()
        return [
            {
                "client": address,
                "client_name": names.get(address),
                "level": state.level,
                "known": len(state.known),
            }
            for address, state in self._clients.items()
        ]

    def describe_known(self, client: object) -> dict[str, Any]:
        """Return the known domains of one tracked client, newest first.

        At most ``MAX_KNOWN_DOMAINS_SHOWN`` are listed; each is validated again.
        """
        address = normalize_client(client)
        if address is None:
            raise RequestError("invalid_client")
        state = self._clients.get(address)
        if state is None:
            raise RequestError("client_not_tracked")
        domains: list[str] = []
        for known in reversed(state.known):
            if len(domains) >= MAX_KNOWN_DOMAINS_SHOWN:
                break
            try:
                domains.append(normalize_domain(known, allow_wildcard=False))
            except InvalidDomainError:
                continue
        return {
            "client": address,
            "client_name": self._client_names().get(address),
            "level": state.level,
            "total": len(state.known),
            "domains": domains,
        }

    def diagnostics(self) -> dict[str, Any]:
        """Return counts only; no address, no name and no domain."""
        return {
            "baseline_last_duration_ms": (
                None
                if self.baseline_seconds is None
                else round(self.baseline_seconds * 1000, 1)
            ),
            "clients": len(self._clients),
            "pending_requests": len(self._requests),
            "known_pairs": sum(len(state.known) for state in self._clients.values()),
            "rejected_pairs": sum(
                len(state.rejected) for state in self._clients.values()
            ),
            "leaks_last_hour": self.leak_count(),
            "has_cursor": self._cursor is not None,
            "counters": asdict(self.counters),
        }

    # --- the statistics round -----------------------------------------------

    async def async_round(self) -> None:
        """Read the next window of the log and act on it. Never raises."""
        try:
            cursor, rows = await self._hass.async_add_executor_job(
                self._read, self._cursor
            )
            # At most once: a row that breaks processing must not be read
            # again every round.
            self._cursor = cursor
            now = dt_util.utcnow().timestamp()
            self._allow_cache = False
            self._process(rows, now)
            await self._async_baseline()
            self._housekeeping(now)
            if rows:
                self._save_later()
        except BlockyDbError as err:
            self.counters.failures += 1
            _LOGGER.warning("New-domain tracking could not read the log: %s", err)
        except Exception as err:
            self.counters.failures += 1
            _LOGGER.warning("New-domain tracking failed: %s", type(err).__name__)
        self._notify()

    def _read(self, cursor: int | None) -> tuple[int, list[LogRow]]:
        """Read one window. Executor only."""
        if cursor is None:
            cursor = max(0, self._database.max_id() - REQUEST_WINDOW_ROWS)
        rows = self._database.rows_after(cursor, REQUEST_WINDOW_ROWS)
        if rows:
            return rows[-1].id, rows
        max_id = self._database.max_id()
        if max_id < cursor:
            # The table was emptied or replaced; start over from its end.
            return max(0, max_id - REQUEST_WINDOW_ROWS), []
        return cursor, []

    async def _async_baseline(self) -> None:
        """Take the recent history of new learning clients as known.

        At most a few clients per round; the others wait, and their rows are
        recorded as known without a report meanwhile. A failure is counted and
        the client is tried again next round.
        """
        waiting = [
            address
            for address, state in self._clients.items()
            if not state.baselined and state.level == LEVEL_RESTRICTED
        ][:MAX_BASELINE_CLIENTS_PER_ROUND]
        if not waiting:
            return
        since = (dt_util.utcnow() - BASELINE_WINDOW).replace(tzinfo=None)
        started = time.monotonic()
        try:
            found = await self._hass.async_add_executor_job(
                self._read_baselines, waiting, since
            )
        except BlockyDbError as err:
            self.baseline_seconds = time.monotonic() - started
            self.counters.failures += 1
            _LOGGER.warning("New-domain baseline could not read the log: %s", err)
            return
        self.baseline_seconds = time.monotonic() - started
        for address, names in found.items():
            state = self._clients.get(address)
            if state is None or state.baselined:
                continue
            for name in names:
                try:
                    self._remember(state, normalize_domain(name, allow_wildcard=False))
                except InvalidDomainError:
                    self.counters.invalid_domains += 1
            state.baselined = True
        self._save_later()

    def _read_baselines(
        self, addresses: list[str], since: datetime
    ) -> dict[str, list[str | None]]:
        """Read each client's recent distinct names. Executor only."""
        return {
            address: self._database.client_domains(
                address, since, MAX_KNOWN_PAIRS_PER_CLIENT
            )
            for address in addresses
        }

    def _process(self, rows: list[LogRow], now: float) -> None:
        self._names = self._client_names()
        for row in rows:
            self.counters.rows_read += 1
            client = normalize_client(row.client)
            if client is None:
                self.counters.invalid_clients += 1
                continue
            config = self._levels.clients.get(client)
            if config is None or config.level not in TRACKED_LEVELS:
                self.counters.skipped_other_level += 1
                continue
            try:
                domain = normalize_domain(row.domain, allow_wildcard=False)
            except InvalidDomainError:
                self.counters.invalid_domains += 1
                continue
            state = self._client(client, config.level, now)
            if state is None:
                continue
            if config.level == LEVEL_RESTRICTED:
                self._restricted_row(state, client, domain, now)
            else:
                self._lockdown_row(state, client, config.ask, domain, row, now)

    def _restricted_row(
        self, state: ClientState, client: str, domain: str, now: float
    ) -> None:
        if domain in state.known:
            state.known.move_to_end(domain)
            return
        if not state.baselined:
            # Waiting for the baseline: never report these as new.
            self._remember(state, domain)
            return
        if (client, domain) in self._pending:
            return
        request = self._create_request(state, client, domain, KIND_LEARNING, now)
        if request is not None:
            self._emit(EVENT_NEW_DOMAIN, state, client, domain, request, now)

    def _lockdown_row(
        self,
        state: ClientState,
        client: str,
        ask: bool,
        domain: str,
        row: LogRow,
        now: float,
    ) -> None:
        category = response_category(row.response_type)
        if category in (CATEGORY_RESOLVED, CATEGORY_CACHED):
            self._leak_row(state, client, domain, row, now)
            return
        if category != CATEGORY_BLOCKED:
            return
        if domain in state.known:
            state.known.move_to_end(domain)
            return
        if not ask:
            self._remember(state, domain)
            self._emit(EVENT_UNEXPECTED_DOMAIN, state, client, domain, None, now)
            return
        if domain in state.rejected or (client, domain) in self._pending:
            return
        request = self._create_request(state, client, domain, KIND_APPROVAL, now)
        if request is not None:
            self._emit(EVENT_NEW_DOMAIN, state, client, domain, request, now)

    def _leak_row(
        self,
        state: ClientState,
        client: str,
        domain: str,
        row: LogRow,
        now: float,
    ) -> None:
        horizon = now - LEAK_WINDOW.total_seconds()
        if row.requested is not None and _utc_timestamp(row.requested) < horizon:
            return
        entries = self._allow_entries()
        if domain_is_covered(domain, entries):
            return
        previous = state.leaks.pop(domain, None)
        state.leaks[domain] = now
        while len(state.leaks) > MAX_LEAKS_PER_CLIENT:
            del state.leaks[next(iter(state.leaks))]
        if previous is None or previous < horizon:
            self._emit(EVENT_LOCKDOWN_LEAK, state, client, domain, None, now)

    def _allow_entries(self) -> frozenset[str]:
        """Return the allowed domains of the Lockdown level (one round cached)."""
        if self._allow_cache is False:
            self._allow_cache = frozenset(self._lists.entries(LIST_LOCKDOWN_ALLOW))
        return self._allow_cache  # type: ignore[return-value]

    # --- state ----------------------------------------------------------------

    def _client(self, address: str, level: str, now: float) -> ClientState | None:
        """Return the client's state, creating it; None when at the cap."""
        state = self._clients.get(address)
        if state is not None and state.level != level:
            self._drop_client(address)
            state = None
        if state is None:
            if len(self._clients) >= MAX_REQUEST_CLIENTS and not self._make_room():
                self.counters.clients_refused += 1
                return None
            state = ClientState(
                level=level,
                last_seen=now,
                baselined=level != LEVEL_RESTRICTED or self._report_existing,
            )
            self._clients[address] = state
        state.last_seen = now
        return state

    def _make_room(self) -> bool:
        """Drop the least recently seen client without pending requests."""
        busy = {request.client for request in self._requests.values()}
        idle = [
            (state.last_seen, address)
            for address, state in self._clients.items()
            if address not in busy
        ]
        if not idle:
            return False
        self._drop_client(min(idle)[1])
        return True

    def _drop_client(self, address: str) -> None:
        self._clients.pop(address, None)
        for request in [r for r in self._requests.values() if r.client == address]:
            self._drop_request(request)

    def _drop_request(self, request: Request) -> None:
        self._requests.pop(request.id, None)
        self._pending.pop((request.client, request.domain), None)

    @staticmethod
    def _remember(state: ClientState, domain: str) -> None:
        state.known[domain] = None
        state.known.move_to_end(domain)
        while len(state.known) > MAX_KNOWN_PAIRS_PER_CLIENT:
            state.known.popitem(last=False)

    @staticmethod
    def _reject_pair(state: ClientState, domain: str) -> None:
        state.rejected[domain] = None
        state.rejected.move_to_end(domain)
        while len(state.rejected) > MAX_REJECTED_PAIRS_PER_CLIENT:
            state.rejected.popitem(last=False)

    def _create_request(
        self, state: ClientState, client: str, domain: str, kind: str, now: float
    ) -> Request | None:
        if len(self._requests) >= MAX_PENDING_REQUESTS:
            self.counters.pending_cap_hits += 1
            return None
        request = Request(
            id=secrets.token_urlsafe(16),
            client=client,
            level=state.level,
            domain=domain,
            kind=kind,
            created=now,
        )
        self._requests[request.id] = request
        self._pending[(client, domain)] = request.id
        return request

    def _housekeeping(self, now: float) -> None:
        """Expire requests and leaks, report held-back events, drop stale clients."""
        for address in [
            address
            for address, state in self._clients.items()
            if self._levels.level_of(address) != state.level
        ]:
            self._drop_client(address)

        ttl = REQUEST_TTL.total_seconds()
        for request in [r for r in self._requests.values() if now - r.created >= ttl]:
            self._expire(request)

        horizon = now - LEAK_WINDOW.total_seconds()
        window = EVENT_RATE_WINDOW.total_seconds()
        for state in self._clients.values():
            for name in [d for d, seen in state.leaks.items() if seen < horizon]:
                del state.leaks[name]
        for address, state in self._clients.items():
            if state.suppressed and now - state.suppressed_since >= window:
                self._hass.bus.async_fire(
                    EVENT_NEW_DOMAINS_SUMMARY,
                    {
                        ATTR_CONFIG_ENTRY_ID: self._entry_id,
                        "level": state.level,
                        "client": address,
                        "client_name": self._names.get(address),
                        "suppressed": state.suppressed,
                    },
                )
                state.suppressed = 0

    def _expire(self, request: Request) -> None:
        """Drop a request nobody answered. Restricted clients stop being asked
        about the pair; Lockdown clients are asked again when it is blocked again."""
        self._drop_request(request)
        state = self._clients.get(request.client)
        if state is not None and request.kind == KIND_LEARNING:
            self._remember(state, request.domain)

    # --- events ---------------------------------------------------------------

    def _emit(
        self,
        event: str,
        state: ClientState,
        client: str,
        domain: str,
        request: Request | None,
        now: float,
    ) -> None:
        """Fire a per-domain event unless the client reached its rate limit.

        A level whose notification is Off fires no new-domain or
        unexpected-domain event (requests are still created). A leak is
        always reported.
        """
        if event != EVENT_LOCKDOWN_LEAK and not self._levels.notify.get(
            state.level, False
        ):
            return
        window = EVENT_RATE_WINDOW.total_seconds()
        while state.events and now - state.events[0] >= window:
            state.events.popleft()
        if len(state.events) >= EVENT_RATE_LIMIT:
            if state.suppressed == 0:
                state.suppressed_since = now
            state.suppressed += 1
            self.counters.events_suppressed += 1
            return
        state.events.append(now)
        self._hass.bus.async_fire(
            event,
            {
                ATTR_CONFIG_ENTRY_ID: self._entry_id,
                "level": state.level,
                "client": client,
                "client_name": self._names.get(client),
                ATTR_DOMAIN: domain,
                "request_id": request.id if request else None,
                "actions": list(_ACTIONS_OF_KIND[request.kind]) if request else [],
            },
        )

    def _fire_list_changed(
        self, list_name: str, domain: str, context: Context | None
    ) -> None:
        self._hass.bus.async_fire(
            EVENT_LIST_CHANGED,
            {
                ATTR_CONFIG_ENTRY_ID: self._entry_id,
                ATTR_ACTION: "add",
                ATTR_LIST: list_name,
                ATTR_DOMAIN: domain,
            },
            context=context,
        )

    # --- decisions --------------------------------------------------------------

    def _active(self, request_id: object) -> Request:
        """Return a live request by exact id or raise; expired ones are dropped."""
        request = (
            self._requests.get(request_id) if isinstance(request_id, str) else None
        )
        if request is None:
            raise RequestError("request_not_found")
        if dt_util.utcnow().timestamp() - request.created >= (
            REQUEST_TTL.total_seconds()
        ):
            self._expire(request)
            self._changed()
            raise RequestError("request_not_found")
        return request

    def _level_ok(self, request: Request, level: str) -> None:
        state = self._clients.get(request.client)
        if (
            state is None
            or state.level != level
            or self._levels.level_of(request.client) != level
        ):
            self._drop_request(request)
            self._changed()
            raise RequestError("level_changed")

    def _changed(self) -> None:
        self._save_later()
        self._notify()

    @callback
    def async_resolve(
        self,
        request_id: object,
        action: str,
        context: Context | None = None,
    ) -> Request:
        """Carry out a decision; the request is single use.

        ``approve`` adds the domain to the Lockdown allow list, ``block`` adds
        it to the Restricted block list, ``reject`` closes the request (a
        Restricted request calls this dismiss).
        """
        if action not in REQUEST_ACTIONS:
            raise RequestError("request_not_found")
        request = self._active(request_id)
        state = self._clients.get(request.client)

        if action == REQUEST_ACTION_APPROVE:
            if request.kind != KIND_APPROVAL:
                raise RequestError("request_not_approvable")
            self._level_ok(request, LEVEL_LOCKDOWN)
            self._add_to_list(
                LIST_LOCKDOWN_ALLOW, request.domain, LIST_TYPE_ALLOW, context
            )
            if state is not None:
                self._remember(state, request.domain)
        elif action == REQUEST_ACTION_BLOCK:
            if request.kind != KIND_LEARNING:
                raise RequestError("request_not_blockable")
            self._level_ok(request, LEVEL_RESTRICTED)
            self._add_to_list(
                LIST_RESTRICTED_DENY, request.domain, LIST_TYPE_DENY, context
            )
            if state is not None:
                self._remember(state, request.domain)
        elif state is not None:
            if request.kind == KIND_LEARNING:
                self._remember(state, request.domain)
            else:
                self._reject_pair(state, request.domain)

        self._drop_request(request)
        self._changed()
        return request

    @callback
    def async_block_known(
        self, client: object, domain: object, context: Context | None = None
    ) -> str:
        """Block a known domain of a Restricted client.

        The domain goes to the Restricted block list, as when a request of a
        Restricted client is blocked. Lockdown clients are refused: their known
        domains are on the allow list, which this does not edit. Returns the
        canonical domain.
        """
        address = normalize_client(client)
        if address is None:
            raise RequestError("invalid_client")
        try:
            name = normalize_domain(domain, allow_wildcard=False)
        except InvalidDomainError as err:
            raise RequestError("invalid_domain") from err
        state = self._clients.get(address)
        if state is None:
            raise RequestError("client_not_tracked")
        if state.level != LEVEL_RESTRICTED:
            raise RequestError("client_not_restricted")
        if self._levels.level_of(address) != LEVEL_RESTRICTED:
            raise RequestError("level_changed")
        if name not in state.known:
            raise RequestError("domain_not_known")
        self._add_to_list(LIST_RESTRICTED_DENY, name, LIST_TYPE_DENY, context)
        self._remember(state, name)
        self._changed()
        return name

    def _add_to_list(
        self, name: str, domain: str, list_type: str, context: Context | None
    ) -> None:
        try:
            added = self._lists.async_add(name, domain, list_type)
        except ListError as err:
            raise RequestError("list_failed") from err
        if added is not None:
            self._fire_list_changed(name, added, context)

    @callback
    def async_set_client_ask(self, client: object, ask: bool) -> None:
        """Check that a client may have its ask switch set (Lockdown only).

        The switch itself is the ``ask`` of the client in the options; the
        caller writes it. Raises RequestError when the client is not a
        Lockdown client.
        """
        address = normalize_client(client)
        if address is None:
            raise RequestError("invalid_client")
        if self._levels.level_of(address) != LEVEL_LOCKDOWN or not isinstance(
            ask, bool
        ):
            raise RequestError("client_not_lockdown")


def _kind_of_level(level: str) -> str:
    return KIND_LEARNING if level == LEVEL_RESTRICTED else KIND_APPROVAL


def storage_key(entry_id: str) -> str:
    """Return the store key of an entry's request state."""
    return f"{DOMAIN}.{entry_id}.requests"


__all__ = [
    "KIND_APPROVAL",
    "KIND_LEARNING",
    "RequestError",
    "RequestTracker",
    "domain_is_covered",
    "storage_key",
]
