"""DataUpdateCoordinator for PNZEO camera."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .device import PNZEODevice

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)


class PNZEOCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to poll camera state every 60s."""

    def __init__(self, hass: HomeAssistant, device: PNZEODevice) -> None:
        super().__init__(hass, _LOGGER, name="PNZEO Camera", update_interval=SCAN_INTERVAL)
        self.device = device

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch camera state."""
        if not self.device.client.connected:
            try:
                await self.device.async_setup()
            except Exception as ex:
                raise UpdateFailed(f"Connection failed: {ex}") from ex

        try:
            await self.device.client.get_status()
            await self.device.client.get_camera_params()
            return self.device.client.state
        except Exception as ex:
            raise UpdateFailed(f"Update failed: {ex}") from ex
