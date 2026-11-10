"""Select entities for the Blocky DNS integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DEFAULT_PAUSE_MINUTES, PAUSE_OPTIONS_MINUTES
from .coordinator import BlockyConfigEntry, BlockyCoordinator
from .entity import BlockyEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlockyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the select entities."""
    async_add_entities([PauseDurationSelect(entry.runtime_data, "pause_duration")])


class PauseDurationSelect(BlockyEntity, SelectEntity, RestoreEntity):
    """How long the blocking switch pauses filtering."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_current_option = str(DEFAULT_PAUSE_MINUTES)

    def __init__(self, coordinator: BlockyCoordinator, key: str) -> None:
        """Initialize the select with its fixed list of durations."""
        super().__init__(coordinator, key)
        self._attr_options = [str(minutes) for minutes in PAUSE_OPTIONS_MINUTES]

    @property
    def available(self) -> bool:
        """A local setting; available even when Blocky is not."""
        return True

    async def async_added_to_hass(self) -> None:
        """Restore the previous choice."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in self.options:
            self._apply(last_state.state)

    async def async_select_option(self, option: str) -> None:
        """Change the pause duration."""
        self._apply(option)
        self.async_write_ha_state()

    def _apply(self, option: str) -> None:
        self._attr_current_option = option
        self.coordinator.pause_minutes = int(option)
