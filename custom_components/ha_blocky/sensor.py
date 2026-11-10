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
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import ATTR_ITEMS
from .coordinator import BlockyConfigEntry
from .db import TopItem
from .entity import BlockyEntity, BlockyStatsEntity
from .stats import BlockyStatsCoordinator, QueryStats, blocked_ratio

PARALLEL_UPDATES = 0

UNIT_QUERIES = "queries"
UNIT_CLIENTS = "clients"


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
    async_add_entities(entities)


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
