"""Base entity for the Blocky DNS integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_NAME, DOMAIN
from .coordinator import BlockyCoordinator


class BlockyEntity(CoordinatorEntity[BlockyCoordinator]):
    """An entity that belongs to one Blocky instance."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BlockyCoordinator, key: str) -> None:
        """Initialize the entity; ``key`` is its translation key."""
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=DEVICE_NAME,
            manufacturer="Blocky",
            entry_type=DeviceEntryType.SERVICE,
        )
