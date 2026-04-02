"""Async PPPP client for PNZEO/MTC cameras — 100% LAN, zero cloud.

How it works:
1. LAN Search (F130 broadcast) → camera responds from its P2P port
2. F141 PUNCH with UID → P2P handshake (F142/F143)
3. CGI commands via DRW → full camera control

No cloud servers, no relay, no internet needed. Everything on LAN.
"""
from __future__ import annotations

import asyncio
import logging
import struct
from typing import Any

from .pppp_packets import (
    PktType,
    build_alive, build_alive_ack, build_close,
    build_cgi_url, build_drw_cgi, build_lan_search,
    encode_uid, parse_drw_cgi_response,
    CGI_CHECK_USER, CGI_GET_PARAMS, CGI_GET_STATUS,
    CGI_CAMERA_CONTROL, CGI_REBOOT, CGI_FACTORY_RESET,
    CGI_FORMAT_SD, CGI_SNAPSHOT,
    CGI_SET_USER, CGI_SET_ALARM,
    CGI_PARAM_BRIGHTNESS, CGI_PARAM_CONTRAST, CGI_PARAM_IR_CUT,
    CGI_PARAM_STATUS_LED, CGI_PARAM_MIRROR, CGI_PARAM_RESOLUTION,
)

_LOGGER = logging.getLogger(__name__)

KEEPALIVE_INTERVAL = 3
PUNCH_COUNT = 8
PUNCH_INTERVAL = 0.1
DRW_RETRY_MAX = 20
DRW_RETRY_INTERVAL = 0.3
LAN_SEARCH_PORT = 32108
LAN_SEARCH_TIMEOUT = 3


