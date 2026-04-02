"""Text entities for PNZEO camera."""
from __future__ import annotations

from homeassistant.components.text import TextEntity
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
        PNZEODeviceName(coordinator),
    ])


class PNZEODeviceName(PNZEOEntity, TextEntity):
    """Device name text entity."""
    _attr_icon = "mdi:label"
    _attr_native_max = 32

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "device_name", "Device Name")

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.get("devname", self.coordinator.device.name)

    async def async_set_value(self, value: str) -> None:
        await self.coordinator.device.client.set_device_name(value)
        await self.coordinator.async_request_refresh()
