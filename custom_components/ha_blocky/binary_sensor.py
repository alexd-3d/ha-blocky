"""Binary sensors for the Blocky DNS integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BlockyConfigEntry
from .entity import BlockyEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlockyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    async_add_entities([ConnectionBinarySensor(entry.runtime_data, "connection")])


class ConnectionBinarySensor(BlockyEntity, BinarySensorEntity):
    """Whether Blocky answers; stays available so an outage is visible."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        """Always available: its state is the availability of Blocky."""
        return True

    @property
    def is_on(self) -> bool:
        """Return whether the last poll succeeded."""
        return self.coordinator.last_update_success
