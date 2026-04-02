"""Event entities for PNZEO camera."""
from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PNZEOCoordinator
from .entity import PNZEOEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up PNZEO event entities."""
    coordinator: PNZEOCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        PNZEOAlarmEvent(coordinator),
    ])


class PNZEOAlarmEvent(PNZEOEntity, EventEntity):
    """Event entity that fires HA events on alarm triggers.

    Detects state transitions in motion_armed between polling cycles:
    when motion_armed goes from "0" to "1", fires a "motion" event
    that can be used in HA automations.
    """

    _attr_device_class = EventDeviceClass.MOTION
    _attr_event_types = ["motion", "gpio", "sound"]

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        super().__init__(coordinator, "alarm_event", "Alarm Event")
        self._prev_motion_armed: str | None = None

    def _handle_coordinator_update(self) -> None:
        """Detect motion_armed state transitions and fire events."""
        motion_armed = self.coordinator.data.get("motion_armed", "0")
        if (
            self._prev_motion_armed is not None
            and self._prev_motion_armed == "0"
            and motion_armed == "1"
        ):
            self._trigger_event("motion", {"source": "polling"})
        self._prev_motion_armed = motion_armed
        super()._handle_coordinator_update()
