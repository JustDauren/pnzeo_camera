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
        PNZEOAlarmAction(coordinator),
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


# Alarm action option mapping: option -> (mail, snapshot, record)
_ALARM_ACTION_MAP = {
    "None": ("0", "0", "0"),
    "Mail": ("1", "0", "0"),
    "Snapshot": ("0", "1", "0"),
    "Record": ("0", "0", "1"),
    "Mail + Snapshot": ("1", "1", "0"),
    "Mail + Record": ("1", "0", "1"),
    "Snapshot + Record": ("0", "1", "1"),
    "All": ("1", "1", "1"),
}

# Reverse lookup: (mail, snapshot, record) -> option
_ALARM_ACTION_REVERSE = {v: k for k, v in _ALARM_ACTION_MAP.items()}


class PNZEOAlarmAction(PNZEOEntity, SelectEntity):
    """Alarm action select (mail/snapshot/record combinations)."""
    _attr_icon = "mdi:bell-cog"
    _attr_options = list(_ALARM_ACTION_MAP.keys())
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "alarm_action", "Alarm Action")

    @property
    def current_option(self) -> str:
        mail = self.coordinator.data.get("mail", "0")
        snapshot = self.coordinator.data.get("snapshot", "0")
        record = self.coordinator.data.get("record", "0")
        return _ALARM_ACTION_REVERSE.get((mail, snapshot, record), "None")

    async def async_select_option(self, option: str) -> None:
        values = _ALARM_ACTION_MAP.get(option)
        if values is None:
            return
        mail, snapshot, record = values
        await self.coordinator.device.client.set_alarm_params(
            mail=int(mail), snapshot=int(snapshot), record=int(record)
        )
        await self.coordinator.async_request_refresh()
