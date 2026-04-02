"""DataUpdateCoordinator for PNZEO camera."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import ConnectionState
from .device import PNZEODevice

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)


class PNZEOCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to poll camera state every 60s.

    Uses ConnectionState enum to gate reconnection decisions:
    - CONNECTED: normal poll path (get_status + get_camera_params)
    - CONNECTING/RECONNECTING/AUTHENTICATING: watchdog is handling it, don't interfere
    - DISCONNECTED/FAILED: trigger reconnection via async_setup

    PPPP is used for control commands (switches, buttons, PTZ etc).
    If PPPP connection fails, video still works via RTSP -- we just
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

        Uses ConnectionState enum to gate reconnection:
        - CONNECTED: normal poll path
        - CONNECTING/RECONNECTING/AUTHENTICATING: watchdog is handling it, don't interfere
        - DISCONNECTED/FAILED: trigger reconnection
        Never raise UpdateFailed for PPPP issues -- RTSP video must keep working.
        """
        client = self.device.client
        state = client.connection_state

        if state == ConnectionState.CONNECTED:
            # Normal path: poll camera state
            try:
                await client.get_status()
                await client.get_camera_params()
                # Alarm params polling (5s timeout each to protect Pi5 60s budget)
                try:
                    await asyncio.wait_for(client.get_alarm_params(), timeout=5.0)
                except (asyncio.TimeoutError, Exception):
                    _LOGGER.debug("Alarm params polling failed or timed out")
                try:
                    await asyncio.wait_for(client.get_alarm_ex_params(), timeout=5.0)
                except (asyncio.TimeoutError, Exception):
                    _LOGGER.debug("Alarm EX params polling failed or timed out")
                self._pppp_available = True
                return self._build_data(client)
            except Exception as ex:
                _LOGGER.debug("PPPP update failed: %s", ex)
                self._pppp_available = False
                return self._build_data(client)

        if state in (
            ConnectionState.CONNECTING,
            ConnectionState.RECONNECTING,
            ConnectionState.AUTHENTICATING,
        ):
            # Reconnection in progress -- don't interfere, return last known state
            _LOGGER.debug(
                "PPPP %s for %s -- watchdog handling reconnection",
                state.name, self.device.host,
            )
            return self._build_data(client)

        if state in (ConnectionState.DISCONNECTED, ConnectionState.FAILED):
            # Trigger reconnection
            try:
                await client.disconnect()
                result = await self.device.async_setup()
                self._pppp_available = result
                if not result:
                    _LOGGER.debug(
                        "PPPP not available for %s. "
                        "Control commands disabled, video still works via RTSP.",
                        self.device.host,
                    )
                return self._build_data(client)
            except Exception as ex:
                _LOGGER.debug("PPPP setup failed: %s", ex)
                self._pppp_available = False
                return self._build_data(client)

        # Fallback for any unexpected state
        return self._build_data(client)

    def _build_data(self, client) -> dict[str, Any]:
        """Build coordinator data dict with connection state included."""
        data = dict(client.state) if client.state else {}
        data["connection_state"] = client.connection_state.name
        data["connection_method"] = client.connection_method
        return data
