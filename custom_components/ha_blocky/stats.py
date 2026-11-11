"""Query log statistics for the Blocky DNS integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import CONF_STATS_INTERVAL, CONF_TOPS_INTERVAL, DOMAIN, STATS_WINDOW
from .db import BlockyDbError, QueryLogDatabase, Summary, TopItem
from .intervals import interval

if TYPE_CHECKING:
    from .coordinator import BlockyConfigEntry

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
SAVE_DELAY_SECONDS = 60


@dataclass(frozen=True, slots=True)
class QueryStats:
    """What the statistics sensors show."""

    queries_total: int
    blocked_total: int
    summary: Summary
    top_domains: tuple[TopItem, ...]
    top_blocked_domains: tuple[TopItem, ...]
    top_clients: tuple[TopItem, ...]


@dataclass(slots=True)
class _Collected:
    """Raw results of one database round, gathered in the executor."""

    max_id: int
    cursor_reset: bool
    new_queries: int
    new_blocked: int
    summary: Summary
    tops: tuple[list[TopItem], list[TopItem], list[TopItem]] | None


def _as_count(value: Any) -> int:
    """Read a stored counter defensively: the store is not trusted either."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


class BlockyStatsCoordinator(DataUpdateCoordinator[QueryStats]):
    """Turn the query log into counters, a 24 hour summary and top lists.

    The running totals are kept by reading only rows added since the last
    poll, so Blocky's retention clean-up never makes them go backwards.
    """

    config_entry: BlockyConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: BlockyConfigEntry, database: QueryLogDatabase
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_stats",
            update_interval=interval(entry.options, CONF_STATS_INTERVAL),
        )
        self.database = database
        self.tops_interval = interval(entry.options, CONF_TOPS_INTERVAL)
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.stats"
        )
        self._last_id: int | None = None
        self._queries_total = 0
        self._blocked_total = 0
        self._tops: tuple[list[TopItem], list[TopItem], list[TopItem]] = ([], [], [])
        self._tops_at: datetime | None = None

    async def async_load(self) -> None:
        """Restore the cursor and totals saved before the last shutdown."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        last_id = stored.get("last_id")
        if isinstance(last_id, int) and not isinstance(last_id, bool) and last_id >= 0:
            self._last_id = last_id
        self._queries_total = _as_count(stored.get("queries_total"))
        self._blocked_total = _as_count(stored.get("blocked_total"))

    def _stored(self) -> dict[str, Any]:
        return {
            "last_id": self._last_id,
            "queries_total": self._queries_total,
            "blocked_total": self._blocked_total,
        }

    async def async_save(self) -> None:
        """Write the cursor and totals now."""
        await self._store.async_save(self._stored())

    async def async_remove_store(self) -> None:
        """Delete the saved cursor and totals."""
        await self._store.async_remove()

    def _collect(self, last_id: int | None, with_tops: bool) -> _Collected:
        """Run all queries of one round. Executor only."""
        since = (dt_util.utcnow() - STATS_WINDOW).replace(tzinfo=None)
        max_id = self.database.max_id()

        cursor_reset = last_id is None or max_id < last_id
        if cursor_reset:
            # First run, or the table was emptied or replaced: start counting
            # from here instead of adding the whole table to the totals.
            new_queries = new_blocked = 0
        else:
            counts = self.database.counts_since(last_id)
            max_id = max(max_id, counts.max_id)
            new_queries, new_blocked = counts.queries, counts.blocked

        tops = None
        if with_tops:
            tops = (
                self.database.top_domains(since),
                self.database.top_blocked_domains(since),
                self.database.top_clients(since),
            )
        return _Collected(
            max_id=max_id,
            cursor_reset=cursor_reset,
            new_queries=new_queries,
            new_blocked=new_blocked,
            summary=self.database.summary(since),
            tops=tops,
        )

    async def _async_update_data(self) -> QueryStats:
        now = dt_util.utcnow()
        with_tops = self._tops_at is None or now - self._tops_at >= self.tops_interval
        try:
            collected = await self.hass.async_add_executor_job(
                self._collect, self._last_id, with_tops
            )
        except BlockyDbError as err:
            raise UpdateFailed(f"query log database: {err}") from err

        self._last_id = collected.max_id
        self._queries_total += collected.new_queries
        self._blocked_total += collected.new_blocked
        if collected.tops is not None:
            self._tops = collected.tops
            self._tops_at = now
        self._store.async_delay_save(self._stored, SAVE_DELAY_SECONDS)

        return QueryStats(
            queries_total=self._queries_total,
            blocked_total=self._blocked_total,
            summary=collected.summary,
            top_domains=tuple(self._tops[0]),
            top_blocked_domains=tuple(self._tops[1]),
            top_clients=tuple(self._tops[2]),
        )

    async def async_close(self) -> None:
        """Save state and close the database."""
        await self.async_save()
        await self.hass.async_add_executor_job(self.database.close)


def blocked_ratio(summary: Summary) -> float | None:
    """Return the share of blocked queries in percent."""
    if summary.queries <= 0:
        return None
    return round(100 * summary.blocked / summary.queries, 1)
