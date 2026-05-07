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
        self._reconnect_task: asyncio.Task | None = None

    @property
    def pppp_available(self) -> bool:
        """Whether PPPP control channel is connected."""
        return self._pppp_available

    def _ensure_reconnect_task(self) -> None:
        """Spawn a background reconnect task if one is not already running.

        Keeps the coordinator update fast: HA never blocks 20+ seconds on
        connect() — entities just stay unavailable until reconnect succeeds.
        """
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = self.hass.loop.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        try:
            await self.device.client.disconnect()
            ok = await self.device.async_setup()
            self._pppp_available = ok
            if ok:
                _LOGGER.info("PPPP reconnect succeeded for %s", self.device.host)
                self.async_set_updated_data(self._build_data(self.device.client))
            else:
                _LOGGER.debug(
                    "PPPP reconnect did not succeed for %s (last_failure=%s)",
                    self.device.host, self.device.client.last_failure,
                )
        except Exception as ex:
            _LOGGER.debug("PPPP reconnect crashed: %s", ex)
            self._pppp_available = False

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
                try:
                    await asyncio.wait_for(client.get_ircut_params(), timeout=5.0)
                except (asyncio.TimeoutError, Exception):
                    _LOGGER.debug("IR cut params polling failed or timed out")
                try:
                    await asyncio.wait_for(client.get_record_mode(), timeout=5.0)
                except (asyncio.TimeoutError, Exception):
                    _LOGGER.debug("Record mode polling failed or timed out")
                # WiFi and network change rarely -- poll every 5th cycle to save Pi5 budget
                if not hasattr(self, "_poll_counter"):
                    self._poll_counter = 0
                self._poll_counter += 1
                if self._poll_counter % 5 == 0:
                    try:
                        await asyncio.wait_for(client.get_wifi_params(), timeout=5.0)
                    except (asyncio.TimeoutError, Exception):
                        _LOGGER.debug("WiFi params polling failed or timed out")
                    try:
                        await asyncio.wait_for(client.get_network_params(), timeout=5.0)
                    except (asyncio.TimeoutError, Exception):
                        _LOGGER.debug("Network params polling failed or timed out")
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
            # Kick off reconnection in the background; do NOT block the
            # coordinator (connect() can take 20+ seconds). Entities stay on
            # last-known data until reconnect publishes a new update.
            self._pppp_available = False
            self._ensure_reconnect_task()
            return self._build_data(client)

        # Fallback for any unexpected state
        return self._build_data(client)

    def _build_data(self, client) -> dict[str, Any]:
        """Build coordinator data dict with connection state included."""
        data = dict(client.state) if client.state else {}
        data["connection_state"] = client.connection_state.name
        data["connection_method"] = client.connection_method
        return data
