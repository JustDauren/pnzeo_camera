"""Async PPPP client for PNZEO/MTC cameras — 100% LAN, zero cloud.

How it works:
1. LAN Search (F130 → 32108) → camera responds from its P2P port
2. F141 PUNCH with UID → same socket → P2P handshake (F142/F143)
3. CGI commands via DRW → same socket → full camera control

No cloud, no relay, no internet. Single UDP socket for entire session.
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
PUNCH_COUNT = 15       # Camera needs persistent punching
PUNCH_INTERVAL = 0.12
DRW_RETRY_MAX = 25
DRW_RETRY_INTERVAL = 0.3
LAN_SEARCH_PORT = 32108
PUNCH_WAIT = 5.0       # Wait for P2P handshake response


class PNZEOClient:
    """Async PPPP client — pure LAN, zero cloud dependency.

    Uses a SINGLE unconnected UDP socket for the entire lifecycle:
    discovery → punch → keepalive → commands.
    """

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
    # Connection — single socket, pure LAN
    # =====================================================================

    async def connect(self) -> bool:
        """Connect to camera. Single UDP socket for everything.

        Retries once if first attempt fails (camera may need time
        to release previous session after HA restart).
        """
        for attempt in range(2):
            result = await self._do_connect()
            if result:
                return True
            if attempt == 0:
                _LOGGER.debug("First connect attempt failed, retrying in 3s...")
                await asyncio.sleep(3)
        return False

    async def _do_connect(self) -> bool:
        """Single connection attempt."""
        try:
            await self._cleanup()
            loop = asyncio.get_running_loop()
            self._protocol = _PNZEOProtocol(self)

            # Create ONE unconnected UDP socket (can send to any addr)
            self._transport, _ = await asyncio.wait_for(
                loop.create_datagram_endpoint(
                    lambda: self._protocol,
                    local_addr=("0.0.0.0", 0),
                ),
                timeout=5,
            )

            # Step 1: LAN Search → discover P2P port
            self._drw_response.clear()
            self._transport.sendto(
                build_lan_search(), (self.host, LAN_SEARCH_PORT),
            )
            try:
                await asyncio.wait_for(self._drw_response.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                _LOGGER.warning("Camera %s not found on LAN", self.host)
                await self._cleanup()
                return False

            if not self._cam_port:
                _LOGGER.warning("No P2P port discovered for %s", self.host)
                await self._cleanup()
                return False

            _LOGGER.warning(
                "PPPP DEBUG: discovered port %d for %s, our socket=%s, punching...",
                self._cam_port, self.host,
                self._transport.get_extra_info('sockname') if self._transport else '?',
            )
            target = (self.host, self._cam_port)

            # Step 2: F141 PUNCH → P2P handshake (same socket!)
            uid = encode_uid(self.device_id)
            punch = struct.pack(">BBH", 0xF1, PktType.PUNCH_PKT, len(uid)) + uid

            self._drw_response.clear()
            self._protocol.got_p2p_rdy = False

            # Send punches interleaved with keepalive
            for i in range(PUNCH_COUNT):
                self._transport.sendto(punch, target)
                if i % 3 == 2:
                    self._transport.sendto(build_alive(), target)
                await asyncio.sleep(PUNCH_INTERVAL)
                if self._protocol.got_p2p_rdy:
                    _LOGGER.warning("PPPP DEBUG: P2P handshake OK after %d punches!", i + 1)
                    break

            # Wait more if not yet ready
            if not self._protocol.got_p2p_rdy:
                try:
                    await asyncio.wait_for(
                        self._drw_response.wait(), timeout=PUNCH_WAIT,
                    )
                except asyncio.TimeoutError:
                    pass

            if not self._protocol.got_p2p_rdy:
                _LOGGER.warning(
                    "P2P handshake failed with %s:%d", self.host, self._cam_port,
                )
                await self._cleanup()
                return False

            self._connected = True

            # Step 3: CGI login (same socket!)
            if not await self._cgi_login():
                _LOGGER.warning("CGI login failed on %s:%d", self.host, self._cam_port)
                await self._cleanup()
                return False

            self._authenticated = True
            self._connection_method = "lan"
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())
            _LOGGER.info(
                "Connected to camera %s on LAN (port %d)", self.host, self._cam_port,
            )
            return True

        except Exception as ex:
            _LOGGER.debug("Connection failed: %s", ex)
            await self._cleanup()
            return False

    async def disconnect(self) -> None:
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
            self._keepalive_task = None
        if self._transport and self._cam_port:
            try:
                self._transport.sendto(
                    build_close(), (self.host, self._cam_port),
                )
            except Exception:
                pass
        await self._cleanup()

    async def _cleanup(self) -> None:
        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None
        self._protocol = None
        self._connected = False
        self._authenticated = False
        self._connection_method = "none"

    # =====================================================================
    # CGI Commands (all use same socket via _send_cgi)
    # =====================================================================

    async def _cgi_login(self) -> bool:
        cgi = build_cgi_url(CGI_CHECK_USER, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            if "json" in resp:
                self._capabilities = resp["json"]
            return True
        if resp and resp.get("result") == -1:
            return False
        return False

    async def login(self, username: str, password: str) -> bool:
        cgi = build_cgi_url(CGI_CHECK_USER, username, password)
        resp = await self._send_cgi(cgi)
        return bool(resp and resp.get("success"))

    async def _send_cgi(self, cgi_url: str) -> dict | None:
        if not self._connected or not self._transport:
            return None
        self._cmd_seq = (self._cmd_seq + 1) % 256
        drw = build_drw_cgi(self._cmd_seq, cgi_url)
        target = (self.host, self._cam_port)

        for _ in range(DRW_RETRY_MAX):
            self._drw_response.clear()
            self._drw_data = b""
            self._transport.sendto(drw, target)
            self._transport.sendto(build_alive(), target)
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
        cgi = build_cgi_url(CGI_CAMERA_CONTROL, self.username, self.password,
                            param=param, value=value)
        resp = await self._send_cgi(cgi)
        return bool(resp and resp.get("success"))

    async def set_brightness(self, v: int) -> bool:
        return await self.camera_control(CGI_PARAM_BRIGHTNESS, v)

    async def set_contrast(self, v: int) -> bool:
        return await self.camera_control(CGI_PARAM_CONTRAST, v)

    async def set_ir_led(self, on: bool) -> bool:
        return await self.camera_control(CGI_PARAM_IR_CUT, 1 if on else 0)

    async def set_indicator_led(self, on: bool) -> bool:
        return await self.camera_control(CGI_PARAM_STATUS_LED, 1 if on else 0)

    async def set_resolution(self, v: int) -> bool:
        return await self.camera_control(CGI_PARAM_RESOLUTION, v)

    async def set_mirror(self, m: int) -> bool:
        return await self.camera_control(CGI_PARAM_MIRROR, m)

    async def reboot(self) -> bool:
        cgi = build_cgi_url(CGI_REBOOT, self.username, self.password)
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

    async def factory_reset(self) -> bool:
        cgi = build_cgi_url(CGI_FACTORY_RESET, self.username, self.password)
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

    async def format_sd(self) -> bool:
        cgi = build_cgi_url(CGI_FORMAT_SD, self.username, self.password)
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

    async def snapshot(self) -> bool:
        cgi = build_cgi_url(CGI_SNAPSHOT, self.username, self.password)
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

    async def change_password(self, new_password: str) -> bool:
        cgi = build_cgi_url(CGI_SET_USER, self.username, self.password,
                            user1=self.username, pwd1=new_password,
                            user2="", pwd2="", user3="", pwd3="")
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            self.password = new_password
            return True
        return False

    async def set_motion_detection(self, enabled: bool) -> bool:
        cgi = build_cgi_url(CGI_SET_ALARM, self.username, self.password,
                            motion_armed=1 if enabled else 0)
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

    async def set_recording_mode(self, mode: int) -> bool:
        cgi = build_cgi_url("set_record_param.cgi", self.username, self.password,
                            rec_mode=mode)
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

    async def ptz_control(self, direction: int, step: int = 1) -> bool:
        cgi = build_cgi_url("decoder_control.cgi", self.username, self.password,
                            command=direction, onestep=step)
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

    # =====================================================================
    # Keepalive
    # =====================================================================

    async def _keepalive_loop(self) -> None:
        while self._connected:
            try:
                if self._transport and self._cam_port:
                    self._transport.sendto(
                        build_alive(), (self.host, self._cam_port),
                    )
                await asyncio.sleep(KEEPALIVE_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    def _handle_drw_response(self, data: bytes) -> None:
        self._drw_data = data
        self._drw_response.set()


class _PNZEOProtocol(asyncio.DatagramProtocol):
    """UDP protocol — single socket handles discovery + punch + data."""

    def __init__(self, client: PNZEOClient) -> None:
        self.client = client
        self.got_p2p_rdy = False

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        if len(data) < 2 or data[0] != 0xF1:
            return

        pkt_type = data[1]
        # Log ALL packets for debugging
        if pkt_type not in (PktType.ALIVE, PktType.ALIVE_ACK):
            _LOGGER.warning(
                "PPPP RX: F1%02X from %s:%d (%dB)",
                pkt_type, addr[0], addr[1], len(data),
            )

        # LAN Search response (F141 PUNCH_PKT) — extract P2P port
        if pkt_type == PktType.PUNCH_PKT and addr[0] == self.client.host:
            self.client._cam_port = addr[1]
            self.client._drw_response.set()

        # P2P handshake response
        elif pkt_type in (PktType.P2P_RDY, PktType.P2P_RDY_ACK):
            if not self.got_p2p_rdy:
                self.got_p2p_rdy = True
                self.client._drw_response.set()

        # DRW data response from camera
        elif pkt_type == PktType.DRW:
            self.client._handle_drw_response(data)

        # Keepalive from camera
        elif pkt_type == PktType.ALIVE:
            if self.client._transport:
                try:
                    self.client._transport.sendto(build_alive_ack(), addr)
                except Exception:
                    pass

        elif pkt_type == PktType.CLOSE:
            self.client._connected = False

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("UDP error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        self.client._connected = False
