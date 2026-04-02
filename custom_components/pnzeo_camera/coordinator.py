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
    """Coordinator to poll camera state every 60s.

    PPPP is used for control commands (switches, buttons, PTZ etc).
    If PPPP connection fails, video still works via RTSP — we just
    return empty state and log a warning instead of raising UpdateFailed.
    """

    def __init__(self, hass: HomeAssistant, device: PNZEODevice) -> None:
        super().__init__(hass, _LOGGER, name="PNZEO Camera", update_interval=SCAN_INTERVAL)
        self.device = device
        self._pppp_available = False

    @property
    def pppp_available(self) -> bool:
        """Whether PPPP control channel is connected."""
        return self._pppp_available

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch camera state via PPPP.

        If PPPP is not connected, try to reconnect silently.
        Never raise UpdateFailed for PPPP issues — RTSP video must keep working.
        """
        if not self.device.client.connected:
            try:
                result = await self.device.async_setup()
                self._pppp_available = result
                if not result:
                    _LOGGER.debug(
                        "PPPP not available for %s (method: %s). "
                        "Control commands disabled, video still works via RTSP.",
                        self.device.host,
                        self.device.client.connection_method,
                    )
                    return self.device.client.state
            except Exception as ex:
                _LOGGER.debug("PPPP setup failed: %s", ex)
                self._pppp_available = False
                return {}

        try:
            await self.device.client.get_status()
            await self.device.client.get_camera_params()
            self._pppp_available = True
            return self.device.client.state
        except Exception as ex:
            _LOGGER.debug("PPPP update failed: %s. Will retry next cycle.", ex)
            self._pppp_available = False
            # Don't raise UpdateFailed — let RTSP video keep working
            return self.device.client.state
