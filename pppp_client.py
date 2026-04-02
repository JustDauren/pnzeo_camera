"""Async PPPP client for PNZEO/MTC cameras.

Connection flow:
1. LAN Search (F130 → 32108) → camera responds with P2P signaling port
2. Cloud query (1 UDP to P2P server) → get camera's DRW data port
3. F141 PUNCH to DRW port → P2P handshake
4. CGI commands via DRW → full camera control on LAN

Cloud is used ONLY for port discovery (1 UDP query, 3 seconds).
All actual camera data stays 100% on LAN.
Camera does NOT need internet — only Pi5 makes one outbound UDP query.
"""
from __future__ import annotations

import asyncio
import logging
import random
import socket
import struct
import time
from typing import Any

from .const import (
    ConnectionState,
    BACKOFF_BASE, BACKOFF_MAX_LAN, BACKOFF_MAX_CLOUD, MAX_RECONNECT_ATTEMPTS,
)
from .pppp_packets import (
    PktType,
    build_alive, build_alive_ack, build_close,
    build_cgi_url, build_drw_cgi, build_lan_search,
    encode_uid, parse_drw_cgi_response,
    CGI_CHECK_USER, CGI_GET_PARAMS, CGI_GET_STATUS,
    CGI_CAMERA_CONTROL, CGI_REBOOT, CGI_FACTORY_RESET,
    CGI_FORMAT_SD, CGI_SNAPSHOT,
    CGI_SET_USER, CGI_SET_ALARM,
    CGI_GET_ALARM, CGI_GET_ALARM_EX, CGI_SET_ALARM_EX, CGI_GET_ALARM_LOG,
    CGI_PARAM_BRIGHTNESS, CGI_PARAM_CONTRAST, CGI_PARAM_IR_CUT,
    CGI_PARAM_STATUS_LED, CGI_PARAM_MIRROR, CGI_PARAM_RESOLUTION,
)

_LOGGER = logging.getLogger(__name__)

KEEPALIVE_INTERVAL = 3
PUNCH_COUNT = 12
PUNCH_INTERVAL = 0.15
DRW_RETRY_MAX = 25
DRW_RETRY_INTERVAL = 0.3
LAN_SEARCH_PORT = 32108
CLOUD_TIMEOUT = 3
CLOUD_P2P_SERVERS = [
    ("54.186.48.247", 32100),
    ("54.191.3.239", 32100),
]

# Canonical alarm parameter names (33 params -- RTAlarmSetting from APK)
ALARM_PARAMS = [
    "motion_armed", "motion_sensitivity", "input_armed", "ioin_level",
    "iolinkage", "ioout_level", "alarmpresetsit", "mail", "snapshot",
    "record", "upload_interval", "schedule_enable",
    "schedule_sun_0", "schedule_sun_1", "schedule_sun_2",
    "schedule_mon_0", "schedule_mon_1", "schedule_mon_2",
    "schedule_tue_0", "schedule_tue_1", "schedule_tue_2",
    "schedule_wed_0", "schedule_wed_1", "schedule_wed_2",
    "schedule_thu_0", "schedule_thu_1", "schedule_thu_2",
    "schedule_fri_0", "schedule_fri_1", "schedule_fri_2",
    "schedule_sat_0", "schedule_sat_1", "schedule_sat_2",
]

# Extended alarm parameter names (11 params -- RTAlarmEXSetting from APK)
ALARM_EX_PARAMS = [
    "mdAlarmType", "mdSensitive", "mdInterval", "mdEmailSnap",
    "mdFtpSnap", "mdFtpRec", "ioEnable", "ioInterval",
    "ioEmailSnap", "ioFtpSnap", "ioFtpRec",
]


