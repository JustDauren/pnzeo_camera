"""Local PPPP relay server for PNZEO cameras.

Runs on Pi5 inside HA, replaces cloud infrastructure entirely.
Camera thinks it's talking to the cloud — but everything stays local.

Architecture:
  [Camera] ──UDP──> [Local Relay :32100] <──UDP── [HA Integration]
                          │
              iptables DNAT redirects camera's
              cloud traffic (182.92.x, 54.x) to Pi5

The relay handles:
1. Camera registration (DEV_LGN) — camera "goes online"
2. Client relay requests — HA integration asks to connect
3. DRW bridging — forwards commands/responses between HA and camera
4. Keepalive — keeps both sides alive
"""
from __future__ import annotations

import asyncio
import logging
import os
import struct
import time
from dataclasses import dataclass, field
from typing import Any

from .pppp_packets import (
    PktType,
    build_alive_ack,
    build_dev_lgn_ack,
    build_dev_lgn_crc_ack,
    build_hello_ack,
    build_punch_to,
    build_relay_hello_ack,
    build_relay_list_ack,
    build_relay_port_ack,
    build_relay_rdy,
    build_relay_to,
    decode_uid,
    parse_f1xx_header,
)

_LOGGER = logging.getLogger(__name__)

RELAY_PORT = 32100
RELAY_SESSION_TIMEOUT = 300  # 5 min without activity → drop session
CAMERA_REG_TIMEOUT = 120     # 2 min without re-registration → camera offline
KEEPALIVE_INTERVAL = 10      # Send keepalive to camera every 10s


@dataclass
class CameraRegistration:
    """A registered camera."""
    uid: str
    address: tuple[str, int]  # (IP, port)
    device_id: str = ""
    last_seen: float = 0.0
    raw_lgn: bytes = b""  # original DEV_LGN payload for debugging

    @property
    def is_alive(self) -> bool:
        return (time.monotonic() - self.last_seen) < CAMERA_REG_TIMEOUT


