"""Camera entity for PNZEO — RTSP stream with go2rtc WebRTC support."""
from __future__ import annotations

import logging

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PNZEOCoordinator
from .entity import PNZEOEntity

_LOGGER = logging.getLogger(__name__)

GO2RTC_STREAMS_API = "http://localhost:1984/api/streams"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PNZEOCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Register stream in go2rtc for WebRTC (zero latency)
    await _register_go2rtc(coordinator.device)

    async_add_entities([PNZEOCamera(coordinator)])


async def _register_go2rtc(device) -> None:
    """Register RTSP stream in go2rtc for WebRTC playback."""
    import aiohttp
    stream_name = f"pnzeo_{device.unique_id}"
    try:
        async with aiohttp.ClientSession() as session:
            # Add stream to go2rtc
            url = f"{GO2RTC_STREAMS_API}?src={stream_name}"
            payload = {"name": stream_name, "src": device.rtsp_url}
            async with session.put(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status in (200, 201):
                    _LOGGER.info("Registered go2rtc stream: %s", stream_name)
                else:
                    _LOGGER.debug("go2rtc registration: %s", resp.status)
    except Exception as ex:
        _LOGGER.debug("go2rtc not available (WebRTC disabled): %s", ex)


class PNZEOCamera(PNZEOEntity, Camera):
    """PNZEO camera with RTSP stream — WebRTC via go2rtc, fallback to HLS."""

    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_brand = "PNZEO"
    _attr_model = "W8"

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        PNZEOEntity.__init__(self, coordinator, "camera", "Камера")
        Camera.__init__(self)
        self._attr_is_streaming = True
        self._attr_is_on = True
        self._stream_name = f"pnzeo_{coordinator.device.unique_id}"

    async def stream_source(self) -> str | None:
        """Return RTSP stream URL.

        HA's stream component routes this through go2rtc automatically
        if go2rtc addon is running. This gives WebRTC with ~200ms latency.
        Without go2rtc, falls back to HLS (~3s latency).
        """
        return self.coordinator.device.rtsp_url

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a snapshot from the camera via ffmpeg."""
        import asyncio
        import subprocess

        def _grab():
            try:
                result = subprocess.run(
                    [
                        "ffmpeg", "-y", "-rtsp_transport", "tcp",
                        "-i", self.coordinator.device.rtsp_url,
                        "-frames:v", "1", "-f", "image2", "-q:v", "3", "pipe:1",
                    ],
                    capture_output=True, timeout=10,
                )
                if result.returncode == 0 and len(result.stdout) > 1000:
                    return result.stdout
            except Exception:
                pass
            return None

        return await asyncio.get_event_loop().run_in_executor(None, _grab)
