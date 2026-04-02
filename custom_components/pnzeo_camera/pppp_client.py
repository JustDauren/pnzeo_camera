"""Async PPPP client for PNZEO cameras — control only (no video streaming).

Connection strategy (tried in order):
1. LAN direct on port 8600 (DH protocol) — fastest
2. LAN direct on port 32108 (standard PPPP) — fallback
3. Cloud P2P via port 32100 servers — if LAN fails

After connection is established, uses DRW packets for camera commands.
If PPPP connection fails entirely, the camera still works via RTSP for video.
"""
from __future__ import annotations

import asyncio
import logging
import struct
from typing import Any

from .const import (
    CH_CMD,
    CLOUD_P2P_SERVERS,
    CMD_SET_BRIGHTNESS, CMD_SET_CONTRAST, CMD_SET_LED, CMD_SET_LIGHT,
    CMD_SET_MIRROR, CMD_SET_RESOLUTION,
    MSG_CAMERA_CONTROL, MSG_FORMAT_SD, MSG_GET_ALARM_EX, MSG_GET_ALARM_PARAM,
    MSG_GET_CAMERA_PARAMS, MSG_GET_CAPABILITY, MSG_GET_REC_MODE,
    MSG_GET_STATUS, MSG_GET_VOICE, MSG_REBOOT, MSG_FACTORY_RESET,
    MSG_SET_ALARM_EX, MSG_SET_REC_MODE, MSG_SNAPSHOT,
    PPPP_PORT_DH_LAN, PPPP_PORT_STANDARD,
)
from .pppp_packets import (
    build_alive, build_close, build_drw, build_drw_ack,
    build_dh_discovery, build_hello, build_lan_search,
    build_p2p_connect,
    encode_camera_control, encode_command, encode_login, encode_ptz,
    decode_response, parse_drw_packet, parse_f1xx_message,
)

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10
COMMAND_TIMEOUT = 5
KEEPALIVE_INTERVAL = 20
HANDSHAKE_TIMEOUT = 5


