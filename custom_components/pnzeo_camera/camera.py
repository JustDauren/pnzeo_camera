"""Camera entity for PNZEO — RTSP stream via HA stream component."""
from __future__ import annotations

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PNZEOCoordinator
from .entity import PNZEOEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PNZEOCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PNZEOCamera(coordinator)])


class PNZEOCamera(PNZEOEntity, Camera):
    """PNZEO camera with RTSP stream and PTZ support."""

    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_brand = "PNZEO"
    _attr_model = "W8"

    def __init__(self, coordinator: PNZEOCoordinator) -> None:
        PNZEOEntity.__init__(self, coordinator, "camera", "Camera")
        Camera.__init__(self)
        self._attr_is_streaming = True
        self._attr_is_on = True

    async def stream_source(self) -> str | None:
        """Return RTSP stream URL for HA stream component (WebRTC)."""
        return self.coordinator.device.rtsp_url

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a snapshot from the camera via ffmpeg."""
        import subprocess
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
