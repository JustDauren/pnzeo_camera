"""Base entity for PNZEO camera."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PNZEOCoordinator


class PNZEOEntity(CoordinatorEntity[PNZEOCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: PNZEOCoordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        device = coordinator.device
        self._attr_unique_id = f"{device.unique_id}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.unique_id)},
            name=device.name,
            manufacturer="PNZEO",
            model="W8",
        )

    @property
    def available(self) -> bool:
        data = self.coordinator.data or {}
        return data.get("reachable", True)
