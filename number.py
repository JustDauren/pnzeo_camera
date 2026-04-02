"""Number entities for PNZEO camera (brightness, contrast)."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PNZEOCoordinator
from .entity import PNZEOEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PNZEOCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        PNZEOBrightness(coordinator),
        PNZEOContrast(coordinator),
        PNZEOMotionSensitivity(coordinator),
    ])


class PNZEOBrightness(PNZEOEntity, NumberEntity):
    _attr_icon = "mdi:brightness-6"
    _attr_native_min_value = 0
    _attr_native_max_value = 255
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "brightness", "Brightness")
        self._value = 128

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.device.client.set_brightness(int(value))
        self._value = int(value)
        self.async_write_ha_state()


class PNZEOContrast(PNZEOEntity, NumberEntity):
    _attr_icon = "mdi:contrast-box"
    _attr_native_min_value = 0
    _attr_native_max_value = 255
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "contrast", "Contrast")
        self._value = 128

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.device.client.set_contrast(int(value))
        self._value = int(value)
        self.async_write_ha_state()


class PNZEOMotionSensitivity(PNZEOEntity, NumberEntity):
    """Motion detection sensitivity (0=most sensitive, 9=least sensitive)."""
    _attr_icon = "mdi:motion-sensor"
    _attr_native_min_value = 0
    _attr_native_max_value = 9
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "motion_sensitivity", "Motion Sensitivity")

    @property
    def native_value(self) -> float:
        return int(self.coordinator.data.get("motion_sensitivity", "5"))

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.device.client.set_alarm_params(
            motion_sensitivity=int(value)
        )
        await self.coordinator.async_request_refresh()
