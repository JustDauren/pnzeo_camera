"""Async PPPP client for PNZEO cameras — control via local relay.

Connection strategy:
1. Local relay on Pi5 (port 32100) — primary, no internet needed
2. LAN direct (port 32108/8600) — fast path if camera supports it
3. Cloud relay — emergency fallback if local relay not available

After connection, uses DRW packets for camera commands.
Video always via RTSP (TCP 554), independent of PPPP.
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
    MSG_GET_STATUS, MSG_GET_USER_INFO, MSG_GET_VOICE,
    MSG_REBOOT, MSG_FACTORY_RESET,
    MSG_SET_ALARM_EX, MSG_SET_REC_MODE, MSG_SET_USER, MSG_SNAPSHOT,
    PPPP_PORT_DH_LAN, PPPP_PORT_STANDARD,
    RELAY_KEEPALIVE_INTERVAL, RELAY_PUNCH_COUNT, RELAY_PUNCH_INTERVAL,
)
from .pppp_packets import (
    PktType,
    build_alive, build_alive_ack, build_close, build_drw, build_drw_ack,
    build_dh_discovery, build_hello, build_lan_search,
    build_p2p_connect, build_p2p_rdy,
    build_relay_hello, build_relay_port_req, build_relay_punch,
    build_relay_request,
    encode_camera_control, encode_command, encode_login, encode_ptz,
    encode_user_setting, parse_user_info,
    decode_response, parse_f1xx_header, parse_f1xx_message,
    parse_relay_info, parse_relay_port_ack,
)

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10
COMMAND_TIMEOUT = 5
HANDSHAKE_TIMEOUT = 5
LAN_KEEPALIVE = 0.4  # 400ms for LAN — camera drops without frequent heartbeat


class PNZEOClient:
    """Async PPPP client for camera control.

    Connects through local relay (preferred) or cloud relay.
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        device_id: str = "",
        port: int = PPPP_PORT_DH_LAN,
        local_relay: Any = None,  # PPPPLocalRelay instance
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.device_id = device_id
        self._local_relay = local_relay
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: _PNZEOProtocol | None = None
        self._connected = False
        self._authenticated = False
        self._keepalive_task: asyncio.Task | None = None
        self._cmd_index = 0
        self._state: dict[str, Any] = {}
        self._connection_method: str = "none"
        self._keepalive_interval: float = LAN_KEEPALIVE
        # Message waiters for async request/response
        self._msg_waiters: dict[int, asyncio.Future] = {}
        # DRW response waiters (by msg_type)
        self._drw_waiters: dict[int, asyncio.Future] = {}

    @property
    def connected(self) -> bool:
        return self._connected and self._authenticated

    @property
    def state(self) -> dict[str, Any]:
        return self._state

    @property
    def connection_method(self) -> str:
        return self._connection_method

    # =====================================================================
    # Connection
    # =====================================================================

    async def connect(self) -> bool:
        """Connect and authenticate with camera.

        Priority: local_relay → LAN → cloud_relay
        """
        # Method 1: Local relay (Pi5, no internet needed)
        if self._local_relay and self.device_id:
            if await self._try_local_relay():
                return True

        # Method 2: LAN direct (fast path — might not work with this firmware)
        if await self._try_lan(PPPP_PORT_STANDARD, "pppp_lan"):
            return True
        if await self._try_lan(PPPP_PORT_DH_LAN, "dh_lan"):
            return True

        # Method 3: Cloud relay (needs internet on Pi5)
        if self.device_id:
            if await self._try_cloud_relay():
                return True

        _LOGGER.warning(
            "All PPPP connection methods failed for %s. "
            "Camera will still work via RTSP for video.",
            self.host,
        )
        return False

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
        # Cancel all waiters
        for fut in self._msg_waiters.values():
            if not fut.done():
                fut.cancel()
        self._msg_waiters.clear()
        for fut in self._drw_waiters.values():
            if not fut.done():
                fut.cancel()
        self._drw_waiters.clear()

    # =====================================================================
    # Connection Method: Local Relay
    # =====================================================================

    async def _try_local_relay(self) -> bool:
        """Connect through the local relay server on Pi5."""
        relay = self._local_relay
        if not relay or not relay.transport:
            return False

        _LOGGER.debug("Trying local relay for %s", self.device_id)

        try:
            loop = asyncio.get_event_loop()
            self._protocol = _PNZEOProtocol(self)

            # Connect to local relay
            relay_host = "127.0.0.1"
            relay_port = relay.port

            self._transport, _ = await asyncio.wait_for(
                loop.create_datagram_endpoint(
                    lambda: self._protocol,
                    remote_addr=(relay_host, relay_port),
                ),
                timeout=CONNECT_TIMEOUT,
            )

            # Step 1: Hello
            self._transport.sendto(build_hello())
            ack = await self._wait_for_f1xx(PktType.HELLO_ACK, 3.0)
            if not ack:
                _LOGGER.debug("No Hello ACK from local relay")
                await self._cleanup_transport()
                return False

            # Step 2: P2P Connect (tell relay which camera we want)
            self._transport.sendto(build_p2p_connect(self.device_id))
            # Wait for punch_to (camera info) — might not get it if camera not registered
            await self._wait_for_f1xx(PktType.PUNCH_TO, 2.0)

            # Step 3: Request relay session
            self._transport.sendto(build_relay_request(self.device_id))
            relay_info = await self._wait_for_f1xx(PktType.LIST_REQ_ACK, 3.0)
            if not relay_info:
                _LOGGER.debug("No relay info from local relay")
                await self._cleanup_transport()
                return False

            # Step 4: Relay handshake (hello → port → punch)
            self._transport.sendto(build_relay_hello())
            if not await self._wait_for_f1xx(PktType.RLY_HELLO_ACK, 3.0):
                await self._cleanup_transport()
                return False

            self._transport.sendto(build_relay_port_req())
            port_ack = await self._wait_for_f1xx(PktType.RLY_PORT_ACK, 3.0)
            session_token = b""
            if port_ack and len(port_ack) > 10:
                parsed = parse_relay_port_ack(port_ack)
                if parsed:
                    session_token = parsed.get("session_token", b"")

            # Step 5: Relay punch (send UID multiple times)
            for _ in range(RELAY_PUNCH_COUNT):
                self._transport.sendto(
                    build_relay_punch(self.device_id, session_token)
                )
                await asyncio.sleep(RELAY_PUNCH_INTERVAL)

            # Step 6: Wait for relay ready
            rdy = await self._wait_for_f1xx(PktType.RLY_RDY, 5.0)
            if not rdy:
                # Even without explicit RDY, camera might be connected
                _LOGGER.debug("No explicit RLY_RDY, trying auth anyway")

            self._connected = True
            self._connection_method = "local_relay"
            self._keepalive_interval = RELAY_KEEPALIVE_INTERVAL

            # Authenticate
            if await self._authenticate():
                self._keepalive_task = asyncio.create_task(self._keepalive_loop())
                _LOGGER.info(
                    "Connected to camera %s via local relay", self.device_id,
                )
                return True

            await self._cleanup_transport()
            return False

        except Exception as ex:
            _LOGGER.debug("Local relay failed: %s", ex)
            await self._cleanup_transport()
            return False

    # =====================================================================
    # Connection Method: LAN Direct
    # =====================================================================

    async def _try_lan(self, port: int, method_name: str) -> bool:
        """Try direct LAN connection with proper handshake."""
        _LOGGER.debug("Trying %s on %s:%d", method_name, self.host, port)
        try:
            await self._cleanup_transport()
            loop = asyncio.get_event_loop()
            self._protocol = _PNZEOProtocol(self)

            self._transport, _ = await asyncio.wait_for(
                loop.create_datagram_endpoint(
                    lambda: self._protocol,
                    remote_addr=(self.host, port),
                ),
                timeout=CONNECT_TIMEOUT,
            )

            # Send discovery
            if port == PPPP_PORT_DH_LAN:
                self._transport.sendto(build_dh_discovery())
            else:
                self._transport.sendto(build_lan_search())

            # Wait for response
            response = await self._wait_for_any_f1xx(3.0)
            if not response:
                _LOGGER.debug("No response on %s:%d", self.host, port)
                await self._cleanup_transport()
                return False

            # Try P2P_RDY handshake
            self._transport.sendto(build_p2p_rdy())

            # Start fast keepalive immediately (camera needs it)
            self._connected = True
            self._keepalive_interval = LAN_KEEPALIVE
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())

            # Give camera time to accept our keepalive
            await asyncio.sleep(1.0)

            self.port = port
            self._connection_method = method_name

            # Try to authenticate
            if await self._authenticate():
                _LOGGER.info(
                    "Connected to camera at %s:%d via %s",
                    self.host, port, method_name,
                )
                return True

            # Auth failed — LAN doesn't support DRW
            if self._keepalive_task:
                self._keepalive_task.cancel()
                self._keepalive_task = None
            await self._cleanup_transport()
            return False

        except Exception as ex:
            _LOGGER.debug("%s on %s:%d failed: %s", method_name, self.host, port, ex)
            await self._cleanup_transport()
            return False

    # =====================================================================
    # Connection Method: Cloud Relay
    # =====================================================================

    async def _try_cloud_relay(self) -> bool:
        """Connect through cloud P2P relay servers.

        Full flow: Hello → P2P_REQ → Relay_REQ → Relay handshake → DRW
        """
        for server_host, server_port in CLOUD_P2P_SERVERS:
            _LOGGER.debug("Trying cloud relay via %s:%d", server_host, server_port)
            try:
                # ---- Phase A: P2P handshake with cloud server ----
                await self._cleanup_transport()
                loop = asyncio.get_event_loop()
                self._protocol = _PNZEOProtocol(self)

                self._transport, _ = await asyncio.wait_for(
                    loop.create_datagram_endpoint(
                        lambda: self._protocol,
                        remote_addr=(server_host, server_port),
                    ),
                    timeout=CONNECT_TIMEOUT,
                )

                # Hello
                self._transport.sendto(build_hello())
                if not await self._wait_for_f1xx(PktType.HELLO_ACK, HANDSHAKE_TIMEOUT):
                    await self._cleanup_transport()
                    continue

                # P2P Connect (register interest in our camera UID)
                self._transport.sendto(build_p2p_connect(self.device_id))
                # Wait for PUNCH_TO (camera info) or P2P_REQ_ACK
                await self._wait_for_any_f1xx(3.0)

                # ---- Phase B: Request relay servers ----
                self._transport.sendto(build_relay_request(self.device_id))
                relay_data = await self._wait_for_f1xx(PktType.LIST_REQ_ACK, 5.0)
                if not relay_data:
                    _LOGGER.debug("No relay info from %s", server_host)
                    await self._cleanup_transport()
                    continue

                relay_servers = parse_relay_info(relay_data)
                if not relay_servers:
                    _LOGGER.debug("Empty relay list from %s", server_host)
                    await self._cleanup_transport()
                    continue

                # Done with P2P server
                p2p_transport = self._transport
                self._transport = None

                # ---- Phase C: Connect to relay node ----
                connected = False
                for relay_ip, relay_port in relay_servers[:3]:
                    _LOGGER.debug("Trying relay node %s:%d", relay_ip, relay_port)
                    try:
                        self._protocol = _PNZEOProtocol(self)
                        self._transport, _ = await asyncio.wait_for(
                            loop.create_datagram_endpoint(
                                lambda: self._protocol,
                                remote_addr=(relay_ip, relay_port),
                            ),
                            timeout=CONNECT_TIMEOUT,
                        )

                        # Relay Hello
                        self._transport.sendto(build_relay_hello())
                        if not await self._wait_for_f1xx(PktType.RLY_HELLO_ACK, 3.0):
                            await self._cleanup_transport()
                            continue

                        # Relay Port
                        self._transport.sendto(build_relay_port_req())
                        port_data = await self._wait_for_f1xx(PktType.RLY_PORT_ACK, 3.0)
                        session_token = b""
                        if port_data:
                            parsed = parse_relay_port_ack(port_data)
                            if parsed:
                                session_token = parsed.get("session_token", b"")

                        # ---- Phase D: Relay punch ----
                        for i in range(RELAY_PUNCH_COUNT):
                            self._transport.sendto(
                                build_relay_punch(self.device_id, session_token)
                            )
                            await asyncio.sleep(RELAY_PUNCH_INTERVAL)

                        # Wait for camera to connect to relay
                        rdy = await self._wait_for_f1xx(PktType.RLY_RDY, 5.0)
                        if not rdy:
                            # Try anyway — some relays don't send explicit RDY
                            await asyncio.sleep(2.0)

                        connected = True
                        break

                    except Exception as ex:
                        _LOGGER.debug("Relay node %s:%d failed: %s", relay_ip, relay_port, ex)
                        await self._cleanup_transport()
                        continue

                # Close P2P server transport
                try:
                    p2p_transport.close()
                except Exception:
                    pass

                if not connected:
                    continue

                # ---- Phase E: Authenticate through relay ----
                self._connected = True
                self._connection_method = "cloud_relay"
                self._keepalive_interval = RELAY_KEEPALIVE_INTERVAL

                if await self._authenticate():
                    self._keepalive_task = asyncio.create_task(self._keepalive_loop())
                    _LOGGER.info(
                        "Connected to camera %s via cloud relay", self.device_id,
                    )
                    return True

                await self._cleanup_transport()

            except Exception as ex:
                _LOGGER.debug("Cloud relay via %s failed: %s", server_host, ex)
                await self._cleanup_transport()
                continue

        return False

    # =====================================================================
    # Authentication
    # =====================================================================

    async def _authenticate(self) -> bool:
        """Send login (MSG_GET_CAPABILITY with credentials)."""
        if not self._transport:
            return False
        try:
            login_data = encode_login(self.username, self.password)
            cmd = encode_command(MSG_GET_CAPABILITY, login_data)
            self._send_cmd(cmd)

            # Wait for response (use DRW waiter)
            response = await self._wait_for_drw_response(MSG_GET_CAPABILITY, 5.0)
            if response is not None:
                self._authenticated = True
                _LOGGER.debug("Authentication successful")
                return True

            # Fallback: even without explicit response, consider auth OK
            # (some cameras don't send capability response)
            await asyncio.sleep(1.0)
            self._authenticated = True
            return True

        except Exception as ex:
            _LOGGER.debug("Authentication error: %s", ex)
            return False

    async def login(self, username: str, password: str) -> bool:
        """Verify credentials via PPPP login. Returns True if accepted."""
        if not self._connected or not self._transport:
            return False
        try:
            login_data = encode_login(username, password)
            cmd = encode_command(MSG_GET_CAPABILITY, login_data)
            self._send_cmd(cmd)

            response = await self._wait_for_drw_response(MSG_GET_CAPABILITY, 5.0)
            return response is not None

        except Exception as ex:
            _LOGGER.debug("Login error: %s", ex)
            return False

    # =====================================================================
    # Message waiting helpers
    # =====================================================================

    async def _wait_for_f1xx(self, expected_type: int, timeout: float) -> bytes | None:
        """Wait for a specific F1xx signaling message. Returns raw packet data."""
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._msg_waiters[expected_type] = future
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._msg_waiters.pop(expected_type, None)

    async def _wait_for_any_f1xx(self, timeout: float) -> bytes | None:
        """Wait for any F1xx signaling message."""
        return await self._wait_for_f1xx(0xFF, timeout)  # 0xFF = any

    async def _wait_for_drw_response(self, msg_type: int, timeout: float) -> bytes | None:
        """Wait for a DRW response with specific camera msg_type."""
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._drw_waiters[msg_type] = future
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._drw_waiters.pop(msg_type, None)

    def _complete_f1xx_waiter(self, pkt_type: int, data: bytes) -> None:
        """Resolve a pending F1xx waiter."""
        # Specific waiter
        waiter = self._msg_waiters.pop(pkt_type, None)
        if waiter and not waiter.done():
            waiter.set_result(data)
        # "Any" waiter
        any_waiter = self._msg_waiters.pop(0xFF, None)
        if any_waiter and not any_waiter.done():
            any_waiter.set_result(data)

    def _complete_drw_waiter(self, msg_type: int, payload: bytes) -> None:
        """Resolve a pending DRW response waiter."""
        waiter = self._drw_waiters.pop(msg_type, None)
        if waiter and not waiter.done():
            waiter.set_result(payload)

    # =====================================================================
    # Transport helpers
    # =====================================================================

    async def _cleanup_transport(self) -> None:
        """Clean up current transport."""
        if self._keepalive_task:
            self._keepalive_task.cancel()
            self._keepalive_task = None
        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None
        self._protocol = None
        self._connected = False
        self._authenticated = False

    async def _keepalive_loop(self) -> None:
        """Send periodic keepalive packets."""
        while self._connected:
            try:
                if self._transport:
                    self._transport.sendto(build_alive())
                await asyncio.sleep(self._keepalive_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    def _send_cmd(self, data: bytes, channel: int = CH_CMD) -> None:
        """Send command packet via DRW."""
        if not self._transport:
            return
        self._cmd_index = (self._cmd_index + 1) % 65536
        pkt = build_drw(channel, data, self._cmd_index)
        self._transport.sendto(pkt)

    # =====================================================================
    # High-level commands
    # =====================================================================

    async def send_command(self, msg_type: int, params: bytes = b"") -> bool:
        """Send a command to camera and wait for ACK."""
        if not self._connected:
            return False
        try:
            cmd = encode_command(msg_type, params)
            self._send_cmd(cmd)
            # Wait briefly for DRW ACK (not the full response)
            await asyncio.sleep(0.3)
            return True
        except Exception as ex:
            _LOGGER.error("Send command error: %s", ex)
            return False

    async def send_command_with_response(
        self, msg_type: int, params: bytes = b"", timeout: float = 5.0
    ) -> bytes | None:
        """Send a command and wait for the response payload."""
        if not self._connected or not self._transport:
            return None
        try:
            cmd = encode_command(msg_type, params)
            self._send_cmd(cmd)
            return await self._wait_for_drw_response(msg_type, timeout)
        except Exception as ex:
            _LOGGER.error("Send command error: %s", ex)
            return None

    async def get_user_info(self) -> list[dict]:
        """Get user accounts from camera."""
        response = await self.send_command_with_response(MSG_GET_USER_INFO)
        if response:
            return parse_user_info(response)
        return []

    async def change_password(self, new_password: str, username: str = "admin") -> bool:
        """Change camera password."""
        users = await self.get_user_info()
        if not users:
            users = [
                {"username": "admin", "password": self.password},
                {"username": "", "password": ""},
                {"username": "", "password": ""},
            ]
        while len(users) < 3:
            users.append({"username": "", "password": ""})

        found = False
        for user in users:
            if user["username"] == username:
                user["password"] = new_password
                found = True
                break
        if not found:
            return False

        params = encode_user_setting(
            users[0]["username"], users[0]["password"],
            users[1]["username"], users[1]["password"],
            users[2]["username"], users[2]["password"],
        )
        result = await self.send_command(MSG_SET_USER, params)
        if result:
            self.password = new_password
        return result

    # --- Camera control shortcuts ---

    async def get_status(self) -> dict[str, Any]:
        resp = await self.send_command_with_response(MSG_GET_STATUS)
        return self._state

    async def get_camera_params(self) -> dict[str, Any]:
        resp = await self.send_command_with_response(MSG_GET_CAMERA_PARAMS)
        return self._state

    async def reboot(self) -> bool:
        return await self.send_command(MSG_REBOOT)

    async def factory_reset(self) -> bool:
        return await self.send_command(MSG_FACTORY_RESET)

    async def snapshot(self) -> bool:
        return await self.send_command(MSG_SNAPSHOT)

    async def format_sd(self) -> bool:
        return await self.send_command(MSG_FORMAT_SD)

    async def set_brightness(self, value: int) -> bool:
        return await self.send_command(MSG_CAMERA_CONTROL, encode_camera_control(CMD_SET_BRIGHTNESS, value))

    async def set_contrast(self, value: int) -> bool:
        return await self.send_command(MSG_CAMERA_CONTROL, encode_camera_control(CMD_SET_CONTRAST, value))

    async def set_resolution(self, value: int) -> bool:
        return await self.send_command(MSG_CAMERA_CONTROL, encode_camera_control(CMD_SET_RESOLUTION, value))

    async def set_mirror(self, mode: int) -> bool:
        return await self.send_command(MSG_CAMERA_CONTROL, encode_camera_control(CMD_SET_MIRROR, mode))

    async def set_ir_led(self, on: bool) -> bool:
        return await self.send_command(MSG_CAMERA_CONTROL, encode_camera_control(CMD_SET_LIGHT, 1 if on else 0))

    async def set_indicator_led(self, on: bool) -> bool:
        return await self.send_command(MSG_CAMERA_CONTROL, encode_camera_control(CMD_SET_LED, 1 if on else 0))

    async def ptz_control(self, direction: int, step: int = 1) -> bool:
        return await self.send_command(MSG_GET_CAMERA_PARAMS, encode_ptz(direction, step))

    async def set_motion_detection(self, enabled: bool) -> bool:
        return await self.send_command(MSG_SET_ALARM_EX, struct.pack("<B", 1 if enabled else 0))

    async def set_recording_mode(self, mode: int) -> bool:
        return await self.send_command(MSG_SET_REC_MODE, struct.pack("<BB", mode, 0))

    # =====================================================================
    # Response handler (called by protocol)
    # =====================================================================

    def _handle_response(self, data: bytes) -> None:
        """Handle incoming DRW response payload."""
        if len(data) < 4:
            return
        msg_type, payload = decode_response(data)
        _LOGGER.debug("Response msg_type=%d payload_len=%d", msg_type, len(payload))
        # Store in state
        self._state[f"msg_{msg_type}"] = payload
        self._state["last_response"] = msg_type
        # Resolve DRW waiter
        self._complete_drw_waiter(msg_type, payload)


class _PNZEOProtocol(asyncio.DatagramProtocol):
    """UDP protocol handler — handles all PPPP packet types."""

    def __init__(self, client: PNZEOClient) -> None:
        self.client = client

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        if len(data) < 2:
            return

        first_byte = data[0]

        # PPPP F1xx packets
        if first_byte == 0xF1 and len(data) >= 4:
            pkt_type = data[1]

            # Data layer (DRW, ACK, ALIVE, CLOSE)
            if pkt_type == PktType.DRW:
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

            elif pkt_type == PktType.DRW_ACK:
                pass  # command acknowledged

            elif pkt_type == PktType.ALIVE:
                # Camera sends keepalive → respond
                if self.client._transport:
                    try:
                        self.client._transport.sendto(build_alive_ack())
                    except Exception:
                        pass

            elif pkt_type == PktType.ALIVE_ACK:
                pass  # our keepalive confirmed

            elif pkt_type == PktType.CLOSE:
                self.client._connected = False

            else:
                # F1xx signaling message → resolve waiters
                self.client._complete_f1xx_waiter(pkt_type, data)

        # DH protocol response
        elif first_byte == 0x44 and len(data) >= 4 and data[1] == 0x48:
            # Treat DH response as a generic signaling response
            self.client._complete_f1xx_waiter(0xFF, data)

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("UDP error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        self.client._connected = False
