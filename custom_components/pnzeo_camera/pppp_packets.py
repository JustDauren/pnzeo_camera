"""PPPP protocol packet encoding/decoding for PNZEO cameras."""
from __future__ import annotations

import struct
from enum import IntEnum


class PktType(IntEnum):
    """PPPP packet types."""
    HELLO = 0xF1
    LAN_SEARCH = 0x67
    LAN_SEARCH_ACK = 0x68
    PUNCH_PKT = 0x41
    P2P_RDY = 0x42
    DRW = 0xD0
    DRW_ACK = 0xD1
    ALIVE = 0xE0
    ALIVE_ACK = 0xE1
    CLOSE = 0xF0
    MGM = 0xF4


# PPPP magic
PPPP_MAGIC = b"\xf1"


def build_lan_search() -> bytes:
    """Build LAN search broadcast packet."""
    # Minimal LAN search: magic(1) + type(1) + size(2) + payload
    # Based on aiopppp: PktLanSearch is just header with random data
    import os
    random_bytes = os.urandom(4)
    header = struct.pack(">BBH", 0xF1, PktType.LAN_SEARCH, len(random_bytes))
    return header + random_bytes


def parse_lan_search_ack(data: bytes) -> dict | None:
    """Parse LAN search response. Returns device info dict or None."""
    if len(data) < 4:
        return None
    magic, pkt_type, payload_len = struct.unpack(">BBH", data[:4])
    if pkt_type != PktType.LAN_SEARCH_ACK:
        return None
    payload = data[4:4 + payload_len]
    # Device ID is typically in the payload as a null-terminated string
    try:
        device_id = payload.split(b"\x00")[0].decode("ascii", errors="ignore")
        if device_id and device_id.startswith("MTC"):
            return {"device_id": device_id, "raw": payload}
    except Exception:
        pass
    # Alternative: device ID at known offset
    if len(payload) >= 20:
        for offset in range(0, min(len(payload) - 3, 40)):
            chunk = payload[offset:offset + 24]
            try:
                text = chunk.decode("ascii", errors="ignore")
                idx = text.find("MTC")
                if idx >= 0:
                    did = text[idx:].split("\x00")[0].split(" ")[0]
                    if len(did) >= 10:
                        return {"device_id": did, "raw": payload}
            except Exception:
                continue
    return None


def build_drw(channel: int, data: bytes, index: int = 0) -> bytes:
    """Build DRW (data) packet for sending commands."""
    # DRW header: magic(1) + type(1) + channel(1) + index(2) + size(2) + payload
    header = struct.pack(">BBBHH", 0xF1, PktType.DRW, channel, index, len(data))
    return header + data


def build_alive() -> bytes:
    """Build keepalive packet."""
    return struct.pack(">BBH", 0xF1, PktType.ALIVE, 0)


def build_close() -> bytes:
    """Build close connection packet."""
    return struct.pack(">BBH", 0xF1, PktType.CLOSE, 0)


def encode_command(msg_type: int, params: bytes = b"") -> bytes:
    """Encode a camera command for sending over PPPP.

    The command format used by minicam/PPPP cameras:
    Header: 4 bytes - [0x00, msg_type(2 bytes LE), flags]
    Then params follow.
    """
    # Based on aiopppp binary command format:
    # struct: command_id (2 bytes LE) + payload_len (2 bytes LE) + payload
    cmd_header = struct.pack("<HH", msg_type, len(params))
    return cmd_header + params


def decode_response(data: bytes) -> tuple[int, bytes]:
    """Decode a camera response.

    Returns (msg_type, payload).
    """
    if len(data) < 4:
        return (-1, b"")
    msg_type, payload_len = struct.unpack("<HH", data[:4])
    payload = data[4:4 + payload_len]
    return (msg_type, payload)


def encode_login(username: str, password: str) -> bytes:
    """Encode login command."""
    # Login format: username(32 bytes padded) + password(32 bytes padded)
    user_bytes = username.encode("ascii")[:32].ljust(32, b"\x00")
    pwd_bytes = password.encode("ascii")[:32].ljust(32, b"\x00")
    return user_bytes + pwd_bytes


def encode_camera_control(cmd_type: int, value: int) -> bytes:
    """Encode camera control command (brightness, contrast, mirror, etc.)."""
    return struct.pack("<BBH", cmd_type, value, 0)


def encode_ptz(direction: int, step_mode: int = 1) -> bytes:
    """Encode PTZ control command."""
    return struct.pack("<BB", direction, step_mode)