@dataclass
class RelaySession:
    """An active relay session bridging client ↔ camera."""
    session_id: str
    camera_uid: str
    client_addr: tuple[str, int] | None = None
    camera_relay_addr: tuple[str, int] | None = None
    created: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    session_token: bytes = b""
    ready: bool = False
    # Futures for async waiting
    _camera_connected: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def is_alive(self) -> bool:
        return (time.monotonic() - self.last_activity) < RELAY_SESSION_TIMEOUT

    async def wait_camera(self, timeout: float = 10.0) -> bool:
        """Wait for camera to connect to this relay session."""
        try:
            await asyncio.wait_for(self._camera_connected.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


class PPPPLocalRelay:
    """Local PPPP relay server — replaces cloud P2P infrastructure.

    Runs as part of the HA integration. Listens on UDP 32100.
    Camera's traffic to cloud servers is redirected here via iptables DNAT.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = RELAY_PORT) -> None:
        self.host = host
        self.port = port
        self.transport: asyncio.DatagramTransport | None = None
        self._cameras: dict[str, CameraRegistration] = {}  # uid → registration
        self._sessions: dict[str, RelaySession] = {}  # session_id → session
        self._session_by_addr: dict[tuple, RelaySession] = {}  # addr → session
        self._session_counter = 0
        self._cleanup_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._running = False

    @property
    def cameras(self) -> dict[str, CameraRegistration]:
        """Currently registered cameras."""
        return {uid: cam for uid, cam in self._cameras.items() if cam.is_alive}

    def get_camera_by_device_id(self, device_id: str) -> CameraRegistration | None:
        """Find a registered camera by its device_id."""
        for cam in self._cameras.values():
            if cam.device_id == device_id and cam.is_alive:
                return cam
        return None

    async def start(self) -> bool:
        """Start the relay server."""
        if self._running:
            return True

        try:
            loop = asyncio.get_event_loop()
            self.transport, _ = await loop.create_datagram_endpoint(
                lambda: _RelayProtocol(self),
                local_addr=(self.host, self.port),
            )
            self._running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            self._keepalive_task = asyncio.create_task(self._camera_keepalive_loop())
            _LOGGER.info(
                "PPPP Local Relay started on %s:%d — ready for camera connections",
                self.host, self.port,
            )
            return True
        except OSError as ex:
            _LOGGER.error("Cannot start relay on %s:%d: %s", self.host, self.port, ex)
            return False

    async def stop(self) -> None:
        """Stop the relay server."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
        if self._keepalive_task:
            self._keepalive_task.cancel()
        if self.transport:
            self.transport.close()
            self.transport = None
        self._cameras.clear()
        self._sessions.clear()
        self._session_by_addr.clear()
        _LOGGER.info("PPPP Local Relay stopped")

    # ---- Session management ----

    def create_session(self, camera_uid: str, client_addr: tuple[str, int]) -> RelaySession:
        """Create a new relay session for a client wanting to talk to a camera."""
        self._session_counter += 1
        session_id = f"rly_{self._session_counter}"
        token = struct.pack(">I", self._session_counter) + os.urandom(4)
        session = RelaySession(
            session_id=session_id,
            camera_uid=camera_uid,
            client_addr=client_addr,
            session_token=token,
        )
        self._sessions[session_id] = session
        self._session_by_addr[client_addr] = session
        _LOGGER.debug("Created relay session %s for camera %s", session_id, camera_uid)
        return session

    def find_session_by_token(self, token: bytes) -> RelaySession | None:
        """Find a relay session by its token."""
        for session in self._sessions.values():
            if session.session_token == token[:len(session.session_token)]:
                return session
        return None

    async def request_camera_connect(self, session: RelaySession) -> bool:
        """Tell a camera to connect to our relay for this session.

        Sends MSG_RLY_TO to the camera's registered address.
        Returns True if camera connects within timeout.
        """
        camera = self._cameras.get(session.camera_uid)
        if not camera or not camera.is_alive:
            _LOGGER.warning("Camera %s not registered", session.camera_uid)
            return False

        if not self.transport:
            return False

        # Get our IP (the one the camera should connect to for relay)
        relay_ip = self._get_our_ip(camera.address[0])
        relay_port = self.port

        # Send RLY_TO to camera — "connect to relay at ip:port with this token"
        rly_to = build_relay_to(relay_ip, relay_port, session.session_token)
        self.transport.sendto(rly_to, camera.address)
        _LOGGER.debug(
            "Sent RLY_TO to camera %s at %s — connect to %s:%d",
            session.camera_uid, camera.address, relay_ip, relay_port,
        )

        # Wait for camera to connect
        return await session.wait_camera(timeout=10.0)

    # ---- Packet handlers (called by protocol) ----

    def handle_dev_lgn(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle camera registration (DEV_LGN or DEV_LGN_CRC)."""
        parsed = parse_f1xx_header(data)
        if not parsed:
            return

        pkt_type, _, payload = parsed

        # Extract UID from PPRT block in payload
        uid = None
        pprt_idx = payload.find(b"PPRT")
        if pprt_idx >= 0 and pprt_idx + 20 <= len(payload):
            uid = decode_uid(payload[pprt_idx:pprt_idx + 20])

        if not uid:
            uid = f"unknown_{addr[0]}_{addr[1]}"

        # Extract device_id if present as text
        device_id = ""
        try:
            text = payload.decode("ascii", errors="ignore")
            mtc_idx = text.find("MTC")
            if mtc_idx >= 0:
                device_id = text[mtc_idx:].split("\x00")[0].split(" ")[0]
        except Exception:
            pass

        # Register or update camera
        if uid in self._cameras:
            cam = self._cameras[uid]
            cam.address = addr
            cam.last_seen = time.monotonic()
            cam.raw_lgn = payload
            if device_id:
                cam.device_id = device_id
        else:
            cam = CameraRegistration(
                uid=uid,
                address=addr,
                device_id=device_id,
                last_seen=time.monotonic(),
                raw_lgn=payload,
            )
            self._cameras[uid] = cam
            _LOGGER.info(
                "Camera registered: uid=%s device_id=%s addr=%s",
                uid, device_id, addr,
            )

        # Send ACK — camera is now "online"
        if self.transport:
            if pkt_type == PktType.DEV_LGN_CRC:
                self.transport.sendto(build_dev_lgn_crc_ack(0), addr)
            else:
                self.transport.sendto(build_dev_lgn_ack(0), addr)

    def handle_hello(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle Hello from client. Respond with Hello ACK."""
        if self.transport:
            # Include a session nonce in the ACK
            session_bytes = struct.pack(">I", int(time.monotonic())) + os.urandom(12)
            self.transport.sendto(build_hello_ack(session_bytes), addr)

    def handle_p2p_req(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle P2P Connect request from client."""
        parsed = parse_f1xx_header(data)
        if not parsed or not self.transport:
            return

        _, _, payload = parsed

        # Extract target camera UID
        uid = None
        pprt_idx = payload.find(b"PPRT")
        if pprt_idx >= 0 and pprt_idx + 20 <= len(payload):
            uid = decode_uid(payload[pprt_idx:pprt_idx + 20])

        if not uid:
            _LOGGER.debug("P2P_REQ without UID from %s", addr)
            return

        # Find the camera
        camera = self._cameras.get(uid)
        if camera and camera.is_alive:
            # Send PUNCH_TO with camera's LAN address
            punch = build_punch_to(camera.address[0], camera.address[1])
            self.transport.sendto(punch, addr)
            _LOGGER.debug("P2P_REQ for %s → PUNCH_TO %s", uid, camera.address)
        else:
            _LOGGER.debug("P2P_REQ for unknown/offline camera %s", uid)

    def handle_relay_list_req(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle relay server list request. Return ourselves as relay."""
        if not self.transport:
            return

        our_ip = self._get_our_ip(addr[0])
        # Return ourselves as the only relay server
        ack = build_relay_list_ack([(our_ip, self.port)])
        self.transport.sendto(ack, addr)
        _LOGGER.debug("Relay list request from %s → returning %s:%d", addr, our_ip, self.port)

    def handle_relay_hello(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle Relay Hello from client or camera."""
        if self.transport:
            self.transport.sendto(build_relay_hello_ack(), addr)

    def handle_relay_port(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle Relay Port request. Allocate relay endpoint."""
        if not self.transport:
            return

        our_ip = self._get_our_ip(addr[0])
        # Use our own port as relay endpoint (we handle everything on one port)
        token = struct.pack(">I", int(time.monotonic())) + os.urandom(4)
        ack = build_relay_port_ack(our_ip, self.port, token)
        self.transport.sendto(ack, addr)

    def handle_relay_punch(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle Relay Punch from client. Associates this addr with a session."""
        parsed = parse_f1xx_header(data)
        if not parsed:
            return

        _, _, payload = parsed

        # Extract UID
        uid = None
        pprt_idx = payload.find(b"PPRT")
        if pprt_idx >= 0 and pprt_idx + 20 <= len(payload):
            uid = decode_uid(payload[pprt_idx:pprt_idx + 20])

        if not uid:
            return

        # Find or create session for this UID
        session = None
        for s in self._sessions.values():
            if s.camera_uid == uid and s.is_alive:
                session = s
                break

        if not session:
            session = self.create_session(uid, addr)

        # Determine if this is client or camera connecting
        camera = self._cameras.get(uid)
        if camera and addr == camera.address:
            # Camera is connecting to relay
            session.camera_relay_addr = addr
            session.last_activity = time.monotonic()
            session.ready = True
            session._camera_connected.set()
            _LOGGER.debug("Camera %s connected to relay session %s", uid, session.session_id)
            # Send relay ready
            if self.transport:
                self.transport.sendto(build_relay_rdy(), addr)
        else:
            # Client connecting
            session.client_addr = addr
            session.last_activity = time.monotonic()
            self._session_by_addr[addr] = session
            _LOGGER.debug("Client %s joined relay session %s for camera %s", addr, session.session_id, uid)

    def handle_drw(self, data: bytes, addr: tuple[str, int]) -> None:
        """Forward DRW packet between client and camera."""
        session = self._session_by_addr.get(addr)
        if not session or not self.transport:
            return

        session.last_activity = time.monotonic()
        camera = self._cameras.get(session.camera_uid)
        if not camera:
            return

        if addr == session.client_addr:
            # From client → forward to camera
            target = session.camera_relay_addr or camera.address
            self.transport.sendto(data, target)
        elif addr == session.camera_relay_addr or addr == camera.address:
            # From camera → forward to client
            if session.client_addr:
                self.transport.sendto(data, session.client_addr)

    def handle_alive(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle keepalive from camera or client."""
        # Update camera last_seen if it's from a registered camera
        for cam in self._cameras.values():
            if cam.address == addr:
                cam.last_seen = time.monotonic()
                break

        # Update session activity
        session = self._session_by_addr.get(addr)
        if session:
            session.last_activity = time.monotonic()

        # Send ACK
        if self.transport:
            self.transport.sendto(build_alive_ack(), addr)

    # ---- Internal helpers ----

    def _get_our_ip(self, peer_ip: str) -> str:
        """Get our IP address that's reachable from the given peer."""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((peer_ip, 1))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "0.0.0.0"

    async def _cleanup_loop(self) -> None:
        """Periodically clean up dead sessions and registrations."""
        while self._running:
            try:
                await asyncio.sleep(60)
                # Clean dead sessions
                dead = [sid for sid, s in self._sessions.items() if not s.is_alive]
                for sid in dead:
                    session = self._sessions.pop(sid, None)
                    if session and session.client_addr:
                        self._session_by_addr.pop(session.client_addr, None)
                    if session and session.camera_relay_addr:
                        self._session_by_addr.pop(session.camera_relay_addr, None)

                # Clean dead cameras
                dead_cams = [uid for uid, c in self._cameras.items() if not c.is_alive]
                for uid in dead_cams:
                    _LOGGER.info("Camera %s went offline (no re-registration)", uid)
                    self._cameras.pop(uid, None)

            except asyncio.CancelledError:
                break
            except Exception as ex:
                _LOGGER.debug("Cleanup error: %s", ex)

    async def _camera_keepalive_loop(self) -> None:
        """Send keepalive to registered cameras to maintain connection."""
        while self._running:
            try:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                if not self.transport:
                    continue
                for cam in list(self._cameras.values()):
                    if cam.is_alive:
                        alive = struct.pack(">BBH", 0xF1, PktType.ALIVE, 0)
                        self.transport.sendto(alive, cam.address)
            except asyncio.CancelledError:
                break
            except Exception:
                pass


class _RelayProtocol(asyncio.DatagramProtocol):
    """UDP protocol handler for the local relay server."""

    def __init__(self, relay: PPPPLocalRelay) -> None:
        self.relay = relay

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        if len(data) < 2:
            return

        # DH protocol (camera might send DH discovery)
        if data[0] == 0x44 and len(data) >= 4 and data[1] == 0x48:
            return  # Ignore DH on relay port

        # PPPP protocol (F1xx)
        if data[0] != 0xF1:
            return

        pkt_type = data[1]

        # Device registration
        if pkt_type in (PktType.DEV_LGN, PktType.DEV_LGN_CRC):
            self.relay.handle_dev_lgn(data, addr)

        # P2P handshake
        elif pkt_type == PktType.HELLO:
            self.relay.handle_hello(data, addr)
        elif pkt_type == PktType.P2P_REQ:
            self.relay.handle_p2p_req(data, addr)

        # Relay negotiation
        elif pkt_type in (PktType.LIST_REQ, PktType.LIST_REQ1):
            self.relay.handle_relay_list_req(data, addr)
        elif pkt_type == PktType.RLY_HELLO:
            self.relay.handle_relay_hello(data, addr)
        elif pkt_type == PktType.RLY_PORT:
            self.relay.handle_relay_port(data, addr)
        elif pkt_type == PktType.RLY_PKT:
            self.relay.handle_relay_punch(data, addr)

        # Data forwarding
        elif pkt_type == PktType.DRW:
            self.relay.handle_drw(data, addr)
        elif pkt_type == PktType.DRW_ACK:
            self.relay.handle_drw(data, addr)  # Forward ACKs too

        # Keepalive
        elif pkt_type == PktType.ALIVE:
            self.relay.handle_alive(data, addr)
        elif pkt_type == PktType.ALIVE_ACK:
            # Update camera last_seen
            for cam in self.relay._cameras.values():
                if cam.address == addr:
                    cam.last_seen = time.monotonic()

        # Close
        elif pkt_type == PktType.CLOSE:
            _LOGGER.debug("Close from %s", addr)

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("Relay UDP error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        _LOGGER.debug("Relay connection lost: %s", exc)
