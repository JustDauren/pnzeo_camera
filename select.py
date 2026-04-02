"""Select entities for PNZEO camera (resolution, mirror, IR mode)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MIRROR_MAP, RESOLUTION_MAP
from .coordinator import PNZEOCoordinator
from .entity import PNZEOEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PNZEOCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        PNZEOResolution(coordinator),
        PNZEOMirror(coordinator),
    ])


class PNZEOResolution(PNZEOEntity, SelectEntity):
    _attr_icon = "mdi:quality-high"
    _attr_options = list(RESOLUTION_MAP.values())

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "resolution", "Resolution")
        self._current = "1080p"

    @property
    def current_option(self) -> str:
        return self._current

    async def async_select_option(self, option: str) -> None:
        rev = {v: k for k, v in RESOLUTION_MAP.items()}
        if option in rev:
            await self.coordinator.device.client.set_resolution(rev[option])
            self._current = option
            self.async_write_ha_state()


class PNZEOMirror(PNZEOEntity, SelectEntity):
    _attr_icon = "mdi:flip-horizontal"
    _attr_options = list(MIRROR_MAP.values())

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "mirror", "Mirror Mode")
        self._current = "Normal"

    @property
    def current_option(self) -> str:
        return self._current

    async def async_select_option(self, option: str) -> None:
        rev = {v: k for k, v in MIRROR_MAP.items()}
        if option in rev:
            await self.coordinator.device.client.set_mirror(rev[option])
            self._current = option
            self.async_write_ha_state()
