"""Select entities for the Blocky DNS integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import BlockyError
from .const import PAUSE_OPTION_ACTIVE, PAUSE_OPTIONS_MINUTES
from .coordinator import BlockyConfigEntry, BlockyCoordinator
from .entity import BlockyEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlockyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the select entities."""
    async_add_entities([PauseBlockingSelect(entry.runtime_data, "pause_blocking")])


class PauseBlockingSelect(BlockyEntity, SelectEntity):
    """Choosing a duration pauses blocking for that long, right away.

    Shows ``active`` while blocking is on and the chosen duration while a
    pause started here or by the switch is running. A pause started some
    other way has no matching option, so the state is unknown.
    """

    def __init__(self, coordinator: BlockyCoordinator, key: str) -> None:
        """Initialize the select with its fixed list of durations."""
        super().__init__(coordinator, key)
        self._attr_options = [
            PAUSE_OPTION_ACTIVE,
            *(str(minutes) for minutes in PAUSE_OPTIONS_MINUTES),
        ]

    @property
    def current_option(self) -> str | None:
        """Return the running pause, or ``active`` when there is none."""
        if self.coordinator.data.enabled:
            return PAUSE_OPTION_ACTIVE
        minutes = self.coordinator.pause_minutes
        if minutes in PAUSE_OPTIONS_MINUTES:
            return str(minutes)
        return None

    async def async_select_option(self, option: str) -> None:
        """Pause blocking for the chosen duration, or resume it."""
        try:
            if option == PAUSE_OPTION_ACTIVE:
                await self.coordinator.async_enable_blocking()
            else:
                await self.coordinator.async_pause_blocking(int(option))
        except BlockyError as err:
            raise HomeAssistantError("Could not change Blocky blocking") from err
