"""Binary sensor entities for PNZEO camera."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PNZEOCoordinator
from .entity import PNZEOEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up PNZEO binary sensor entities."""
    coordinator: PNZEOCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        PNZEOConnectionBinarySensor(coordinator),
        PNZEOMotionBinarySensor(coordinator),
    ])


class PNZEOConnectionBinarySensor(PNZEOEntity, BinarySensorEntity):
    """Binary sensor showing whether the camera is connected via PPPP."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "connection_status", "Connection")

    @property
    def is_on(self) -> bool:
        """Return True if the camera is connected."""
        return self.coordinator.data.get("connection_state") == "CONNECTED"

    @property
    def available(self) -> bool:
        """Always available -- must be visible even when camera is disconnected."""
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return connection method as extra attribute."""
        return {
            "connection_method": self.coordinator.data.get(
                "connection_method", "unknown"
            ),
        }


class PNZEOMotionBinarySensor(PNZEOEntity, BinarySensorEntity):
    """Binary sensor showing active motion detection state.

    Reflects the motion_armed state from alarm params polling.
    True real-time detection would need DRW alarm packets,
    but polling-based state satisfies ALRM-05.
    """

    _attr_device_class = BinarySensorDeviceClass.MOTION

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "motion_detected", "Motion Detected")

    @property
    def is_on(self) -> bool:
        """Return True when motion_armed is enabled."""
        return self.coordinator.data.get("motion_armed", "0") == "1"
