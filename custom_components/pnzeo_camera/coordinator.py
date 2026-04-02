"""DataUpdateCoordinator for PNZEO camera."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .device import PNZEODevice

_LOGGER = logging.getLogger(__name__)


class PNZEOCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Lightweight coordinator — just checks RTSP reachability. No PPPP."""

    def __init__(self, hass: HomeAssistant, device: PNZEODevice) -> None:
        super().__init__(hass, _LOGGER, name="PNZEO Camera", update_interval=timedelta(seconds=300))
        self.device = device

    async def _async_update_data(self) -> dict[str, Any]:
        """Quick RTSP port check. No PPPP, no timeouts."""
        try:
            from .pppp_discovery import check_rtsp
            reachable = await check_rtsp(self.device.host, self.device.rtsp_port, timeout=3)
            return {"reachable": reachable}
        except Exception:
            return {"reachable": False}
