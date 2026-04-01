"""Button entities for PNZEO camera."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
        PNZEORebootButton(coordinator),
        PNZEOSnapshotButton(coordinator),
        PNZEOFormatSDButton(coordinator),
    ])


class PNZEORebootButton(PNZEOEntity, ButtonEntity):
    _attr_icon = "mdi:restart"

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "reboot", "Reboot")

    async def async_press(self) -> None:
        await self.coordinator.device.client.reboot()


class PNZEOSnapshotButton(PNZEOEntity, ButtonEntity):
    _attr_icon = "mdi:camera"

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "snapshot", "Snapshot")

    async def async_press(self) -> None:
        await self.coordinator.device.client.snapshot()


class PNZEOFormatSDButton(PNZEOEntity, ButtonEntity):
    _attr_icon = "mdi:sd"
    _attr_entity_registry_enabled_default = False  # hidden by default (destructive)

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "format_sd", "Format SD Card")

    async def async_press(self) -> None:
        await self.coordinator.device.client.format_sd()