class PNZEOClient:
    """Async PPPP client for camera control."""

    def __init__(self, host: str, username: str, password: str,
                 device_id: str = "", **kwargs) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.device_id = device_id
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: _PNZEOProtocol | None = None
        self._state: ConnectionState = ConnectionState.DISCONNECTED
        self._keepalive_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._last_keepalive_sent: float = 0.0
        self._cam_port: int = 0
        self._cmd_seq = 0
        self._connection_method = "none"
        self._capabilities: dict = {}
        self._camera_params: dict = {}
        self._drw_response: asyncio.Event = asyncio.Event()
        self._drw_data: bytes = b""

    @property
    def connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED

    @property
    def connection_state(self) -> ConnectionState:
        """Current connection state enum value."""
        return self._state

    @property
    def state(self) -> dict[str, Any]:
        return self._camera_params

    @property
    def connection_method(self) -> str:
        return self._connection_method

    @property
    def capabilities(self) -> dict:
        return self._capabilities

    def _set_state(self, new_state: ConnectionState) -> None:
        """Transition connection state with logging."""
        old_state = self._state
        if old_state == new_state:
            return
        self._state = new_state
        _LOGGER.info(
            "Connection state: %s -> %s (%s)",
            old_state.name, new_state.name, self.host,
        )

    # =====================================================================
    # Connection
    # =====================================================================

    async def connect(self) -> bool:
        """Connect to camera. Retries once on failure."""
        for attempt in range(2):
            result = await self._do_connect()
            if result:
                return True
            if attempt == 0:
                await asyncio.sleep(2)
        return False

    async def _do_connect(self) -> bool:
        """Single connection attempt with guaranteed cleanup on failure."""
        self._set_state(ConnectionState.CONNECTING)
        transport = None
        try:
            await self._cleanup_transport()

            drw_port = await self._cloud_discover_port()
            if not drw_port:
                _LOGGER.debug("Cloud port discovery failed, trying LAN only")
                drw_port = await self._lan_discover_port()

            if not drw_port:
                _LOGGER.warning("Cannot discover camera port for %s", self.host)
                return False

            self._cam_port = drw_port

            loop = asyncio.get_running_loop()
            self._protocol = _PNZEOProtocol(self)
            transport, _ = await asyncio.wait_for(
                loop.create_datagram_endpoint(
                    lambda: self._protocol,
                    local_addr=("0.0.0.0", 0),
                ),
                timeout=5,
            )
            self._transport = transport

            target = (self.host, self._cam_port)
            uid = encode_uid(self.device_id)
            punch = struct.pack(">BBH", 0xF1, PktType.PUNCH_PKT, len(uid)) + uid

            self._drw_response.clear()
            for i in range(PUNCH_COUNT):
                self._transport.sendto(punch, target)
                if i % 3 == 2:
                    self._transport.sendto(build_alive(), target)
                await asyncio.sleep(PUNCH_INTERVAL)
                if self._protocol.got_p2p_rdy:
                    break

            if not self._protocol.got_p2p_rdy:
                try:
                    await asyncio.wait_for(self._drw_response.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    pass

            if not self._protocol.got_p2p_rdy:
                _LOGGER.warning("P2P handshake failed with %s:%d", self.host, self._cam_port)
                return False

            _LOGGER.debug("P2P handshake OK with %s:%d", self.host, self._cam_port)

            # Keepalive burst before CGI
            for _ in range(8):
                self._transport.sendto(build_alive(), target)
                await asyncio.sleep(0.15)

            # CGI login
            self._set_state(ConnectionState.AUTHENTICATING)
            if not await self._cgi_login():
                _LOGGER.warning("CGI login failed on %s:%d", self.host, self._cam_port)
                return False

            self._connection_method = "lan"
            self._set_state(ConnectionState.CONNECTED)
            self._last_keepalive_sent = time.monotonic()
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())
            self._watchdog_task = asyncio.create_task(self._connection_watchdog())
            _LOGGER.info("Connected to camera %s (port %d)", self.host, self._cam_port)
            return True

        except Exception as ex:
            _LOGGER.debug("Connection failed: %s", ex)
            return False
        finally:
            if self._state != ConnectionState.CONNECTED:
                if transport and not transport.is_closing():
                    transport.close()
                if self._transport is transport:
                    self._transport = None
                self._protocol = None
                if self._state in (ConnectionState.CONNECTING, ConnectionState.AUTHENTICATING):
                    self._set_state(ConnectionState.DISCONNECTED)

    async def disconnect(self) -> None:
        """Disconnect and clean up all tasks."""
        if self._watchdog_task:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None

        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
            self._keepalive_task = None

        if self._transport and self._cam_port:
            try:
                self._transport.sendto(build_close(), (self.host, self._cam_port))
            except Exception:
                pass

        await self._cleanup_transport()
        self._set_state(ConnectionState.DISCONNECTED)

    async def _cleanup_transport(self) -> None:
        """Clean up transport and protocol. Does NOT change connection state."""
        if self._transport:
            try:
                if not self._transport.is_closing():
                    self._transport.close()
            except Exception:
                pass
            self._transport = None
        self._protocol = None
        self._connection_method = "none"

    # =====================================================================
    # Reconnection and Watchdog
    # =====================================================================

    async def _reconnect_with_backoff(self) -> bool:
        """Reconnect with exponential backoff + full jitter."""
        self._set_state(ConnectionState.RECONNECTING)
        max_delay = (
            BACKOFF_MAX_CLOUD
            if self._connection_method == "cloud"
            else BACKOFF_MAX_LAN
        )

        for attempt in range(MAX_RECONNECT_ATTEMPTS):
            delay = min(BACKOFF_BASE * (2 ** attempt), max_delay)
            jitter = random.uniform(0, delay)
            _LOGGER.info(
                "Reconnect attempt %d/%d in %.1fs (%s)",
                attempt + 1, MAX_RECONNECT_ATTEMPTS, jitter, self.host,
            )
            await asyncio.sleep(jitter)
            await self._cleanup_transport()
            if await self._do_connect():
                return True

        self._set_state(ConnectionState.FAILED)
        _LOGGER.error(
            "Failed to reconnect after %d attempts (%s). "
            "Will retry on next coordinator cycle.",
            MAX_RECONNECT_ATTEMPTS, self.host,
        )
        return False

    async def _connection_watchdog(self) -> None:
        """Monitor connection health. Restart keepalive or trigger reconnect."""
        consecutive_failures = 0
        while self._state in (ConnectionState.CONNECTED, ConnectionState.RECONNECTING):
            try:
                if self._state == ConnectionState.CONNECTED:
                    if not self._keepalive_task or self._keepalive_task.done():
                        _LOGGER.warning(
                            "Keepalive task died at %s (%s). Restarting.",
                            time.strftime("%H:%M:%S"), self.host,
                        )
                        consecutive_failures += 1
                        if consecutive_failures >= 3:
                            _LOGGER.warning(
                                "3 keepalive failures (%s). Triggering reconnect.",
                                self.host,
                            )
                            await self._reconnect_with_backoff()
                            consecutive_failures = 0
                        elif self._state == ConnectionState.CONNECTED:
                            self._keepalive_task = asyncio.create_task(
                                self._keepalive_loop()
                            )
                    else:
                        consecutive_failures = 0

                await asyncio.sleep(KEEPALIVE_INTERVAL * 2)

            except asyncio.CancelledError:
                break
            except Exception as ex:
                _LOGGER.warning("Watchdog error (%s): %s", self.host, ex)
                await asyncio.sleep(KEEPALIVE_INTERVAL)

    # =====================================================================
    # Port Discovery
    # =====================================================================

    async def _cloud_discover_port(self) -> int | None:
        """Get camera's DRW port from cloud P2P server (1 UDP query, ~3s)."""
        if not self.device_id:
            return None
        uid = encode_uid(self.device_id)

        for server_host, server_port in CLOUD_P2P_SERVERS:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(CLOUD_TIMEOUT)

                # Hello
                sock.sendto(b"\xf1\x00\x00\x00", (server_host, server_port))
                sock.recvfrom(4096)

                # P2P Connect
                p2p_payload = uid + b"\x00" * 16
                p2p = struct.pack(">BBH", 0xF1, 0x20, len(p2p_payload)) + p2p_payload
                sock.sendto(p2p, (server_host, server_port))

                # Wait for F140 with camera's LAN IP:port
                for _ in range(5):
                    data, _ = sock.recvfrom(4096)
                    if len(data) >= 12 and data[0] == 0xF1 and data[1] == 0x40:
                        payload = data[4:]
                        if len(payload) >= 8:
                            port = struct.unpack("<H", payload[2:4])[0]
                            ip_val = struct.unpack("<I", payload[4:8])[0]
                            ip = socket.inet_ntoa(struct.pack("!I", ip_val))
                            if ip == self.host:
                                sock.close()
                                _LOGGER.debug("Cloud: camera DRW port = %d", port)
                                return port
                sock.close()
            except Exception as ex:
                _LOGGER.debug("Cloud discovery via %s failed: %s", server_host, ex)
                try:
                    sock.close()
                except Exception:
                    pass
        return None

    async def _lan_discover_port(self) -> int | None:
        """Fallback: get port from LAN Search response."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(3)
            sock.sendto(build_lan_search(), (self.host, LAN_SEARCH_PORT))
            _, (_, port) = sock.recvfrom(4096)
            sock.close()
            _LOGGER.debug("LAN: camera port = %d", port)
            return port
        except Exception:
            return None

    # =====================================================================
    # CGI Commands
    # =====================================================================

    async def _cgi_login(self) -> bool:
        cgi = build_cgi_url(CGI_CHECK_USER, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            if "json" in resp:
                self._capabilities = resp["json"]
            return True
        return False

    async def login(self, username: str, password: str) -> bool:
        cgi = build_cgi_url(CGI_CHECK_USER, username, password)
        resp = await self._send_cgi(cgi)
        return bool(resp and resp.get("success"))

    async def _send_cgi(self, cgi_url: str) -> dict | None:
        if self._state not in (ConnectionState.CONNECTED, ConnectionState.AUTHENTICATING):
            return None
        if not self._transport or self._transport.is_closing():
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
    # Camera control
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
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

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

    # =====================================================================
    # Alarm settings (GET-before-SET per Pitfall 11)
    # =====================================================================

    async def get_alarm_params(self) -> dict[str, Any]:
        """Get alarm parameters (33 params -- RTAlarmSetting)."""
        cgi = build_cgi_url(CGI_GET_ALARM, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            alarm = {k: v for k, v in resp.items()
                     if k in ALARM_PARAMS}
            self._camera_params.update(alarm)
        return self._camera_params

    async def set_alarm_params(self, **kwargs) -> bool:
        """Set alarm parameters with GET-before-SET merge.

        CRITICAL: Always GET current values first, merge changed values,
        then SET all 33 params. Never send partial updates.
        """
        # Validate param names
        unknown = [k for k in kwargs if k not in ALARM_PARAMS]
        if unknown:
            _LOGGER.warning("Unknown alarm params ignored: %s", unknown)
            kwargs = {k: v for k, v in kwargs.items() if k in ALARM_PARAMS}

        if not kwargs:
            return False

        # GET current values first
        await self.get_alarm_params()
        current = {k: self._camera_params.get(k, "0") for k in ALARM_PARAMS}

        # Merge changes into current
        current.update({k: str(v) for k, v in kwargs.items()})

        # SET all params
        cgi = build_cgi_url(CGI_SET_ALARM, self.username, self.password, **current)
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

    async def get_alarm_ex_params(self) -> dict[str, Any]:
        """Get extended alarm parameters (11 params -- RTAlarmEXSetting)."""
        cgi = build_cgi_url(CGI_GET_ALARM_EX, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            alarm_ex = {k: v for k, v in resp.items()
                        if k in ALARM_EX_PARAMS}
            self._camera_params.update(alarm_ex)
        return self._camera_params

    async def set_alarm_ex_params(self, **kwargs) -> bool:
        """Set extended alarm parameters with GET-before-SET merge.

        CRITICAL: Always GET current values first, merge changed values,
        then SET all 11 params. Never send partial updates.
        """
        unknown = [k for k in kwargs if k not in ALARM_EX_PARAMS]
        if unknown:
            _LOGGER.warning("Unknown alarm EX params ignored: %s", unknown)
            kwargs = {k: v for k, v in kwargs.items() if k in ALARM_EX_PARAMS}

        if not kwargs:
            return False

        # GET current values first
        await self.get_alarm_ex_params()
        current = {k: self._camera_params.get(k, "0") for k in ALARM_EX_PARAMS}

        # Merge changes into current
        current.update({k: str(v) for k, v in kwargs.items()})

        # SET all params
        cgi = build_cgi_url(CGI_SET_ALARM_EX, self.username, self.password, **current)
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

    async def get_alarm_log(self) -> list[dict]:
        """Get alarm log entries from camera."""
        cgi = build_cgi_url(CGI_GET_ALARM_LOG, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if not resp or not resp.get("success"):
            return []

        # Parse log entries from response text
        entries = []
        raw = resp.get("raw", "")
        for line in raw.split("\n"):
            line = line.strip().rstrip(";")
            if line.startswith("log_") and "=" in line:
                key, _, val = line.partition("=")
                # Each log entry is log_N=type,timestamp,...
                parts = val.split(",")
                if len(parts) >= 2:
                    entries.append({
                        "key": key.strip(),
                        "type": parts[0].strip(),
                        "time": parts[1].strip() if len(parts) > 1 else "",
                        "extra": ",".join(parts[2:]) if len(parts) > 2 else "",
                    })
        return entries

    async def set_sound_detection(self, enabled: bool) -> bool:
        """Toggle sound detection alarm (uses input_armed field)."""
        return await self.set_alarm_params(input_armed=1 if enabled else 0)

    async def set_gpio_alarm(self, enabled: bool) -> bool:
        """Toggle GPIO alarm input (uses ioEnable in extended alarm)."""
        return await self.set_alarm_ex_params(ioEnable=1 if enabled else 0)

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
        """Send keepalive packets. Track failures for watchdog."""
        self._last_keepalive_sent = time.monotonic()
        while self._state == ConnectionState.CONNECTED:
            try:
                if self._transport and not self._transport.is_closing():
                    self._transport.sendto(
                        build_alive(), (self.host, self._cam_port)
                    )
                    self._last_keepalive_sent = time.monotonic()
                else:
                    _LOGGER.warning(
                        "Keepalive: transport closed at %s (%s)",
                        time.strftime("%H:%M:%S"), self.host,
                    )
                    break
                await asyncio.sleep(KEEPALIVE_INTERVAL)
            except asyncio.CancelledError:
                _LOGGER.debug("Keepalive cancelled (%s)", self.host)
                raise
            except OSError as ex:
                _LOGGER.warning(
                    "Keepalive send failed at %s (%s): %s",
                    time.strftime("%H:%M:%S"), self.host, ex,
                )
                break
            except Exception as ex:
                _LOGGER.warning(
                    "Keepalive unexpected error at %s (%s): %s",
                    time.strftime("%H:%M:%S"), self.host, ex,
                )
                break

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

        # F141/F142/F143 — all valid P2P handshake responses
        if pkt_type in (PktType.PUNCH_PKT, PktType.P2P_RDY, PktType.P2P_RDY_ACK):
            if addr[0] == self.client.host:
                self.got_p2p_rdy = True
                self.client._drw_response.set()

        # DRW data from camera
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
            if self.client._state == ConnectionState.CONNECTED:
                self.client._set_state(ConnectionState.DISCONNECTED)

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("UDP error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        if self.client._state == ConnectionState.CONNECTED:
            self.client._set_state(ConnectionState.DISCONNECTED)
