"""Switch entities for PNZEO camera."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
        PNZEONightVisionSwitch(coordinator),
        PNZEOMotionSwitch(coordinator),
        PNZEORecordingSwitch(coordinator),
        PNZEOLEDSwitch(coordinator),
    ])


class PNZEONightVisionSwitch(PNZEOEntity, SwitchEntity):
    """Night vision / IR LED toggle."""
    _attr_icon = "mdi:weather-night"

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "night_vision", "Ночной режим")
        self._is_on = False

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.device.client.set_ir_led(True)
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.device.client.set_ir_led(False)
        self._is_on = False
        self.async_write_ha_state()


class PNZEOMotionSwitch(PNZEOEntity, SwitchEntity):
    """Motion detection toggle."""
    _attr_icon = "mdi:motion-sensor"

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "motion_detection", "Детекция движения")
        self._is_on = True

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.device.client.set_motion_detection(True)
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.device.client.set_motion_detection(False)
        self._is_on = False
        self.async_write_ha_state()


class PNZEORecordingSwitch(PNZEOEntity, SwitchEntity):
    """SD card recording toggle."""
    _attr_icon = "mdi:record-rec"

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "sd_recording", "Запись на SD")
        self._is_on = False

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.device.client.set_recording_mode(1)
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.device.client.set_recording_mode(0)
        self._is_on = False
        self.async_write_ha_state()


class PNZEOLEDSwitch(PNZEOEntity, SwitchEntity):
    """Camera indicator LED toggle."""
    _attr_icon = "mdi:led-on"

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "indicator_led", "Индикатор LED")
        self._is_on = True

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.device.client.set_indicator_led(True)
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.device.client.set_indicator_led(False)
        self._is_on = False
        self.async_write_ha_state()