class PNZEOClient:
    """Async PPPP client — pure LAN, zero cloud dependency."""

    def __init__(self, host: str, username: str, password: str,
                 device_id: str = "", **kwargs) -> None:
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
    # Connection — pure LAN
    # =====================================================================

    async def connect(self) -> bool:
        """Connect to camera on LAN. No cloud needed.

        1. LAN Search → discover camera's P2P port
        2. F141 PUNCH → P2P handshake
        3. CGI login → verify password
        """
        # Step 1: Discover P2P port via LAN search
        port = await self._lan_discover_port()
        if not port:
            _LOGGER.warning("Camera %s not found on LAN", self.host)
            return False
        self._cam_port = port

        # Step 2: P2P handshake
        if not await self._p2p_punch():
            _LOGGER.warning("P2P handshake failed with %s:%d", self.host, port)
            return False

        # Step 3: CGI login
        if not await self._cgi_login():
            _LOGGER.warning("CGI login failed on %s:%d", self.host, port)
            return False

        self._authenticated = True
        self._connection_method = "lan"
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        _LOGGER.info("Connected to camera %s on LAN (port %d)", self.host, port)
        return True

    async def disconnect(self) -> None:
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
    # LAN Port Discovery (no cloud)
    # =====================================================================

    async def _lan_discover_port(self) -> int | None:
        """Discover camera's P2P port via LAN Search broadcast.

        Sends F130 to port 32108, camera responds from its P2P port.
        The source port of the response IS the P2P data port.
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[int | None] = loop.create_future()

        class _DiscoverProtocol(asyncio.DatagramProtocol):
            def __init__(self, target_ip: str):
                self.target_ip = target_ip

            def datagram_received(self, data: bytes, addr: tuple) -> None:
                if addr[0] == self.target_ip and len(data) >= 4 and data[0] == 0xF1:
                    if not fut.done():
                        fut.set_result(addr[1])  # source port = P2P port

        try:
            transport, _ = await asyncio.wait_for(
                loop.create_datagram_endpoint(
                    lambda: _DiscoverProtocol(self.host),
                    local_addr=("0.0.0.0", 0),
                ),
                timeout=5,
            )
            transport.sendto(build_lan_search(), (self.host, LAN_SEARCH_PORT))

            port = await asyncio.wait_for(fut, timeout=LAN_SEARCH_TIMEOUT)
            transport.close()
            _LOGGER.debug("LAN discovered port %d for %s", port, self.host)
            return port
        except (asyncio.TimeoutError, OSError) as ex:
            _LOGGER.debug("LAN discovery failed for %s: %s", self.host, ex)
            return None

    # =====================================================================
    # P2P Punch
    # =====================================================================

    async def _p2p_punch(self) -> bool:
        """Establish P2P session via F141 punch."""
        try:
            loop = asyncio.get_running_loop()
            self._protocol = _PNZEOProtocol(self)

            self._transport, _ = await asyncio.wait_for(
                loop.create_datagram_endpoint(
                    lambda: self._protocol,
                    remote_addr=(self.host, self._cam_port),
                ),
                timeout=5,
            )

            uid = encode_uid(self.device_id)
            punch = struct.pack(">BBH", 0xF1, PktType.PUNCH_PKT, len(uid)) + uid

            self._drw_response.clear()
            for _ in range(PUNCH_COUNT):
                self._transport.sendto(punch)
                await asyncio.sleep(PUNCH_INTERVAL)

            # Wait for F142/F143
            try:
                await asyncio.wait_for(self._drw_response.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                pass

            if self._protocol and self._protocol.got_p2p_rdy:
                self._connected = True
                return True
            return False
        except Exception as ex:
            _LOGGER.debug("P2P punch failed: %s", ex)
            return False

    # =====================================================================
    # CGI Commands
    # =====================================================================

    async def _cgi_login(self) -> bool:
        """Login via check_user.cgi."""
        cgi = build_cgi_url(CGI_CHECK_USER, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            if "json" in resp:
                self._capabilities = resp["json"]
            return True
        if resp and resp.get("result") == -1:
            return False  # Wrong password
        # No response — might be OK, camera may not respond to first login
        return False

    async def login(self, username: str, password: str) -> bool:
        """Verify credentials. Returns True if accepted."""
        cgi = build_cgi_url(CGI_CHECK_USER, username, password)
        resp = await self._send_cgi(cgi)
        return bool(resp and resp.get("success"))

    async def _send_cgi(self, cgi_url: str) -> dict | None:
        """Send CGI command and wait for response."""
        if not self._connected or not self._transport:
            return None

        self._cmd_seq = (self._cmd_seq + 1) % 256
        drw = build_drw_cgi(self._cmd_seq, cgi_url)

        for _ in range(DRW_RETRY_MAX):
            self._drw_response.clear()
            self._drw_data = b""

            self._transport.sendto(drw)
            self._transport.sendto(build_alive())

            try:
                await asyncio.wait_for(
                    self._drw_response.wait(), timeout=DRW_RETRY_INTERVAL,
                )
                if self._drw_data:
                    return parse_drw_cgi_response(self._drw_data)
            except asyncio.TimeoutError:
                pass

        return None

    # =====================================================================
    # Camera control commands
    # =====================================================================

    async def get_camera_params(self) -> dict[str, Any]:
        cgi = build_cgi_url(CGI_GET_PARAMS, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            self._camera_params.update(resp)
        return self._camera_params

    async def get_status(self) -> dict[str, Any]:
        cgi = build_cgi_url(CGI_GET_STATUS, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            self._camera_params.update(resp)
        return self._camera_params

    async def camera_control(self, param: int, value: int) -> bool:
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
        cgi = build_cgi_url(
            CGI_SET_USER, self.username, self.password,
            user1=self.username, pwd1=new_password,
            user2="", pwd2="", user3="", pwd3="",
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

    def _handle_drw_response(self, data: bytes) -> None:
        self._drw_data = data
        self._drw_response.set()


class _PNZEOProtocol(asyncio.DatagramProtocol):
    """UDP protocol handler."""

    def __init__(self, client: PNZEOClient) -> None:
        self.client = client
        self.got_p2p_rdy = False

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        if len(data) < 2 or data[0] != 0xF1:
            return

        pkt_type = data[1]

        if pkt_type == PktType.DRW:
            self.client._handle_drw_response(data)

        elif pkt_type in (PktType.P2P_RDY, PktType.P2P_RDY_ACK):
            if not self.got_p2p_rdy:
                self.got_p2p_rdy = True
                self.client._drw_response.set()

        elif pkt_type == PktType.ALIVE:
            if self.client._transport:
                try:
                    self.client._transport.sendto(build_alive_ack())
                except Exception:
                    pass

        elif pkt_type == PktType.CLOSE:
            self.client._connected = False

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("UDP error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        self.client._connected = False
