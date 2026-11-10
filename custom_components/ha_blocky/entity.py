"""Base entities for the Blocky DNS integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_NAME, DOMAIN
from .coordinator import BlockyCoordinator
from .stats import BlockyStatsCoordinator


def _device_info(entry_id: str) -> DeviceInfo:
    """Return the device all entities of one config entry belong to."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name=DEVICE_NAME,
        manufacturer="Blocky",
        entry_type=DeviceEntryType.SERVICE,
    )


class BlockyEntity(CoordinatorEntity[BlockyCoordinator]):
    """An entity fed by the blocking status of one Blocky instance."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BlockyCoordinator, key: str) -> None:
        """Initialize the entity; ``key`` is its translation key."""
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = _device_info(entry_id)


class BlockyStatsEntity(CoordinatorEntity[BlockyStatsCoordinator]):
    """An entity fed by the query log statistics."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BlockyStatsCoordinator, key: str) -> None:
        """Initialize the entity; ``key`` is its translation key."""
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = _device_info(entry_id)
