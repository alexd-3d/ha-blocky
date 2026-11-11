"""Binary sensors for the Blocky DNS integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import LEAK_WINDOW
from .coordinator import BlockyConfigEntry
from .entity import BlockyEntity, BlockyStatsEntity, device_info
from .requests import RequestTracker

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlockyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    data = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        ConnectionBinarySensor(data.coordinator, "connection")
    ]
    if data.stats is not None:
        entities.append(DatabaseBinarySensor(data.stats, "database"))
    if data.requests is not None:
        entities.append(ZoneLeakBinarySensor(entry.entry_id, data.requests))
    async_add_entities(entities)


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


class DatabaseBinarySensor(BlockyStatsEntity, BinarySensorEntity):
    """Whether the query log database answers; stays available as well."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        """Always available: its state is the availability of the database."""
        return True

    @property
    def is_on(self) -> bool:
        """Return whether the last statistics round succeeded."""
        return self.coordinator.last_update_success


class ZoneLeakBinarySensor(BinarySensorEntity):
    """On while a client of an allowlist-only zone got an answer for a domain
    that is on none of the zone's allow lists, during the last hour.

    Only a count is exposed, never a client or a domain.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "zone_leak"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, entry_id: str, tracker: RequestTracker) -> None:
        """Initialize the sensor."""
        self._tracker = tracker
        # Not "zone_...": the sensors of deleted zones are removed by prefix.
        self._attr_unique_id = f"{entry_id}_domain_leak"
        self._attr_device_info = device_info(entry_id)

    async def async_added_to_hass(self) -> None:
        """Follow the tracker; every statistics round re-evaluates the hour."""
        self.async_on_remove(
            self._tracker.async_add_listener(self.async_write_ha_state)
        )

    @property
    def is_on(self) -> bool:
        """Return whether a leak was seen in the last hour."""
        return self._tracker.leak_count() > 0

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        """Return how many leaks were seen and for how many minutes they count."""
        return {
            "count": self._tracker.leak_count(),
            "window_minutes": int(LEAK_WINDOW.total_seconds() // 60),
        }
