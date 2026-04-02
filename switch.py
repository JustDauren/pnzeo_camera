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
        PNZEOIRSwitch(coordinator),
        PNZEOMotionSwitch(coordinator),
        PNZEORecordingSwitch(coordinator),
        PNZEOLEDSwitch(coordinator),
        PNZEOSoundAlarmSwitch(coordinator),
        PNZEOGPIOAlarmSwitch(coordinator),
        PNZEOMicrophoneSwitch(coordinator),
    ])


class PNZEOIRSwitch(PNZEOEntity, SwitchEntity):
    _attr_icon = "mdi:lightbulb-night"

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "ir_led", "IR LED")
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
    _attr_icon = "mdi:motion-sensor"

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "motion_detection", "Motion Detection")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.get("motion_armed", "1") == "1"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.device.client.set_motion_detection(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.device.client.set_motion_detection(False)
        await self.coordinator.async_request_refresh()


class PNZEORecordingSwitch(PNZEOEntity, SwitchEntity):
    _attr_icon = "mdi:record-rec"

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "sd_recording", "SD Recording")
        self._is_on = False

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.device.client.set_recording_mode(1)  # continuous
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.device.client.set_recording_mode(0)  # off
        self._is_on = False
        self.async_write_ha_state()


class PNZEOLEDSwitch(PNZEOEntity, SwitchEntity):
    _attr_icon = "mdi:led-on"

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "indicator_led", "Indicator LED")
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


class PNZEOSoundAlarmSwitch(PNZEOEntity, SwitchEntity):
    """Sound detection alarm switch."""
    _attr_icon = "mdi:volume-vibrate"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "sound_alarm", "Sound Detection Alarm")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.get("input_armed", "0") == "1"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.device.client.set_sound_detection(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.device.client.set_sound_detection(False)
        await self.coordinator.async_request_refresh()


class PNZEOGPIOAlarmSwitch(PNZEOEntity, SwitchEntity):
    """GPIO alarm input switch."""
    _attr_icon = "mdi:electric-switch"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "gpio_alarm", "GPIO Alarm")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.get("ioEnable", "0") == "1"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.device.client.set_gpio_alarm(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.device.client.set_gpio_alarm(False)
        await self.coordinator.async_request_refresh()


class PNZEOMicrophoneSwitch(PNZEOEntity, SwitchEntity):
    """Camera microphone on/off switch."""
    _attr_icon = "mdi:microphone"

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "microphone", "Microphone")

    @property
    def is_on(self) -> bool:
        # voice_enable from camera params: "1" = on, "0" = off
        return self.coordinator.data.get("voice_enable", "1") == "1"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.device.client.set_voice_enable(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.device.client.set_voice_enable(False)
        await self.coordinator.async_request_refresh()
