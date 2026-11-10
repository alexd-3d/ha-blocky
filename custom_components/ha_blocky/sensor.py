"""Sensors for the Blocky DNS integration."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
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
    """Set up the sensors."""
    async_add_entities([BlockingResumesAtSensor(entry.runtime_data, "resumes_at")])


class BlockingResumesAtSensor(BlockyEntity, SensorEntity):
    """When Blocky will re-enable blocking on its own."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        """Return the resume time, or None while blocking is active."""
        return self.coordinator.resumes_at
