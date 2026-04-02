"""Async PPPP client for PNZEO/MTC cameras — full LAN control via CGI.

How it works (fully automatic):
1. One UDP query to cloud P2P server → get camera's session port
2. F141 PUNCH to camera on LAN → P2P handshake (F142/F143)
3. DRW packets with CGI commands → full camera control on LAN
4. All actual data stays on LAN, cloud only used for port discovery

Camera uses HTTP-like CGI commands inside DRW packets:
  GET /check_user.cgi?loginuse=admin&loginpas=XXX&...
  GET /camera_control.cgi?param=14&value=1&...
  GET /get_camera_params.cgi?...
"""
from __future__ import annotations

import asyncio
import logging
import socket
import struct
from typing import Any

from .const import (
    CLOUD_P2P_SERVERS,
    PPPP_PORT_STANDARD,
)
from .pppp_packets import (
    PktType,
    build_alive, build_alive_ack, build_close,
    build_cgi_url, build_drw_cgi, build_lan_search,
    encode_uid,
    parse_drw_cgi_response, parse_f1xx_header,
    CGI_CHECK_USER, CGI_GET_PARAMS, CGI_GET_STATUS,
    CGI_CAMERA_CONTROL, CGI_REBOOT, CGI_FACTORY_RESET,
    CGI_FORMAT_SD, CGI_SNAPSHOT, CGI_SET_DATETIME,
    CGI_SET_USER, CGI_GET_USER, CGI_SET_ALARM, CGI_GET_ALARM,
    CGI_PARAM_BRIGHTNESS, CGI_PARAM_CONTRAST, CGI_PARAM_IR_CUT,
    CGI_PARAM_STATUS_LED, CGI_PARAM_MIRROR, CGI_PARAM_RESOLUTION,
)

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10
COMMAND_TIMEOUT = 8
KEEPALIVE_INTERVAL = 3
PUNCH_COUNT = 12
PUNCH_INTERVAL = 0.15
DRW_RETRY_MAX = 25
DRW_RETRY_INTERVAL = 0.4
CLOUD_PORT = 32100


