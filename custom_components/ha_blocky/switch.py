"""Blocking switch for the Blocky DNS integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import BlockyError
from .const import ATTR_DISABLED_GROUPS, DEFAULT_PAUSE_MINUTES
from .coordinator import BlockyConfigEntry
from .entity import BlockyEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlockyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the blocking switch."""
    async_add_entities([BlockingSwitch(entry.runtime_data.coordinator, "blocking")])


class BlockingSwitch(BlockyEntity, SwitchEntity):
    """On while Blocky filters DNS; turning it off pauses filtering."""

    @property
    def is_on(self) -> bool:
        """Return whether blocking is enabled."""
        return self.coordinator.data.enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the groups blocking is currently disabled for."""
        return {ATTR_DISABLED_GROUPS: list(self.coordinator.data.disabled_groups)}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable blocking."""
        try:
            await self.coordinator.async_enable_blocking()
        except BlockyError as err:
            raise HomeAssistantError("Could not enable Blocky blocking") from err

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Pause blocking for the default duration; never indefinitely."""
        try:
            await self.coordinator.async_pause_blocking(DEFAULT_PAUSE_MINUTES)
        except BlockyError as err:
            raise HomeAssistantError("Could not pause Blocky blocking") from err
