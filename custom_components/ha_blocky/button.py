"""Buttons for the Blocky DNS integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import BlockyError
from .coordinator import BlockyConfigEntry
from .entity import BlockyEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlockyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            RefreshListsButton(coordinator, "refresh_lists"),
            FlushCacheButton(coordinator, "flush_cache"),
        ]
    )


class RefreshListsButton(BlockyEntity, ButtonEntity):
    """Reload all allow and deny lists."""

    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        """Reload the lists."""
        try:
            await self.coordinator.async_refresh_lists()
        except BlockyError as err:
            raise HomeAssistantError("Could not refresh Blocky lists") from err


class FlushCacheButton(BlockyEntity, ButtonEntity):
    """Clear the DNS response cache."""

    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        """Flush the cache."""
        try:
            await self.coordinator.async_flush_cache()
        except BlockyError as err:
            raise HomeAssistantError("Could not flush the Blocky cache") from err
