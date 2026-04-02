"""PNZEO camera device wrapper."""
from __future__ import annotations

from .const import DEFAULT_RTSP_PORT, RTSP_MAIN_STREAM, RTSP_SUB_STREAM
from .pppp_client import PNZEOClient


class PNZEODevice:
    """Represents a PNZEO camera device."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        device_id: str = "",
        rtsp_port: int = DEFAULT_RTSP_PORT,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.device_id = device_id
        self.rtsp_port = rtsp_port
        self.client = PNZEOClient(host, username, password, device_id=device_id)

    @property
    def rtsp_url(self) -> str:
        """Main RTSP stream URL."""
        return f"rtsp://{self.username}:{self.password}@{self.host}:{self.rtsp_port}{RTSP_MAIN_STREAM}"

    @property
    def rtsp_sub_url(self) -> str:
        """Sub RTSP stream URL (lower quality)."""
        return f"rtsp://{self.username}:{self.password}@{self.host}:{self.rtsp_port}{RTSP_SUB_STREAM}"

    @property
    def name(self) -> str:
        return f"PNZEO {self.device_id or self.host}"

    @property
    def unique_id(self) -> str:
        return self.device_id or self.host.replace(".", "_")

    async def async_setup(self) -> bool:
        """Connect to camera."""
        return await self.client.connect()

    async def async_teardown(self) -> None:
        """Disconnect from camera."""
        await self.client.disconnect()