class PNZEOClient:
    """Async PPPP client for camera control.

    Tries LAN connection first (DH port 8600, then PPPP port 32108),
    then falls back to cloud P2P relay.
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        device_id: str = "",
        port: int = PPPP_PORT_DH_LAN,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.device_id = device_id
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: _PNZEOProtocol | None = None
        self._connected = False
        self._authenticated = False
        self._keepalive_task: asyncio.Task | None = None
        self._cmd_index = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._state: dict[str, Any] = {}
        self._connection_method: str = "none"
        # Event for handshake completion
        self._handshake_event = asyncio.Event()
        self._handshake_result: dict | None = None

    @property
    def connected(self) -> bool:
        return self._connected and self._authenticated

    @property
    def state(self) -> dict[str, Any]:
        return self._state

    @property
    def connection_method(self) -> str:
        """How we connected: 'dh_lan', 'pppp_lan', 'cloud_p2p', or 'none'."""
        return self._connection_method

    async def connect(self) -> bool:
        """Connect and authenticate with camera.

        Tries multiple connection methods in order:
        1. LAN DH on port 8600
        2. LAN PPPP on port 32108
        3. Cloud P2P via port 32100 servers
        """
        # Method 1: LAN DH on port 8600
        if await self._try_lan_connect(PPPP_PORT_DH_LAN, "dh_lan"):
            return True

        # Method 2: LAN PPPP on port 32108
        if await self._try_lan_connect(PPPP_PORT_STANDARD, "pppp_lan"):
            return True

        # Method 3: Cloud P2P
        if self.device_id:
            if await self._try_cloud_p2p():
                return True

        _LOGGER.warning(
            "All PPPP connection methods failed for %s. "
            "Camera will still work via RTSP for video.",
            self.host,
        )
        return False

    async def _try_lan_connect(self, port: int, method_name: str) -> bool:
        """Try to connect to camera on LAN via specified port."""
        _LOGGER.debug("Trying %s connection to %s:%d", method_name, self.host, port)
        try:
            await self._cleanup_transport()
            loop = asyncio.get_event_loop()
            self._protocol = _PNZEOProtocol(self)
            self._handshake_event.clear()
            self._handshake_result = None

            self._transport, _ = await asyncio.wait_for(
                loop.create_datagram_endpoint(
                    lambda: self._protocol,
                    remote_addr=(self.host, port),
                ),
                timeout=CONNECT_TIMEOUT,
            )

            # Send appropriate discovery/hello based on port
            if port == PPPP_PORT_DH_LAN:
                self._transport.sendto(build_dh_discovery())
            else:
                self._transport.sendto(build_lan_search())

            # Wait briefly for any response
            try:
                await asyncio.wait_for(self._handshake_event.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                # No response on this port, try next method
                _LOGGER.debug("No response on %s:%d", self.host, port)
                await self._cleanup_transport()
                return False

            self._connected = True
            self.port = port
            self._connection_method = method_name

            # Authenticate
            if await self._authenticate():
                self._keepalive_task = asyncio.create_task(self._keepalive_loop())
                _LOGGER.info(
                    "Connected to PNZEO camera at %s:%d via %s",
                    self.host, port, method_name,
                )
                return True
            else:
                _LOGGER.debug("Auth failed on %s:%d", self.host, port)
                await self._cleanup_transport()
                return False

        except Exception as ex:
            _LOGGER.debug("%s connection to %s:%d failed: %s", method_name, self.host, port, ex)
            await self._cleanup_transport()
            return False

    async def _try_cloud_p2p(self) -> bool:
        """Try to connect via cloud P2P relay servers."""
        for server_host, server_port in CLOUD_P2P_SERVERS:
            _LOGGER.debug("Trying cloud P2P via %s:%d", server_host, server_port)
            try:
                await self._cleanup_transport()
                loop = asyncio.get_event_loop()
                self._protocol = _PNZEOProtocol(self)
                self._handshake_event.clear()
                self._handshake_result = None

                self._transport, _ = await asyncio.wait_for(
                    loop.create_datagram_endpoint(
                        lambda: self._protocol,
                        remote_addr=(server_host, server_port),
                    ),
                    timeout=CONNECT_TIMEOUT,
                )

                # Step 1: Hello
                self._transport.sendto(build_hello())

                # Wait for Hello ACK
                try:
                    await asyncio.wait_for(self._handshake_event.wait(), timeout=HANDSHAKE_TIMEOUT)
                except asyncio.TimeoutError:
                    _LOGGER.debug("No hello ack from %s:%d", server_host, server_port)
                    await self._cleanup_transport()
                    continue

                hello_result = self._handshake_result
                if not hello_result or hello_result.get("type") != "hello_ack":
                    _LOGGER.debug("Unexpected response from %s:%d", server_host, server_port)
                    await self._cleanup_transport()
                    continue

                # Step 2: P2P Connect with UID
                self._handshake_event.clear()
                self._handshake_result = None
                self._transport.sendto(build_p2p_connect(self.device_id))

                # Wait for DRW Response (0xF140) with camera IPs
                try:
                    await asyncio.wait_for(self._handshake_event.wait(), timeout=HANDSHAKE_TIMEOUT)
                except asyncio.TimeoutError:
                    _LOGGER.debug("No P2P response from %s:%d", server_host, server_port)
                    await self._cleanup_transport()
                    continue

                p2p_result = self._handshake_result
                if p2p_result and p2p_result.get("type") in ("drw_response", "p2p_ready"):
                    # Extract camera LAN IP if available
                    lan_ip = p2p_result.get("lan_ip")
                    if lan_ip and lan_ip != self.host:
                        _LOGGER.info("Cloud P2P returned LAN IP: %s", lan_ip)

                    # If we got a P2P ready, we can send commands through relay
                    self._connected = True
                    self._connection_method = "cloud_p2p"

                    if await self._authenticate():
                        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
                        _LOGGER.info(
                            "Connected to PNZEO camera via cloud P2P (%s:%d)",
                            server_host, server_port,
                        )
                        return True

                await self._cleanup_transport()

            except Exception as ex:
                _LOGGER.debug("Cloud P2P via %s:%d failed: %s", server_host, server_port, ex)
                await self._cleanup_transport()
                continue

        return False

    async def _authenticate(self) -> bool:
        """Send login + get_capability to authenticate."""
        if not self._transport:
            return False
        try:
            login_data = encode_login(self.username, self.password)
            cmd = encode_command(MSG_GET_CAPABILITY, login_data)
            self._send_cmd(cmd)
            # Brief wait for auth response
            await asyncio.sleep(1.5)
            self._authenticated = True
            return True
        except Exception as ex:
            _LOGGER.debug("Authentication error: %s", ex)
            return False

    async def _cleanup_transport(self) -> None:
        """Clean up current transport without full disconnect."""
        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None
        self._protocol = None
        self._connected = False
        self._authenticated = False

    async def disconnect(self) -> None:
        """Disconnect from camera."""
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
            self._keepalive_task = None
        if self._transport:
            try:
                self._transport.sendto(build_close())
            except Exception:
                pass
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None
        self._connected = False
        self._authenticated = False
        self._connection_method = "none"

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

    def _send_cmd(self, data: bytes, channel: int = CH_CMD) -> None:
        """Send command packet via DRW."""
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

    # ===== Handshake callback (called by protocol) =====

    def _handle_handshake_message(self, data: bytes) -> None:
        """Handle F1xx handshake messages during connection setup."""
        result = parse_f1xx_message(data)
        if result:
            _LOGGER.debug("Handshake message: %s", result.get("type", "unknown"))
            self._handshake_result = result
            self._handshake_event.set()

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
        param = struct.pack("<B", 1 if enabled else 0)
        return await self.send_command(MSG_SET_ALARM_EX, param)

    async def set_recording_mode(self, mode: int) -> bool:
        """Set SD recording mode (0=off, 1=continuous, 2=alarm)."""
        param = struct.pack("<BB", mode, 0)
        return await self.send_command(MSG_SET_REC_MODE, param)

    def _handle_response(self, data: bytes) -> None:
        """Handle incoming response data from DRW payload."""
        if len(data) < 4:
            return
        msg_type, payload = decode_response(data)
        _LOGGER.debug("Response msg_type=%d payload_len=%d", msg_type, len(payload))
        # Store in state dict for coordinator to read
        self._state[f"msg_{msg_type}"] = payload
        self._state["last_response"] = msg_type


class _PNZEOProtocol(asyncio.DatagramProtocol):
    """UDP protocol handler for PPPP.

    Handles both F1xx signaling messages (during handshake) and
    DRW data packets (after connection established).
    """

    def __init__(self, client: PNZEOClient) -> None:
        self.client = client

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        """Handle incoming UDP packet."""
        if len(data) < 2:
            return

        first_byte = data[0]

        # F1xx signaling messages (2-byte msg type, big-endian)
        if first_byte == 0xF1 and len(data) >= 2:
            second_byte = data[1]

            # Check if this is a F1xx signaling message (second byte 0x00-0x80+)
            # vs a data-layer packet (second byte is PktType like 0xD0, 0xE0, etc.)
            if second_byte in (0x00, 0x01, 0x20, 0x21, 0x40, 0x67, 0x80):
                # F1xx handshake message
                self.client._handle_handshake_message(data)
                return

            if second_byte == 0xD0:  # DRW - data packet
                # Extract payload after DRW header
                # Header: magic(1) + type(1) + channel(1) + index(2) + size(2) = 7 bytes
                if len(data) > 7:
                    channel = data[2]
                    index = struct.unpack(">H", data[3:5])[0]
                    payload = data[7:]
                    # Send ACK
                    if self.client._transport:
                        try:
                            self.client._transport.sendto(build_drw_ack(channel, index))
                        except Exception:
                            pass
                    self.client._handle_response(payload)

            elif second_byte == 0xE1:  # ALIVE_ACK
                pass  # keepalive confirmed

            elif second_byte == 0xD1:  # DRW_ACK
                pass  # command acknowledged

            elif second_byte == 0xE0:  # ALIVE from camera
                # Respond with ALIVE_ACK
                if self.client._transport:
                    try:
                        ack = struct.pack(">BBH", 0xF1, 0xE1, 0)
                        self.client._transport.sendto(ack)
                    except Exception:
                        pass

        # DH protocol responses (starts with 44 48)
        elif first_byte == 0x44 and len(data) >= 4 and data[1] == 0x48:
            _LOGGER.debug("DH response from %s: %d bytes", addr, len(data))
            # Treat as successful handshake response
            self.client._handshake_result = {"type": "dh_response", "data": data}
            self.client._handshake_event.set()

        else:
            _LOGGER.debug("Unknown packet from %s: %s", addr, data[:8].hex())
            # Could be a handshake response in unexpected format
            if not self.client._connected:
                self.client._handshake_result = {"type": "unknown", "data": data}
                self.client._handshake_event.set()

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("UDP error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        self.client._connected = False
