"""Async PPPP client for PNZEO cameras — control only (no video streaming)."""
from __future__ import annotations

import asyncio
import logging
import struct
from typing import Any

from .const import (
    CMD_SET_BRIGHTNESS, CMD_SET_CONTRAST, CMD_SET_LED, CMD_SET_LIGHT,
    CMD_SET_MIRROR, CMD_SET_RESOLUTION, MSG_CAMERA_CONTROL,
    MSG_FORMAT_SD, MSG_GET_ALARM_EX, MSG_GET_ALARM_PARAM,
    MSG_GET_CAMERA_PARAMS, MSG_GET_CAPABILITY, MSG_GET_REC_MODE,
    MSG_GET_STATUS, MSG_GET_VOICE, MSG_REBOOT, MSG_FACTORY_RESET,
    MSG_SET_ALARM_EX, MSG_SET_REC_MODE, MSG_SNAPSHOT,
)
from .pppp_packets import (
    build_alive, build_close, build_drw, encode_camera_control,
    encode_command, encode_login, encode_ptz, decode_response,
)

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10
COMMAND_TIMEOUT = 5
KEEPALIVE_INTERVAL = 20


class PNZEOClient:
    """Async PPPP client for camera control."""

    def __init__(self, host: str, username: str, password: str, port: int = 32108) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: _PNZEOProtocol | None = None
        self._connected = False
        self._authenticated = False
        self._keepalive_task: asyncio.Task | None = None
        self._cmd_index = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._state: dict[str, Any] = {}

    @property
    def connected(self) -> bool:
        return self._connected and self._authenticated

    @property
    def state(self) -> dict[str, Any]:
        return self._state

    async def connect(self) -> bool:
        """Connect and authenticate with camera."""
        try:
            loop = asyncio.get_event_loop()
            self._protocol = _PNZEOProtocol(self)
            self._transport, _ = await asyncio.wait_for(
                loop.create_datagram_endpoint(
                    lambda: self._protocol,
                    remote_addr=(self.host, self.port),
                ),
                timeout=CONNECT_TIMEOUT,
            )
            self._connected = True

            # Send login
            login_data = encode_login(self.username, self.password)
            cmd = encode_command(MSG_GET_CAPABILITY, login_data)
            self._send_cmd(cmd)

            # Wait for auth response
            await asyncio.sleep(2)
            self._authenticated = True

            # Start keepalive
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())

            _LOGGER.info("Connected to PNZEO camera at %s", self.host)
            return True

        except Exception as ex:
            _LOGGER.error("Connection failed: %s", ex)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from camera."""
        if self._keepalive_task:
            self._keepalive_task.cancel()
            self._keepalive_task = None
        if self._transport:
            try:
                self._transport.sendto(build_close())
            except Exception:
                pass
            self._transport.close()
            self._transport = None
        self._connected = False
        self._authenticated = False

    async def _keepalive_loop(self) -> None:
        """Send periodic keepalive packets."""
        while self._connected:
            try:
                if self._transport:
                    self._transport.sendto(build_alive())
                await asyncio.sleep(KEEPALIVE_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    def _send_cmd(self, data: bytes, channel: int = 0) -> None:
        """Send command packet."""
        if not self._transport:
            return
        self._cmd_index += 1
        pkt = build_drw(channel, data, self._cmd_index)
        self._transport.sendto(pkt)

    async def send_command(self, msg_type: int, params: bytes = b"") -> bool:
        """Send a command to camera."""
        if not self._connected:
            return False
        try:
            cmd = encode_command(msg_type, params)
            self._send_cmd(cmd)
            return True
        except Exception as ex:
            _LOGGER.error("Send command error: %s", ex)
            return False

    # ===== High-level commands =====

    async def get_status(self) -> dict[str, Any]:
        """Get camera status (firmware, SD card, etc.)."""
        await self.send_command(MSG_GET_STATUS)
        await asyncio.sleep(0.5)
        return self._state

    async def get_camera_params(self) -> dict[str, Any]:
        """Get camera image params (brightness, contrast, resolution, etc.)."""
        await self.send_command(MSG_GET_CAMERA_PARAMS)
        await asyncio.sleep(0.5)
        return self._state

    async def get_capability(self) -> dict[str, Any]:
        """Get device capabilities."""
        await self.send_command(MSG_GET_CAPABILITY)
        await asyncio.sleep(0.5)
        return self._state

    async def reboot(self) -> bool:
        """Reboot camera."""
        return await self.send_command(MSG_REBOOT)

    async def factory_reset(self) -> bool:
        """Factory reset camera."""
        return await self.send_command(MSG_FACTORY_RESET)

    async def snapshot(self) -> bool:
        """Take snapshot."""
        return await self.send_command(MSG_SNAPSHOT)

    async def format_sd(self) -> bool:
        """Format SD card."""
        return await self.send_command(MSG_FORMAT_SD)

    async def set_brightness(self, value: int) -> bool:
        """Set brightness (0-255)."""
        params = encode_camera_control(CMD_SET_BRIGHTNESS, value)
        return await self.send_command(MSG_CAMERA_CONTROL, params)

    async def set_contrast(self, value: int) -> bool:
        """Set contrast (0-255)."""
        params = encode_camera_control(CMD_SET_CONTRAST, value)
        return await self.send_command(MSG_CAMERA_CONTROL, params)

    async def set_resolution(self, value: int) -> bool:
        """Set resolution (0=640p, 1=720p, 2=1080p)."""
        params = encode_camera_control(CMD_SET_RESOLUTION, value)
        return await self.send_command(MSG_CAMERA_CONTROL, params)

    async def set_mirror(self, mode: int) -> bool:
        """Set mirror mode (0=normal, 1=vertical, 2=horizontal, 3=both)."""
        params = encode_camera_control(CMD_SET_MIRROR, mode)
        return await self.send_command(MSG_CAMERA_CONTROL, params)

    async def set_ir_led(self, on: bool) -> bool:
        """Toggle IR LED."""
        params = encode_camera_control(CMD_SET_LIGHT, 1 if on else 0)
        return await self.send_command(MSG_CAMERA_CONTROL, params)

    async def set_indicator_led(self, on: bool) -> bool:
        """Toggle indicator LED."""
        params = encode_camera_control(CMD_SET_LED, 1 if on else 0)
        return await self.send_command(MSG_CAMERA_CONTROL, params)

    async def ptz_control(self, direction: int, step: int = 1) -> bool:
        """PTZ control."""
        params = encode_ptz(direction, step)
        return await self.send_command(MSG_GET_CAMERA_PARAMS, params)

    async def set_motion_detection(self, enabled: bool) -> bool:
        """Enable/disable motion detection."""
        # Simplified: send alarm ex setting with enable/disable
        param = struct.pack("<B", 1 if enabled else 0)
        return await self.send_command(MSG_SET_ALARM_EX, param)

    async def set_recording_mode(self, mode: int) -> bool:
        """Set SD recording mode (0=off, 1=continuous, 2=alarm)."""
        param = struct.pack("<BB", mode, 0)
        return await self.send_command(MSG_SET_REC_MODE, param)

    def _handle_response(self, data: bytes) -> None:
        """Handle incoming response data."""
        if len(data) < 4:
            return
        msg_type, payload = decode_response(data)
        _LOGGER.debug("Response msg_type=%d payload_len=%d", msg_type, len(payload))
        # Store in state dict for coordinator to read
        self._state[f"msg_{msg_type}"] = payload
        self._state["last_response"] = msg_type


class _PNZEOProtocol(asyncio.DatagramProtocol):
    """UDP protocol handler for PPPP."""

    def __init__(self, client: PNZEOClient) -> None:
        self.client = client

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        """Handle incoming UDP packet."""
        if len(data) < 4:
            return
        # Parse packet header
        magic = data[0]
        pkt_type = data[1]

        if pkt_type == 0xD0:  # DRW - data packet
            # Extract payload after DRW header (7 bytes: magic+type+channel+index+size)
            if len(data) > 7:
                payload = data[7:]
                self.client._handle_response(payload)
        elif pkt_type == 0xE1:  # ALIVE_ACK
            pass  # keepalive confirmed
        elif pkt_type == 0xD1:  # DRW_ACK
            pass  # command acknowledged

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("UDP error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        self.client._connected = False
