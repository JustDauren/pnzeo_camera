"""Sensor entities for PNZEO camera."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PNZEOCoordinator
from .entity import PNZEOEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up PNZEO sensor entities."""
    coordinator: PNZEOCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        PNZEOSDTotalSensor(coordinator),
        PNZEOSDFreeSensor(coordinator),
        PNZEOSDUsedSensor(coordinator),
        PNZEOFirmwareSensor(coordinator),
        PNZEODeviceNameSensor(coordinator),
    ])


class PNZEOSDTotalSensor(PNZEOEntity, SensorEntity):
    """Sensor showing total SD card capacity in MB."""

    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:sd"

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "sd_total", "SD Card Total")

    @property
    def native_value(self) -> int | None:
        """Return total SD card capacity in MB."""
        raw = self.coordinator.data.get("sdtotal")
        if raw is None:
            return None
        try:
            return int(raw)
        except (ValueError, TypeError):
            return None


class PNZEOSDFreeSensor(PNZEOEntity, SensorEntity):
    """Sensor showing free SD card space in MB."""

    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:sd"

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "sd_free", "SD Card Free")

    @property
    def native_value(self) -> int | None:
        """Return free SD card space in MB."""
        raw = self.coordinator.data.get("sdfree")
        if raw is None:
            return None
        try:
            return int(raw)
        except (ValueError, TypeError):
            return None


class PNZEOSDUsedSensor(PNZEOEntity, SensorEntity):
    """Sensor showing used SD card space in MB (computed: total - free)."""

    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:sd"

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "sd_used", "SD Card Used")

    @property
    def native_value(self) -> int | None:
        """Return used SD card space in MB (total - free)."""
        raw_total = self.coordinator.data.get("sdtotal")
        raw_free = self.coordinator.data.get("sdfree")
        if raw_total is None or raw_free is None:
            return None
        try:
            return int(raw_total) - int(raw_free)
        except (ValueError, TypeError):
            return None


class PNZEOFirmwareSensor(PNZEOEntity, SensorEntity):
    """Sensor showing camera firmware version."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chip"

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "firmware_version", "Firmware Version")

    @property
    def native_value(self) -> str | None:
        """Return firmware version from get_status or capabilities."""
        return self.coordinator.data.get(
            "sysver",
            self.coordinator.device.client.state.get("firmware", "unknown"),
        )


class PNZEODeviceNameSensor(PNZEOEntity, SensorEntity):
    """Sensor showing camera device name."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:tag"

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "device_name_info", "Device Name Info")

    @property
    def native_value(self) -> str | None:
        """Return device name from camera params or device config."""
        return self.coordinator.data.get("devname", self.coordinator.device.name)
