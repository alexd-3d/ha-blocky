"""Sensors for the Blocky DNS integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import ATTR_ITEMS
from .coordinator import BlockyConfigEntry
from .db import TopItem
from .entity import BlockyEntity, BlockyStatsEntity, device_info
from .lists import ListManager
from .stats import BlockyStatsCoordinator, QueryStats, blocked_ratio

PARALLEL_UPDATES = 0

UNIT_QUERIES = "queries"
UNIT_CLIENTS = "clients"
UNIT_ENTRIES = "entries"
LIST_SENSOR_PREFIX = "list_"
ZONE_SENSOR_PREFIX = "zone_"
ZONE_SENSOR_SUFFIXES = ("queries_24h", "blocked_24h")


@dataclass(frozen=True, kw_only=True)
class BlockyStatsSensorDescription(SensorEntityDescription):
    """A sensor computed from the query log statistics."""

    value_fn: Callable[[QueryStats], StateType]


@dataclass(frozen=True, kw_only=True)
class BlockyTopSensorDescription(SensorEntityDescription):
    """A top-list sensor: state is the list length, items are attributes."""

    items_fn: Callable[[QueryStats], tuple[TopItem, ...]]


STATS_SENSORS: tuple[BlockyStatsSensorDescription, ...] = (
    BlockyStatsSensorDescription(
        key="queries_total",
        translation_key="queries_total",
        native_unit_of_measurement=UNIT_QUERIES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.queries_total,
    ),
    BlockyStatsSensorDescription(
        key="blocked_total",
        translation_key="blocked_total",
        native_unit_of_measurement=UNIT_QUERIES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.blocked_total,
    ),
    BlockyStatsSensorDescription(
        key="resolved_total",
        translation_key="resolved_total",
        native_unit_of_measurement=UNIT_QUERIES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.category_totals["resolved"],
    ),
    BlockyStatsSensorDescription(
        key="cached_total",
        translation_key="cached_total",
        native_unit_of_measurement=UNIT_QUERIES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.category_totals["cached"],
    ),
    BlockyStatsSensorDescription(
        key="local_total",
        translation_key="local_total",
        native_unit_of_measurement=UNIT_QUERIES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.category_totals["local"],
    ),
    BlockyStatsSensorDescription(
        key="other_total",
        translation_key="other_total",
        native_unit_of_measurement=UNIT_QUERIES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.category_totals["other"],
    ),
    BlockyStatsSensorDescription(
        key="queries_24h",
        translation_key="queries_24h",
        native_unit_of_measurement=UNIT_QUERIES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda stats: stats.summary.queries,
    ),
    BlockyStatsSensorDescription(
        key="blocked_24h",
        translation_key="blocked_24h",
        native_unit_of_measurement=UNIT_QUERIES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda stats: stats.summary.blocked,
    ),
    BlockyStatsSensorDescription(
        key="blocked_ratio_24h",
        translation_key="blocked_ratio_24h",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda stats: blocked_ratio(stats.summary),
    ),
    BlockyStatsSensorDescription(
        key="clients_24h",
        translation_key="clients_24h",
        native_unit_of_measurement=UNIT_CLIENTS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda stats: stats.summary.clients,
    ),
    BlockyStatsSensorDescription(
        key="avg_response_time_24h",
        translation_key="avg_response_time_24h",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda stats: (
            None
            if stats.summary.avg_duration_ms is None
            else round(stats.summary.avg_duration_ms, 1)
        ),
    ),
)

TOP_SENSORS: tuple[BlockyTopSensorDescription, ...] = (
    BlockyTopSensorDescription(
        key="top_domains",
        translation_key="top_domains",
        items_fn=lambda stats: stats.top_domains,
    ),
    BlockyTopSensorDescription(
        key="top_blocked_domains",
        translation_key="top_blocked_domains",
        items_fn=lambda stats: stats.top_blocked_domains,
    ),
    BlockyTopSensorDescription(
        key="top_clients",
        translation_key="top_clients",
        entity_category=EntityCategory.DIAGNOSTIC,
        items_fn=lambda stats: stats.top_clients,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlockyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    data = entry.runtime_data
    entities: list[SensorEntity] = [
        BlockingResumesAtSensor(data.coordinator, "resumes_at")
    ]
    if data.stats is not None:
        entities.extend(
            BlockyStatsSensor(data.stats, description) for description in STATS_SENSORS
        )
        entities.extend(
            BlockyTopSensor(data.stats, description) for description in TOP_SENSORS
        )
        entities.extend(
            BlockyZoneSensor(data.stats, zone, blocked)
            for zone in data.zones
            for blocked in (False, True)
        )
    entities.extend(
        BlockyListSensor(entry.entry_id, data.lists, name)
        for name in data.lists.definitions
    )
    _remove_sensors_of_deleted_lists(hass, entry.entry_id, set(data.lists.definitions))
    _remove_sensors_of_deleted_zones(hass, entry.entry_id, set(data.zones))
    async_add_entities(entities)


def _remove_sensors_of_deleted_zones(
    hass: HomeAssistant, entry_id: str, current: set[str]
) -> None:
    """Drop the registry entries of zones that no longer exist."""
    registry = er.async_get(hass)
    prefix = f"{entry_id}_{ZONE_SENSOR_PREFIX}"
    keep = {
        f"{prefix}{name}_{suffix}"
        for name in current
        for suffix in ZONE_SENSOR_SUFFIXES
    }
    for registered in er.async_entries_for_config_entry(registry, entry_id):
        if registered.unique_id.startswith(prefix) and registered.unique_id not in keep:
            registry.async_remove(registered.entity_id)


def _remove_sensors_of_deleted_lists(
    hass: HomeAssistant, entry_id: str, current: set[str]
) -> None:
    """Drop the registry entries of lists that are no longer defined."""
    registry = er.async_get(hass)
    prefix = f"{entry_id}_{LIST_SENSOR_PREFIX}"
    for registered in er.async_entries_for_config_entry(registry, entry_id):
        if (
            registered.unique_id.startswith(prefix)
            and registered.unique_id.removeprefix(prefix) not in current
        ):
            registry.async_remove(registered.entity_id)


class BlockyListSensor(SensorEntity):
    """How many entries a manual list has."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "list_entries"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UNIT_ENTRIES

    def __init__(self, entry_id: str, lists: ListManager, name: str) -> None:
        """Initialize the sensor for one list."""
        self._lists = lists
        self._list_name = name
        definition = lists.definitions[name]
        self._attr_unique_id = f"{entry_id}_{LIST_SENSOR_PREFIX}{name}"
        self._attr_translation_placeholders = {"name": name}
        self._attr_device_info = device_info(entry_id)
        self._attr_extra_state_attributes = {
            "list_type": definition.list_type,
            "exact_only": definition.exact_only,
        }

    async def async_added_to_hass(self) -> None:
        """Follow changes of the list."""
        self.async_on_remove(self._lists.async_add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> int:
        """Return the number of entries."""
        return self._lists.count(self._list_name)


class BlockingResumesAtSensor(BlockyEntity, SensorEntity):
    """When Blocky will re-enable blocking on its own."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        """Return the resume time, or None while blocking is active."""
        return self.coordinator.resumes_at


class BlockyStatsSensor(BlockyStatsEntity, SensorEntity):
    """A number computed from the query log."""

    entity_description: BlockyStatsSensorDescription

    def __init__(
        self,
        coordinator: BlockyStatsCoordinator,
        description: BlockyStatsSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        """Return the value."""
        return self.entity_description.value_fn(self.coordinator.data)


class BlockyZoneSensor(BlockyStatsEntity, SensorEntity):
    """Queries of the clients of one zone in the last 24 hours."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UNIT_QUERIES

    def __init__(
        self, coordinator: BlockyStatsCoordinator, zone: str, blocked: bool
    ) -> None:
        """Initialize the sensor for one zone; ``blocked`` picks the counter."""
        suffix = ZONE_SENSOR_SUFFIXES[1 if blocked else 0]
        super().__init__(coordinator, f"zone_{suffix}")
        self._zone = zone
        self._blocked = blocked
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{ZONE_SENSOR_PREFIX}{zone}_{suffix}"
        )
        self._attr_translation_placeholders = {"zone": zone}

    @property
    def native_value(self) -> int:
        """Return the count; a zone without traffic reports 0."""
        queries, blocked = self.coordinator.data.zone_counts.get(self._zone, (0, 0))
        return blocked if self._blocked else queries


class BlockyTopSensor(BlockyStatsEntity, SensorEntity):
    """A top list from the last 24 hours.

    The list itself is DNS history, so it is kept out of the recorder.
    """

    entity_description: BlockyTopSensorDescription
    _unrecorded_attributes = frozenset({ATTR_ITEMS})

    def __init__(
        self,
        coordinator: BlockyStatsCoordinator,
        description: BlockyTopSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int:
        """Return how many entries the list has."""
        return len(self.entity_description.items_fn(self.coordinator.data))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the list entries."""
        return {
            ATTR_ITEMS: [
                {"name": item.name, "count": item.count}
                for item in self.entity_description.items_fn(self.coordinator.data)
            ]
        }