class PNZEOClient:
    """Async PPPP client — connects to camera on LAN via P2P punch.

    Port discovered from cloud (one quick UDP query), then everything on LAN.
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        device_id: str = "",
        **kwargs,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.device_id = device_id
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: _PNZEOProtocol | None = None
        self._connected = False
        self._authenticated = False
        self._keepalive_task: asyncio.Task | None = None
        self._cam_port: int = 0
        self._cmd_seq = 0
        self._connection_method = "none"
        self._capabilities: dict = {}
        self._camera_params: dict = {}
        # Async response handling
        self._drw_response: asyncio.Event = asyncio.Event()
        self._drw_data: bytes = b""

    @property
    def connected(self) -> bool:
        return self._connected and self._authenticated

    @property
    def state(self) -> dict[str, Any]:
        return self._camera_params

    @property
    def connection_method(self) -> str:
        return self._connection_method

    @property
    def capabilities(self) -> dict:
        return self._capabilities

    # =====================================================================
    # Connection
    # =====================================================================

    async def connect(self) -> bool:
        """Connect to camera: discover port → P2P punch → login."""
        # Step 1: Get camera's P2P port from cloud
        if self.device_id:
            port = await self._discover_port()
            if port:
                self._cam_port = port
                _LOGGER.debug("Camera P2P port: %d", port)

        if not self._cam_port:
            _LOGGER.warning("Could not discover camera P2P port")
            return False

        # Step 2: P2P handshake on LAN
        if not await self._p2p_punch():
            return False

        # Step 3: Login via CGI
        if not await self._cgi_login():
            return False

        self._authenticated = True
        self._connection_method = "lan_p2p"
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        _LOGGER.info("Connected to camera %s on LAN (port %d)", self.host, self._cam_port)
        return True

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

    # =====================================================================
    # Port Discovery (one UDP query to cloud)
    # =====================================================================

    async def _discover_port(self) -> int | None:
        """Get camera's P2P session port from cloud server.

        Sends Hello + P2P_REQ to cloud, receives F140 with camera's LAN IP:port.
        This is the ONLY cloud interaction — all data stays on LAN after this.
        """
        uid = encode_uid(self.device_id)

        for server_host, server_port in CLOUD_P2P_SERVERS:
            try:
                loop = asyncio.get_event_loop()
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setblocking(False)
                sock.settimeout(0)

                # Hello
                hello = struct.pack(">BBH", 0xF1, 0x00, 0)
                sock.sendto(hello, (server_host, server_port))

                # Wait for Hello ACK
                if not await self._udp_wait(sock, 0x01, 3.0):
                    sock.close()
                    continue

                # P2P Connect
                p2p_payload = uid + b"\x00" * 16
                p2p = struct.pack(">BBH", 0xF1, 0x20, len(p2p_payload)) + p2p_payload
                sock.sendto(p2p, (server_host, server_port))

                # Wait for F140 (PUNCH_TO) with camera's LAN IP
                for _ in range(8):
                    data = await self._udp_recv(sock, 3.0)
                    if not data or len(data) < 12:
                        continue
                    if data[0] == 0xF1 and data[1] == 0x40:
                        # Parse sockaddr_in_le: AF(2 BE) + port(2 LE) + IP(4 LE)
                        payload = data[4:]
                        if len(payload) >= 8:
                            port = struct.unpack("<H", payload[2:4])[0]
                            ip_val = struct.unpack("<I", payload[4:8])[0]
                            ip = socket.inet_ntoa(struct.pack("!I", ip_val))
                            if ip == self.host:
                                sock.close()
                                return port

                sock.close()
            except Exception as ex:
                _LOGGER.debug("Port discovery via %s failed: %s", server_host, ex)
                try:
                    sock.close()
                except Exception:
                    pass

        return None

    async def _udp_wait(self, sock: socket.socket, expected_type: int, timeout: float) -> bool:
        """Wait for a specific F1xx response on a raw socket."""
        data = await self._udp_recv(sock, timeout)
        return data is not None and len(data) >= 2 and data[1] == expected_type

    async def _udp_recv(self, sock: socket.socket, timeout: float) -> bytes | None:
        """Async receive on a raw UDP socket."""
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self._blocking_recv(sock, timeout)),
                timeout=timeout + 1,
            )
        except (asyncio.TimeoutError, Exception):
            return None

    @staticmethod
    def _blocking_recv(sock: socket.socket, timeout: float) -> bytes | None:
        """Blocking receive with timeout."""
        import select
        ready, _, _ = select.select([sock], [], [], timeout)
        if ready:
            data, _ = sock.recvfrom(4096)
            return data
        return None

    # =====================================================================
    # P2P Punch (LAN handshake)
    # =====================================================================

    async def _p2p_punch(self) -> bool:
        """Establish P2P session via F141 punch on LAN."""
        try:
            loop = asyncio.get_event_loop()
            self._protocol = _PNZEOProtocol(self)

            self._transport, _ = await asyncio.wait_for(
                loop.create_datagram_endpoint(
                    lambda: self._protocol,
                    remote_addr=(self.host, self._cam_port),
                ),
                timeout=CONNECT_TIMEOUT,
            )

            uid = encode_uid(self.device_id)
            punch = struct.pack(">BBH", 0xF1, PktType.PUNCH_PKT, len(uid)) + uid

            # Send burst of F141 punches (camera needs multiple)
            for _ in range(PUNCH_COUNT):
                self._transport.sendto(punch)
                await asyncio.sleep(PUNCH_INTERVAL)

            # Wait for F142 or F143 (P2P_RDY or P2P_RDY_ACK)
            try:
                await asyncio.wait_for(self._drw_response.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass

            # Check if we got handshake response
            if self._protocol and self._protocol.got_p2p_rdy:
                self._connected = True
                _LOGGER.debug("P2P handshake OK on %s:%d", self.host, self._cam_port)
                return True

            _LOGGER.debug("No P2P handshake response from %s:%d", self.host, self._cam_port)
            return False

        except Exception as ex:
            _LOGGER.debug("P2P punch failed: %s", ex)
            return False

    # =====================================================================
    # CGI Commands
    # =====================================================================

    async def _cgi_login(self) -> bool:
        """Login via check_user.cgi. Returns True on success."""
        cgi = build_cgi_url(CGI_CHECK_USER, self.username, self.password)
        response = await self._send_cgi(cgi)
        if response and response.get("success"):
            # Parse capabilities from JSON response
            if "json" in response:
                self._capabilities = response["json"]
            _LOGGER.debug("CGI login successful")
            return True
        _LOGGER.debug("CGI login failed: %s", response)
        return False

    async def login(self, username: str, password: str) -> bool:
        """Verify credentials. Returns True if accepted."""
        cgi = build_cgi_url(CGI_CHECK_USER, username, password)
        response = await self._send_cgi(cgi)
        return bool(response and response.get("success"))

    async def _send_cgi(self, cgi_url: str) -> dict | None:
        """Send CGI command and wait for response.

        Retries during F142 flood (camera needs time to switch to data mode).
        """
        if not self._connected or not self._transport:
            return None

        self._cmd_seq = (self._cmd_seq + 1) % 256
        drw = build_drw_cgi(self._cmd_seq, cgi_url)

        for attempt in range(DRW_RETRY_MAX):
            self._drw_response.clear()
            self._drw_data = b""

            self._transport.sendto(drw)
            self._transport.sendto(build_alive())

            try:
                await asyncio.wait_for(self._drw_response.wait(), timeout=DRW_RETRY_INTERVAL)
                if self._drw_data:
                    return parse_drw_cgi_response(self._drw_data)
            except asyncio.TimeoutError:
                pass

        _LOGGER.debug("CGI command timeout after %d retries: %s", DRW_RETRY_MAX, cgi_url[:60])
        return None

    # =====================================================================
    # High-level camera commands
    # =====================================================================

    async def get_camera_params(self) -> dict[str, Any]:
        """Get camera image parameters (brightness, contrast, etc.)."""
        cgi = build_cgi_url(CGI_GET_PARAMS, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            self._camera_params.update(resp)
        return self._camera_params

    async def get_status(self) -> dict[str, Any]:
        """Get camera status (firmware, SD card, WiFi, etc.)."""
        cgi = build_cgi_url(CGI_GET_STATUS, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            self._camera_params.update(resp)
        return self._camera_params

    async def camera_control(self, param: int, value: int) -> bool:
        """Send camera_control.cgi with param=X&value=Y."""
        cgi = build_cgi_url(
            CGI_CAMERA_CONTROL, self.username, self.password,
            param=param, value=value,
        )
        resp = await self._send_cgi(cgi)
        return bool(resp and resp.get("success"))

    async def set_brightness(self, value: int) -> bool:
        return await self.camera_control(CGI_PARAM_BRIGHTNESS, value)

    async def set_contrast(self, value: int) -> bool:
        return await self.camera_control(CGI_PARAM_CONTRAST, value)

    async def set_ir_led(self, on: bool) -> bool:
        return await self.camera_control(CGI_PARAM_IR_CUT, 1 if on else 0)

    async def set_indicator_led(self, on: bool) -> bool:
        return await self.camera_control(CGI_PARAM_STATUS_LED, 1 if on else 0)

    async def set_resolution(self, value: int) -> bool:
        return await self.camera_control(CGI_PARAM_RESOLUTION, value)

    async def set_mirror(self, mode: int) -> bool:
        return await self.camera_control(CGI_PARAM_MIRROR, mode)

    async def reboot(self) -> bool:
        cgi = build_cgi_url(CGI_REBOOT, self.username, self.password)
        resp = await self._send_cgi(cgi)
        return bool(resp and resp.get("success"))

    async def factory_reset(self) -> bool:
        cgi = build_cgi_url(CGI_FACTORY_RESET, self.username, self.password)
        resp = await self._send_cgi(cgi)
        return bool(resp and resp.get("success"))

    async def format_sd(self) -> bool:
        cgi = build_cgi_url(CGI_FORMAT_SD, self.username, self.password)
        resp = await self._send_cgi(cgi)
        return bool(resp and resp.get("success"))

    async def snapshot(self) -> bool:
        cgi = build_cgi_url(CGI_SNAPSHOT, self.username, self.password)
        resp = await self._send_cgi(cgi)
        return bool(resp and resp.get("success"))

    async def change_password(self, new_password: str) -> bool:
        """Change camera password."""
        cgi = build_cgi_url(
            CGI_SET_USER, self.username, self.password,
            user1=self.username, pwd1=new_password,
            user2="", pwd2="",
            user3="", pwd3="",
        )
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            self.password = new_password
            return True
        return False

    async def set_motion_detection(self, enabled: bool) -> bool:
        cgi = build_cgi_url(
            CGI_SET_ALARM, self.username, self.password,
            motion_armed=1 if enabled else 0,
        )
        resp = await self._send_cgi(cgi)
        return bool(resp and resp.get("success"))

    async def set_recording_mode(self, mode: int) -> bool:
        cgi = build_cgi_url(
            "set_record_param.cgi", self.username, self.password,
            rec_mode=mode,
        )
        resp = await self._send_cgi(cgi)
        return bool(resp and resp.get("success"))

    async def ptz_control(self, direction: int, step: int = 1) -> bool:
        """PTZ control (if camera supports it)."""
        cgi = build_cgi_url(
            "decoder_control.cgi", self.username, self.password,
            command=direction, onestep=step,
        )
        resp = await self._send_cgi(cgi)
        return bool(resp and resp.get("success"))

    # =====================================================================
    # Keepalive
    # =====================================================================

    async def _keepalive_loop(self) -> None:
        while self._connected:
            try:
                if self._transport:
                    self._transport.sendto(build_alive())
                await asyncio.sleep(KEEPALIVE_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    # =====================================================================
    # Response handler (called by protocol)
    # =====================================================================

    def _handle_drw_response(self, data: bytes) -> None:
        """Handle incoming DRW DATA response."""
        self._drw_data = data
        self._drw_response.set()


class _PNZEOProtocol(asyncio.DatagramProtocol):
    """UDP protocol — handles P2P handshake and DRW responses."""

    def __init__(self, client: PNZEOClient) -> None:
        self.client = client
        self.got_p2p_rdy = False

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        if len(data) < 2 or data[0] != 0xF1:
            return

        pkt_type = data[1]

        if pkt_type == PktType.DRW:
            # DRW DATA response from camera
            self.client._handle_drw_response(data)

        elif pkt_type == PktType.DRW_ACK:
            pass  # Command acknowledged, wait for DATA

        elif pkt_type in (PktType.P2P_RDY, PktType.P2P_RDY_ACK):
            # P2P handshake success
            if not self.got_p2p_rdy:
                self.got_p2p_rdy = True
                self.client._drw_response.set()

        elif pkt_type == PktType.ALIVE:
            if self.client._transport:
                try:
                    self.client._transport.sendto(build_alive_ack())
                except Exception:
                    pass

        elif pkt_type == PktType.ALIVE_ACK:
            pass

        elif pkt_type == PktType.CLOSE:
            self.client._connected = False

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("UDP error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        self.client._connected = False
