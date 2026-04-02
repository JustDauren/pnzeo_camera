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
import datetime as dt
import logging
import random
import socket
import struct
import time
from typing import Any

from .const import (
    ConnectionState,
    BACKOFF_BASE, BACKOFF_MAX_LAN, BACKOFF_MAX_CLOUD, MAX_RECONNECT_ATTEMPTS,
    CH_CMD, CH_AUDIO, CH_TALK,
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
    CGI_PARAM_POWER_FREQ,
    CGI_GET_IRCUT, CGI_SET_IRCUT, CGI_SET_DEVNAME,
    CGI_SET_DATETIME, CGI_START_RECORDING,
    CGI_WIFI_SCAN, CGI_GET_DDNS, CGI_SET_DDNS,
    CGI_GET_WIFI, CGI_SET_WIFI, CGI_GET_NETWORK, CGI_GET_USER,
    CGI_GET_FTP, CGI_SET_FTP, CGI_GET_MAIL, CGI_SET_MAIL, CGI_SET_FCM,
    CGI_UNMOUNT_SD, CGI_SET_RECORD_SCH, CGI_GET_RECORD_FILE,
    CGI_GET_RECORD_CALENDAR, CGI_GET_RECORD, RECORDING_MODE_MAP,
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

# Recording schedule parameter names (25 params)
RECORDING_SCHEDULE_PARAMS = [
    "rec_sch_enable",
    "rec_sch_sun_0", "rec_sch_sun_1", "rec_sch_sun_2",
    "rec_sch_mon_0", "rec_sch_mon_1", "rec_sch_mon_2",
    "rec_sch_tue_0", "rec_sch_tue_1", "rec_sch_tue_2",
    "rec_sch_wed_0", "rec_sch_wed_1", "rec_sch_wed_2",
    "rec_sch_thu_0", "rec_sch_thu_1", "rec_sch_thu_2",
    "rec_sch_fri_0", "rec_sch_fri_1", "rec_sch_fri_2",
    "rec_sch_sat_0", "rec_sch_sat_1", "rec_sch_sat_2",
    "rec_sch_record_time", "rec_sch_mode", "rec_sch_prerecord",
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
        self._cmd_response: asyncio.Event = asyncio.Event()
        self._cmd_data: bytes = b""
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=50)
        self._audio_streaming: bool = False
        self._audio_format: dict | None = None

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

            self._cmd_response.clear()
            for i in range(PUNCH_COUNT):
                self._transport.sendto(punch, target)
                if i % 3 == 2:
                    self._transport.sendto(build_alive(), target)
                await asyncio.sleep(PUNCH_INTERVAL)
                if self._protocol.got_p2p_rdy:
                    break

            if not self._protocol.got_p2p_rdy:
                try:
                    await asyncio.wait_for(self._cmd_response.wait(), timeout=3.0)
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
        if self._audio_streaming:
            await self.stop_audio_stream()

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
            self._cmd_response.clear()
            self._cmd_data = b""
            self._transport.sendto(drw, target)
            self._transport.sendto(build_alive(), target)
            try:
                await asyncio.wait_for(
                    self._cmd_response.wait(), timeout=DRW_RETRY_INTERVAL,
                )
                if self._cmd_data:
                    return parse_drw_cgi_response(self._cmd_data)
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

    async def unmount_sd(self) -> bool:
        """Safely unmount the SD card."""
        cgi = build_cgi_url(CGI_UNMOUNT_SD, self.username, self.password)
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

    async def get_record_mode(self) -> dict[str, Any]:
        """Get current recording mode. Stores rec_mode in _camera_params."""
        cgi = build_cgi_url(CGI_GET_RECORD, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            if "rec_mode" in resp:
                self._camera_params["rec_mode"] = resp["rec_mode"]
            # Store any other recording params
            rec = {k: v for k, v in resp.items()
                   if k.startswith("rec_")}
            self._camera_params.update(rec)
        return self._camera_params

    async def set_recording_schedule(self, **kwargs) -> bool:
        """Configure recording schedule (25 params).

        Accepts: rec_sch_enable, rec_sch_sun_0..2, rec_sch_mon_0..2, ...,
        rec_sch_sat_0..2, rec_sch_record_time, rec_sch_mode, rec_sch_prerecord.
        """
        unknown = [k for k in kwargs if k not in RECORDING_SCHEDULE_PARAMS]
        if unknown:
            _LOGGER.warning("Unknown recording schedule params ignored: %s", unknown)
            kwargs = {k: v for k, v in kwargs.items()
                      if k in RECORDING_SCHEDULE_PARAMS}

        if not kwargs:
            return False

        cgi = build_cgi_url(CGI_SET_RECORD_SCH, self.username, self.password,
                            **kwargs)
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

    async def get_record_file_list(self, start_date: str, end_date: str,
                                   rec_type: int = 0, start_idx: int = 0,
                                   count: int = 20) -> dict | None:
        """Get recorded file list from SD card.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            rec_type: Recording type (0=all)
            start_idx: Pagination start index
            count: Number of files to return
        Returns: Parsed response dict with file list and pagination info.
        """
        cgi = build_cgi_url(CGI_GET_RECORD_FILE, self.username, self.password,
                            startDate=start_date, endDate=end_date,
                            type=rec_type, startIdx=start_idx, count=count)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            return resp
        return None

    async def get_record_calendar(self, month: str) -> dict | None:
        """Get recording calendar (bitmask of days with recordings).

        Args:
            month: Month string in YYYY-MM format.
        Returns: Parsed response dict with day bitmask.
        """
        cgi = build_cgi_url(CGI_GET_RECORD_CALENDAR, self.username, self.password,
                            month=month)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            return resp
        return None

    # =====================================================================
    # Camera settings (IR, power freq, device name, time sync, recording)
    # =====================================================================

    async def get_ircut_params(self) -> dict[str, Any]:
        """Get IR cut parameters (mode, sensitivity, timing)."""
        cgi = build_cgi_url(CGI_GET_IRCUT, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            ircut = {k: v for k, v in resp.items()
                     if k.startswith("ircut_") or k in ("ircut_mode",)}
            self._camera_params.update(ircut)
        return self._camera_params

    async def set_ircut_params(self, **kwargs) -> bool:
        """Set IR cut parameters.

        Accepts: ircut_mode (0=auto, 1=on, 2=off),
                 ircut_sensitivity, ircut_day_start, ircut_day_end, ircut_night_start.
        Falls back to camera_control for basic mode setting if full CGI unavailable.
        """
        mode = kwargs.get("ircut_mode")

        # Try full IR cut CGI first
        if len(kwargs) > 1 or mode is None:
            cgi = build_cgi_url(CGI_SET_IRCUT, self.username, self.password, **kwargs)
            resp = await self._send_cgi(cgi)
            if resp and resp.get("success"):
                return True

        # Fallback: use camera_control.cgi param=14 for basic mode
        if mode is not None:
            return await self.camera_control(CGI_PARAM_IR_CUT, int(mode))

        return False

    async def set_power_freq(self, freq: int) -> bool:
        """Set power frequency (anti-flicker). 0=50Hz, 1=60Hz."""
        return await self.camera_control(CGI_PARAM_POWER_FREQ, freq)

    async def set_device_name(self, name: str) -> bool:
        """Set camera device name."""
        cgi = build_cgi_url(CGI_SET_DEVNAME, self.username, self.password,
                            devname=name)
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

    async def sync_time(self) -> bool:
        """Synchronize camera time with system time."""
        now = dt.datetime.now()
        # Calculate timezone offset in hours
        utc_offset = now.astimezone().utcoffset()
        tz_hours = int(utc_offset.total_seconds() // 3600) if utc_offset else 0
        cgi = build_cgi_url(
            CGI_SET_DATETIME, self.username, self.password,
            year=now.year, mon=now.month, day=now.day,
            hour=now.hour, min=now.minute, sec=now.second,
            tz=tz_hours,
        )
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

    async def start_recording(self) -> bool:
        """Trigger manual recording on camera SD card."""
        cgi = build_cgi_url(CGI_START_RECORDING, self.username, self.password,
                            rec_mode=1, rec_channel=1)
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

    # =====================================================================
    # WiFi, network, and user management
    # =====================================================================

    _SECURITY_MAP = {0: "None", 1: "WEP", 2: "WPA", 3: "WPA2"}

    async def wifi_scan(self) -> list[dict]:
        """Scan for available WiFi networks from camera.

        Response format: key=value pairs like
          ap_ssid[0]=NetworkName&ap_signal[0]=80&ap_security[0]=3
        Returns list of dicts: [{"ssid": "...", "signal": 80, "security": "WPA2"}, ...]
        """
        cgi = build_cgi_url(CGI_WIFI_SCAN, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if not resp or not resp.get("success"):
            return []

        networks: list[dict] = []
        # Collect indexed AP fields from response
        ssids: dict[int, str] = {}
        signals: dict[int, int] = {}
        securities: dict[int, int] = {}
        for key, val in resp.items():
            if key.startswith("ap_ssid["):
                try:
                    idx = int(key.split("[")[1].rstrip("]"))
                    ssids[idx] = str(val)
                except (ValueError, IndexError):
                    pass
            elif key.startswith("ap_signal["):
                try:
                    idx = int(key.split("[")[1].rstrip("]"))
                    signals[idx] = int(val)
                except (ValueError, IndexError):
                    pass
            elif key.startswith("ap_security["):
                try:
                    idx = int(key.split("[")[1].rstrip("]"))
                    securities[idx] = int(val)
                except (ValueError, IndexError):
                    pass

        for idx in sorted(ssids.keys()):
            sec_num = securities.get(idx, 0)
            networks.append({
                "ssid": ssids[idx],
                "signal": signals.get(idx, 0),
                "security": self._SECURITY_MAP.get(sec_num, f"Unknown({sec_num})"),
            })
        return networks

    async def set_wifi(self, ssid: str, password: str, security: int = 3) -> bool:
        """Connect camera to a WiFi network.

        security: 0=none, 1=WEP, 2=WPA, 3=WPA2
        """
        cgi = build_cgi_url(CGI_SET_WIFI, self.username, self.password,
                            ssid=ssid, pwd=password, mode=security, enable=1)
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

    async def get_wifi_params(self) -> dict[str, Any]:
        """Get current WiFi connection parameters (SSID, signal, mode).

        Stores results in _camera_params under 'wifi_*' namespace.
        """
        cgi = build_cgi_url(CGI_GET_WIFI, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            wifi = {k: v for k, v in resp.items()
                    if k.startswith("wifi_") or k in ("ssid", "signal", "mode", "enable")}
            self._camera_params.update(wifi)
            return wifi
        return {}

    async def get_network_params(self) -> dict[str, Any]:
        """Get LAN network settings (IP, mask, gateway, DNS).

        Stores results in _camera_params under 'net_*' namespace.
        """
        cgi = build_cgi_url(CGI_GET_NETWORK, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            network = {k: v for k, v in resp.items()
                       if k.startswith("net_") or k in (
                           "ip", "mask", "gateway", "dns", "dhcp")}
            self._camera_params.update(network)
            return network
        return {}

    async def get_ddns_params(self) -> dict[str, Any]:
        """Get DDNS settings from camera."""
        cgi = build_cgi_url(CGI_GET_DDNS, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            ddns = {k: v for k, v in resp.items()
                    if k.startswith("ddns_") or k in (
                        "ddns_service", "ddns_host", "ddns_user", "ddns_port")}
            return ddns
        return {}

    async def set_ddns(self, service: str, hostname: str, user: str,
                       password: str, port: int = 80) -> bool:
        """Configure DDNS settings on camera."""
        cgi = build_cgi_url(CGI_SET_DDNS, self.username, self.password,
                            ddns_service=service, ddns_host=hostname,
                            ddns_user=user, ddns_pwd=password, ddns_port=port)
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

    async def get_users(self) -> list[dict]:
        """Get camera user accounts (up to 3 slots).

        Response format: user1=admin&pwd1=8888&user2=&pwd2=&user3=&pwd3=
        Returns list of dicts with slot and username (passwords NOT returned for security).
        """
        cgi = build_cgi_url(CGI_GET_USER, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if not resp or not resp.get("success"):
            return []

        users: list[dict] = []
        for slot in range(1, 4):
            username = resp.get(f"user{slot}", "")
            if username:
                users.append({"slot": slot, "username": str(username)})
        return users

    async def set_users(self, user1: str = "", pwd1: str = "",
                        user2: str = "", pwd2: str = "",
                        user3: str = "", pwd3: str = "") -> bool:
        """Set camera user accounts (all 3 slots).

        WARNING: This overwrites ALL 3 user slots. Always GET first.
        If primary user (slot 1) password changes, updates self.password.
        """
        cgi = build_cgi_url(CGI_SET_USER, self.username, self.password,
                            user1=user1, pwd1=pwd1,
                            user2=user2, pwd2=pwd2,
                            user3=user3, pwd3=pwd3)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            # Update stored password if primary user password changed
            if user1 == self.username and pwd1:
                self.password = pwd1
            return True
        return False

    # =====================================================================
    # FTP, email, and push notification settings
    # =====================================================================

    async def get_ftp_params(self) -> dict[str, Any]:
        """Get FTP upload configuration from camera.

        Response contains: ftp_svr, ftp_port, ftp_user, ftp_dir,
        ftp_mode (0=PORT, 1=PASV), ftp_upload_interval.
        """
        cgi = build_cgi_url(CGI_GET_FTP, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            ftp = {k: v for k, v in resp.items()
                   if k.startswith("ftp_")}
            self._camera_params.update(ftp)
            return ftp
        return {}

    async def set_ftp(self, server: str, port: int = 21, user: str = "",
                      password: str = "", directory: str = "/",
                      mode: int = 1, upload_interval: int = 0) -> bool:
        """Configure FTP upload settings on camera.

        mode: 0=Active (PORT), 1=Passive (PASV, usually needed)
        upload_interval: 0=every alarm, N=every N seconds
        """
        cgi = build_cgi_url(CGI_SET_FTP, self.username, self.password,
                            ftp_svr=server, ftp_port=port, ftp_user=user,
                            ftp_pwd=password, ftp_dir=directory,
                            ftp_mode=mode, ftp_upload_interval=upload_interval)
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

    async def get_mail_params(self) -> dict[str, Any]:
        """Get email notification configuration from camera.

        Response contains: mail_svr, mail_port, mail_user, mail_sender,
        mail_receiver1..4, mail_ssl (0/1).
        """
        cgi = build_cgi_url(CGI_GET_MAIL, self.username, self.password)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            mail = {k: v for k, v in resp.items()
                    if k.startswith("mail_")}
            self._camera_params.update(mail)
            return mail
        return {}

    async def set_mail(self, smtp_server: str, smtp_port: int = 587,
                       user: str = "", password: str = "",
                       sender: str = "", receiver: str = "",
                       ssl: int = 1) -> bool:
        """Configure email notification settings on camera.

        ssl: 0=off, 1=TLS/STARTTLS
        """
        cgi = build_cgi_url(CGI_SET_MAIL, self.username, self.password,
                            mail_svr=smtp_server, mail_port=smtp_port,
                            mail_user=user, mail_pwd=password,
                            mail_sender=sender, mail_receiver1=receiver,
                            mail_ssl=ssl)
        return bool((r := await self._send_cgi(cgi)) and r.get("success"))

    async def set_push_token(self, token: str) -> bool:
        """Register FCM push notification token on camera.

        Camera uses this to send push alerts on alarm events.
        If CGI endpoint is unsupported, logs warning and returns False.
        """
        cgi = build_cgi_url(CGI_SET_FCM, self.username, self.password,
                            token=token)
        resp = await self._send_cgi(cgi)
        if resp and resp.get("success"):
            return True
        _LOGGER.warning(
            "set_push_token failed -- camera may not support CGI push "
            "(MSG_SET_FCM_PUSH=97 may require binary protocol)"
        )
        return False

    async def set_voice_enable(self, enable: bool) -> bool:
        """Enable/disable camera microphone (RTSetVoiceEnable)."""
        cgi = build_cgi_url("set_voice.cgi", self.username, self.password,
                            voice_enable=1 if enable else 0)
        resp = await self._send_cgi(cgi)
        return bool(resp and resp.get("success"))

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

    def _handle_drw_data(self, data: bytes, channel: int) -> None:
        """Route DRW data by channel."""
        if channel == CH_CMD:
            # CGI command response -- signal _send_cgi
            self._cmd_data = data
            self._cmd_response.set()
        elif channel == CH_AUDIO:
            # Audio stream data -- queue for consumer
            if self._audio_streaming:
                if self._audio_format is None and len(data) > 7:
                    # First audio packet -- detect format from inner header
                    from .audio_codec import detect_audio_format
                    drw_payload = data[7:]  # skip 7-byte DRW outer header
                    self._audio_format = detect_audio_format(drw_payload)
                    _LOGGER.debug("Audio format detected: %s", self._audio_format)
                try:
                    self._audio_queue.put_nowait(data)
                except asyncio.QueueFull:
                    # Drop oldest, keep newest (backpressure)
                    try:
                        self._audio_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    try:
                        self._audio_queue.put_nowait(data)
                    except asyncio.QueueFull:
                        pass
        # CH_TALK (3): ignore -- camera does not send talk feedback
        # CH_VIDEO (1): ignore -- video via RTSP, not DRW

    # =====================================================================
    # Audio streaming control
    # =====================================================================

    async def start_audio_stream(self) -> bool:
        """Start receiving audio on CH_AUDIO. Returns True if command sent."""
        if not self.connected or not self._transport:
            return False
        # Clear queue and state
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._audio_format = None
        self._audio_streaming = True
        # Send binary start audio command on CH_CMD
        from .pppp_packets import encode_command, build_drw
        from .const import MSG_START_AUDIO
        cmd = encode_command(MSG_START_AUDIO, b"\x01")  # mode=1 (A-law)
        pkt = build_drw(CH_CMD, cmd, index=self._cmd_seq)
        self._cmd_seq = (self._cmd_seq + 1) % 256
        self._transport.sendto(pkt, (self.host, self._cam_port))
        _LOGGER.info("Audio stream started on %s", self.host)
        return True

    async def stop_audio_stream(self) -> None:
        """Stop receiving audio on CH_AUDIO."""
        self._audio_streaming = False
        if self.connected and self._transport:
            from .pppp_packets import encode_command, build_drw
            from .const import MSG_STOP_AUDIO
            cmd = encode_command(MSG_STOP_AUDIO)
            pkt = build_drw(CH_CMD, cmd, index=self._cmd_seq)
            self._cmd_seq = (self._cmd_seq + 1) % 256
            self._transport.sendto(pkt, (self.host, self._cam_port))
        # Drain queue
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._audio_format = None
        _LOGGER.info("Audio stream stopped on %s", self.host)

    async def send_talk_data(self, alaw_data: bytes) -> bool:
        """Send A-law encoded audio data to camera on CH_TALK."""
        if not self.connected or not self._transport:
            return False
        from .pppp_packets import build_drw
        from .const import AUDIO_FRAME_SIZE
        # Send in AUDIO_FRAME_SIZE chunks
        offset = 0
        while offset < len(alaw_data):
            chunk = alaw_data[offset:offset + AUDIO_FRAME_SIZE]
            pkt = build_drw(CH_TALK, chunk, index=self._cmd_seq)
            self._cmd_seq = (self._cmd_seq + 1) % 256
            self._transport.sendto(pkt, (self.host, self._cam_port))
            offset += AUDIO_FRAME_SIZE
        return True


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
                self.client._cmd_response.set()

        # DRW data from camera -- route by channel
        elif pkt_type == PktType.DRW:
            if len(data) >= 3:
                channel = data[2]
                self.client._handle_drw_data(data, channel)

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
