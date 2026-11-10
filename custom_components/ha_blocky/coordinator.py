"""Polling coordinator for the Blocky blocking status."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Sequence
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import BlockingStatus, BlockyClient, BlockyError
from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DISABLED_GROUPS,
    DEFAULT_PAUSE_MINUTES,
    DOMAIN,
    EVENT_BLOCKING_DISABLED_EXTERNALLY,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# A recomputed resume time within this distance of the known one is the same
# deadline seen through polling jitter.
_RESUME_JITTER = timedelta(seconds=5)

type BlockyConfigEntry = ConfigEntry[BlockyCoordinator]


class BlockyCoordinator(DataUpdateCoordinator[BlockingStatus]):
    """Poll Blocky and notice blocking being disabled behind our back."""

    config_entry: BlockyConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: BlockyConfigEntry, client: BlockyClient
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.pause_minutes: int = DEFAULT_PAUSE_MINUTES
        self.resumes_at: datetime | None = None
        # Serializes polls and commands so a poll never observes a command of
        # ours half-applied and reports it as an external change.
        self._lock = asyncio.Lock()

    async def _async_update_data(self) -> BlockingStatus:
        """Fetch the status and report unexpected loss of blocking."""
        async with self._lock:
            try:
                status = await self.client.async_get_status()
            except BlockyError as err:
                raise UpdateFailed(str(err)) from err
            self._report_external_disable(self.data, status)
            self._update_resume_time(status)
            return status

    def _report_external_disable(
        self, previous: BlockingStatus | None, current: BlockingStatus
    ) -> None:
        """Fire an event when blocking was reduced without our command."""
        if previous is None or current.enabled:
            return
        newly_disabled = set(current.disabled_groups) - set(previous.disabled_groups)
        if not previous.enabled and not newly_disabled:
            return
        _LOGGER.warning("Blocky blocking was disabled outside Home Assistant")
        self.hass.bus.async_fire(
            EVENT_BLOCKING_DISABLED_EXTERNALLY,
            {
                ATTR_CONFIG_ENTRY_ID: self.config_entry.entry_id,
                ATTR_DISABLED_GROUPS: list(current.disabled_groups),
            },
        )

    def _update_resume_time(self, status: BlockingStatus) -> None:
        """Track when Blocky will re-enable blocking on its own."""
        if status.enabled or status.auto_enable_in_sec <= 0:
            self.resumes_at = None
            return
        candidate = (
            dt_util.utcnow() + timedelta(seconds=status.auto_enable_in_sec)
        ).replace(microsecond=0)
        if self.resumes_at is None or abs(candidate - self.resumes_at) > _RESUME_JITTER:
            self.resumes_at = candidate

    async def _async_run_command(self, command: Awaitable[None]) -> None:
        """Run a command of ours and publish the resulting status."""
        async with self._lock:
            await command
            status = await self.client.async_get_status()
            self._update_resume_time(status)
        self.async_set_updated_data(status)

    async def async_enable_blocking(self) -> None:
        """Enable blocking."""
        await self._async_run_command(self.client.async_enable_blocking())

    async def async_disable_blocking(
        self, duration_seconds: int, groups: Sequence[str] = ()
    ) -> None:
        """Disable blocking for a limited time."""
        await self._async_run_command(
            self.client.async_disable_blocking(duration_seconds, groups)
        )

    async def async_refresh_lists(self) -> None:
        """Reload all lists."""
        await self._async_run_command(self.client.async_refresh_lists())

    async def async_flush_cache(self) -> None:
        """Clear the DNS cache."""
        await self._async_run_command(self.client.async_flush_cache())
