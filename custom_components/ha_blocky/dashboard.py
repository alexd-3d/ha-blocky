"""Data of the dashboard tab: the time window, the buckets and a short cache.

The query log is aggregated in the database (GROUP BY, bounded by the time
window); no log rows are read. Hourly counts are folded into local days in
Python, so a day always starts at local midnight, also across a change of
summer time. One answer is reused for a short time, so that several open cards
do not multiply the load on the database.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    DASHBOARD_CACHE,
    DASHBOARD_CACHE_LONG,
    DASHBOARD_STALE_MAX,
    DOMAIN,
)
from .db import CATEGORIES, BlockyDbError, QueryLogDatabase

if TYPE_CHECKING:
    from .coordinator import BlockyData

_LOGGER = logging.getLogger(__name__)

PERIOD_TODAY: Final = "today"
PERIOD_24H: Final = "24h"
PERIOD_7D: Final = "7d"
PERIOD_30D: Final = "30d"
_DAYS: Final = {PERIOD_7D: 7, PERIOD_30D: 30}
_HOUR: Final = timedelta(hours=1)
# Today always has 24 slots: the hours still to come stay empty.
TODAY_SLOTS: Final = 24
UNIT_HOUR: Final = "hour"
UNIT_DAY: Final = "day"


@dataclass(frozen=True, slots=True)
class Window:
    """A time window and its buckets; every time is aware UTC."""

    since: datetime
    until: datetime
    unit: str
    starts: tuple[datetime, ...]


def _hour_floor(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def _local_day_start(moment: datetime) -> datetime:
    return dt_util.as_utc(dt_util.start_of_local_day(dt_util.as_local(moment).date()))


def build_window(period: str, now: datetime) -> Window:
    """Return the window of a period.

    For 24 h, 7 d and 30 d the last bucket holds ``now``. Today is padded with
    empty buckets for the hours to come, so that it always has 24 slots (more
    on a day with 25 hours); ``until`` still ends at the current hour.
    """
    now = dt_util.as_utc(now)
    if period in (PERIOD_TODAY, PERIOD_24H):
        until = _hour_floor(now) + _HOUR
        if period == PERIOD_TODAY:
            first = _hour_floor(_local_day_start(now))
        else:
            first = until - 24 * _HOUR
        count = round((until - first) / _HOUR)
        if period == PERIOD_TODAY:
            count = max(count, TODAY_SLOTS)
        starts = tuple(first + index * _HOUR for index in range(count))
        since = _local_day_start(now) if period == PERIOD_TODAY else first
        return Window(since, until, UNIT_HOUR, starts)
    days = _DAYS[period]
    today = dt_util.as_local(now).date()
    starts = tuple(
        dt_util.as_utc(dt_util.start_of_local_day(today - timedelta(days=back)))
        for back in range(days - 1, -1, -1)
    )
    until = dt_util.as_utc(dt_util.start_of_local_day(today + timedelta(days=1)))
    return Window(starts[0], until, UNIT_DAY, starts)


def _naive(moment: datetime) -> datetime:
    return dt_util.as_utc(moment).replace(tzinfo=None)


def _iso(moment: datetime) -> str:
    return dt_util.as_utc(moment).isoformat(timespec="seconds")


def collect(
    database: QueryLogDatabase, window: Window, period: str, rows: int
) -> dict[str, Any]:
    """Run the dashboard queries. Executor only."""
    started = time.perf_counter()
    result = _collect(database, window, period, rows)
    _LOGGER.debug(
        "dashboard round for %s: %d ms",
        period,
        round((time.perf_counter() - started) * 1000),
    )
    return result


def _collect(
    database: QueryLogDatabase, window: Window, period: str, rows: int
) -> dict[str, Any]:
    since, until = _naive(window.since), _naive(window.until)
    unique_domains, average = database.dashboard_domains(since, until)

    buckets = {start: dict.fromkeys(CATEGORIES, 0) for start in window.starts}
    categories = dict.fromkeys(CATEGORIES, 0)
    for hour, category, count in database.dashboard_hours(since, until):
        categories[category] += count
        stamp = hour.replace(tzinfo=dt_util.UTC)
        key = (
            max(_local_day_start(stamp), window.starts[0])
            if window.unit == UNIT_DAY
            else stamp
        )
        bucket = buckets.get(key)
        if bucket is not None:
            bucket[category] += count

    return {
        "state": "ok",
        "period": period,
        "rows": rows,
        "since": _iso(window.since),
        "until": _iso(window.until),
        "totals": {
            "queries": sum(categories.values()),
            "unique_domains": unique_domains,
            "avg_duration_ms": round(average, 1) if average is not None else None,
            "categories": categories,
        },
        "buckets": {
            "unit": window.unit,
            "items": [
                {"start": _iso(start), "categories": counts}
                for start, counts in buckets.items()
            ],
        },
        "top_clients": database.dashboard_top("client", since, until, rows),
        "top_domains": database.dashboard_top("domain", since, until, rows),
        "top_blocked": database.dashboard_top(
            "domain", since, until, rows, blocked_only=True, with_reason=True
        ),
    }


def _fresh_for(period: str) -> timedelta:
    return DASHBOARD_CACHE_LONG if period in _DAYS else DASHBOARD_CACHE


async def _round(
    hass: HomeAssistant,
    data: BlockyData,
    database: QueryLogDatabase,
    period: str,
    rows: int,
) -> dict[str, Any]:
    """Run one database round and cache its answer. The caller holds the lock."""
    now = dt_util.utcnow()
    result = await hass.async_add_executor_job(
        collect, database, build_window(period, now), period, rows
    )
    result["generated_at"] = _iso(now)
    data.dashboard_cache[(period, rows)] = (now, result)
    return result


async def _background_refresh(
    hass: HomeAssistant,
    data: BlockyData,
    database: QueryLogDatabase,
    period: str,
    rows: int,
) -> None:
    """Refresh a stale long-period answer; one round at a time, errors are kept
    out of the cache (the old answer stays until it is too old)."""
    key = (period, rows)
    try:
        async with data.dashboard_lock:
            cached = data.dashboard_cache.get(key)
            if cached is None or dt_util.utcnow() - cached[0] >= _fresh_for(period):
                await _round(hass, data, database, period, rows)
    except BlockyDbError as err:
        _LOGGER.debug("dashboard background refresh failed (%s)", type(err).__name__)
    finally:
        data.dashboard_refreshing.discard(key)


async def async_dashboard(
    hass: HomeAssistant,
    data: BlockyData,
    database: QueryLogDatabase,
    period: str,
    rows: int,
) -> dict[str, Any]:
    """Return the dashboard answer, from the cache while it is fresh.

    The lock makes callers that arrive together wait for one database round.
    An answer that is stale but under an hour old is returned at once, marked
    ``"stale": True``, while one background round refreshes it. The cache holds at
    most one answer per (period, rows). The returned dict is shared: callers
    must copy it before changing it.
    """
    key = (period, rows)
    cached = data.dashboard_cache.get(key)
    if cached is not None:
        age = dt_util.utcnow() - cached[0]
        if age < _fresh_for(period):
            _LOGGER.debug("dashboard cache hit for %s", period)
            return cached[1]
        if age < DASHBOARD_STALE_MAX:
            _LOGGER.debug("dashboard stale hit for %s, refreshing", period)
            if key not in data.dashboard_refreshing:
                data.dashboard_refreshing.add(key)
                hass.async_create_background_task(
                    _background_refresh(hass, data, database, period, rows),
                    f"{DOMAIN} dashboard refresh",
                )
            # A copy: the cached answer itself is never marked.
            return {**cached[1], "stale": True}
    async with data.dashboard_lock:
        now = dt_util.utcnow()
        cached = data.dashboard_cache.get(key)
        if cached is not None and now - cached[0] < _fresh_for(period):
            _LOGGER.debug("dashboard cache hit for %s", period)
            return cached[1]
        _LOGGER.debug("dashboard cache miss for %s", period)
        if not data.table_logged and _LOGGER.isEnabledFor(logging.DEBUG):
            data.table_logged = True
            try:
                facts = await hass.async_add_executor_job(database.table_info)
            except BlockyDbError:
                facts = None
            # Schema facts only: index names, their columns, a row estimate.
            _LOGGER.debug("query log table facts: %s", facts)
        return await _round(hass, data, database, period, rows)
