"""PPPP protocol packet encoding/decoding for PNZEO cameras.

Implements the two protocol layers:
1. F1xx signaling layer — P2P handshake, hole punching, relay
2. Data layer — DRW command/response packets after connection established

Also implements DH (DaHua-derived) LAN discovery on port 8600.
"""
from __future__ import annotations

import struct
from enum import IntEnum


class PktType(IntEnum):
    """PPPP packet types (data layer, single-byte)."""
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


# =============================================================================
# PPRT UID Encoding
# =============================================================================

def encode_uid(device_id: str) -> bytes:
    """Encode device ID into PPRT UID block (20 bytes).

    Example for device ID "MTC888-XXXXXX-XXXXX":
    Offset 0:  50 50 52 54 00 00 00 00  ("PPRT" + 4 null bytes)
    Offset 8:  00 09 XX XX XX XX XX XX  (prefix 0x0009 + transformed suffix)
    Offset 16: XX 00 00 00              (continued + 3 null bytes)

    The UID is derived from the device_id suffix. The exact encoding:
    - First 8 bytes: "PPRT" + 4x 0x00
    - Bytes 8-9: big-endian prefix (observed 0x0009)
    - Bytes 10-19: device_id encoded/transformed, null-padded to 10 bytes
    """
    # Extract the meaningful suffix from the device ID
    # MTC888-XXXXXX-XXXXX -> we need the parts that form the UID payload
    parts = device_id.split("-")

    # Build the PPRT header
    header = b"PPRT\x00\x00\x00\x00"

    # Build the UID payload from device ID
    # The suffix is transformed into UID content bytes using _transform_uid_suffix()

    if len(parts) >= 3:
        # Use the numeric and suffix parts
        suffix = parts[-1]  # e.g. "ABCDE"
        # Build UID bytes based on observed pattern
        # Prefix bytes (observed as 0x0009)
        prefix = struct.pack(">H", 0x0009)
        # The UID content — a transformed form of the suffix
        uid_content = _transform_uid_suffix(device_id)
        uid_payload = prefix + uid_content.ljust(10, b"\x00")[:10]
    else:
        # Fallback: use raw device_id bytes
        raw = device_id.encode("ascii")[:12]
        uid_payload = raw.ljust(12, b"\x00")

    return header + uid_payload


def _transform_uid_suffix(device_id: str) -> bytes:
    """Transform device ID into the UID content bytes.

    The transformation takes the serial number and suffix from the device ID
    (format: MTC888-XXXXXX-XXXXX) and derives UID content bytes:
    - First byte: hash-derived from the serial number, OR'd with 0x40
    - Second byte: hash-derived from the suffix, OR'd with 0x40
    - Remaining bytes: raw ASCII of the suffix
    """
    # Extract last segment and encode
    parts = device_id.split("-")
    suffix = parts[-1] if parts else device_id
    # Simple encoding: prepend two derived bytes then the suffix
    result = bytearray()
    # Use a hash-derived prefix byte
    serial = parts[1] if len(parts) > 1 else "000000"
    result.append((sum(ord(c) for c in serial) & 0xFF) | 0x40)
    result.append((sum(ord(c) for c in suffix) & 0xFF) | 0x40)
    result.extend(suffix.encode("ascii"))
    return bytes(result)


# =============================================================================
# F1xx Signaling Layer (P2P Handshake)
# =============================================================================

def build_hello() -> bytes:
    """Build Hello packet (0xF100). Client -> Server, 4 bytes."""
    return struct.pack(">HH", 0xF100, 0x0000)


def build_p2p_connect(device_id: str) -> bytes:
    """Build P2P Connect packet (0xF120). Client -> Server, 40 bytes.

    Contains PPRT + UID block (20 bytes) preceded by the F120 header.
    """
    uid_block = encode_uid(device_id)  # 20 bytes
    # F120 header: msg_type(2) + payload_len(2) = 4 bytes
    # Total: 4 + 20 + padding = 40 bytes
    header = struct.pack(">HH", 0xF120, len(uid_block))
    # Pad to 40 bytes total as observed in capture
    packet = header + uid_block
    padding_needed = 40 - len(packet)
    if padding_needed > 0:
        packet += b"\x00" * padding_needed
    return packet


def build_relay_request(device_id: str) -> bytes:
    """Build Relay Request packet (0xF167). 24 bytes with UID."""
    uid_block = encode_uid(device_id)  # 20 bytes
    header = struct.pack(">HH", 0xF167, len(uid_block))
    return header + uid_block


def build_punch(device_id: str, target_ip: str, target_port: int) -> bytes:
    """Build Punch packet (0xF180). 44 bytes."""
    uid_block = encode_uid(device_id)  # 20 bytes
    # Pack target address
    ip_parts = [int(x) for x in target_ip.split(".")]
    ip_bytes = bytes(ip_parts)
    port_bytes = struct.pack(">H", target_port)
    header = struct.pack(">HH", 0xF180, 0)
    # Build 44 byte packet
    packet = header + uid_block + ip_bytes + port_bytes
    padding_needed = 44 - len(packet)
    if padding_needed > 0:
        packet += b"\x00" * padding_needed
    return packet[:44]


def parse_f1xx_message(data: bytes) -> dict | None:
    """Parse an F1xx signaling message.

    Returns dict with 'type' and type-specific fields, or None.
    """
    if len(data) < 4:
        return None

    msg_type = struct.unpack(">H", data[0:2])[0]

    if msg_type == 0xF101:
        # Hello ACK — 20 bytes
        return {
            "type": "hello_ack",
            "msg_type": msg_type,
            "payload": data[2:],
        }

    elif msg_type == 0xF121:
        # P2P Ready — 8 bytes
        return {
            "type": "p2p_ready",
            "msg_type": msg_type,
            "payload": data[2:],
        }

    elif msg_type == 0xF140:
        # DRW Response — contains camera IP addresses (20 bytes)
        result = {
            "type": "drw_response",
            "msg_type": msg_type,
            "payload": data[2:],
        }
        # Try to extract IP addresses from payload
        if len(data) >= 12:
            result.update(_parse_drw_response_ips(data))
        return result

    elif msg_type == 0xF180:
        # Punch
        return {
            "type": "punch",
            "msg_type": msg_type,
            "payload": data[2:],
        }

    else:
        return {
            "type": "unknown_f1xx",
            "msg_type": msg_type,
            "payload": data[2:],
        }


def _parse_drw_response_ips(data: bytes) -> dict:
    """Extract public and LAN IP from DRW Response (0xF140).

    The response is 20 bytes. IPs are typically at offsets 4-8 (public, big-endian)
    and 8-12 (LAN, little-endian / reversed byte order).
    """
    result = {}
    payload = data[4:]  # skip 2-byte type + 2-byte length

    if len(payload) >= 8:
        # Try public IP (big-endian)
        try:
            pub_ip = f"{payload[0]}.{payload[1]}.{payload[2]}.{payload[3]}"
            result["public_ip"] = pub_ip
        except (IndexError, ValueError):
            pass

    if len(payload) >= 12:
        # Try LAN IP (little-endian / reversed as seen in capture)
        try:
            lan_ip = f"{payload[7]}.{payload[6]}.{payload[5]}.{payload[4]}"
            result["lan_ip"] = lan_ip
        except (IndexError, ValueError):
            pass

        # Also try big-endian at offset 8
        try:
            lan_ip2 = f"{payload[8]}.{payload[9]}.{payload[10]}.{payload[11]}"
            result["lan_ip_alt"] = lan_ip2
        except (IndexError, ValueError):
            pass

    return result


# =============================================================================
# DH LAN Discovery (port 8600)
# =============================================================================

def build_dh_discovery() -> bytes:
    """Build DH LAN discovery packet. Magic: 44 48 01 01."""
    return b"\x44\x48\x01\x01"


def parse_dh_response(data: bytes) -> dict | None:
    """Parse DH discovery response from camera on port 8600.

    Camera responds with its info. The response starts with DH magic
    and contains device info in the payload.
    """
    if len(data) < 4:
        return None
    # Check for DH magic
    if data[0:2] != b"\x44\x48":
        return None

    result = {"protocol": "dh"}
    payload = data[4:]

    # Try to find device ID (MTC...) in the response
    try:
        text = payload.decode("ascii", errors="ignore")
        idx = text.find("MTC")
        if idx >= 0:
            device_id = text[idx:].split("\x00")[0].split(" ")[0]
            if len(device_id) >= 10:
                result["device_id"] = device_id
    except Exception:
        pass

    # Try to extract IP address from response
    # Camera might include its own IP in the response
    result["raw"] = payload
    return result


# =============================================================================
# Standard PPPP LAN Discovery (port 32108)
# =============================================================================

def build_lan_search() -> bytes:
    """Build LAN search broadcast packet for port 32108.

    Standard PPPP: f1 30 00 00
    """
    return b"\xf1\x30\x00\x00"


def parse_lan_search_ack(data: bytes) -> dict | None:
    """Parse LAN search response. Returns device info dict or None."""
    if len(data) < 4:
        return None

    # Check for standard PPPP response
    if data[0] == 0xF1:
        magic, pkt_type, payload_len = struct.unpack(">BBH", data[:4])
        if pkt_type == PktType.LAN_SEARCH_ACK:
            payload = data[4:4 + payload_len]
            return _extract_device_id(payload)

    # Check for DH response (camera might respond with DH format)
    if data[0:2] == b"\x44\x48":
        return parse_dh_response(data)

    # Try parsing as generic response with device ID somewhere
    return _extract_device_id(data)


def _extract_device_id(payload: bytes) -> dict | None:
    """Try to extract device ID from payload bytes."""
    try:
        text = payload.decode("ascii", errors="ignore")
        if "MTC" in text:
            idx = text.find("MTC")
            device_id = text[idx:].split("\x00")[0].split(" ")[0]
            if len(device_id) >= 10:
                return {"device_id": device_id, "raw": payload}
    except Exception:
        pass

    # Scan byte by byte
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


# =============================================================================
# Data Layer — DRW packets (used after connection is established)
# =============================================================================

def build_drw(channel: int, data: bytes, index: int = 0) -> bytes:
    """Build DRW (data) packet for sending commands."""
    # DRW header: magic(1) + type(1) + channel(1) + index(2) + size(2) + payload
    header = struct.pack(">BBBHH", 0xF1, PktType.DRW, channel, index, len(data))
    return header + data


def build_drw_ack(channel: int, index: int) -> bytes:
    """Build DRW ACK packet."""
    return struct.pack(">BBBHH", 0xF1, PktType.DRW_ACK, channel, index, 0)


def build_alive() -> bytes:
    """Build keepalive packet."""
    return struct.pack(">BBH", 0xF1, PktType.ALIVE, 0)


def build_close() -> bytes:
    """Build close connection packet."""
    return struct.pack(">BBH", 0xF1, PktType.CLOSE, 0)


def parse_drw_packet(data: bytes) -> tuple[int, int, bytes] | None:
    """Parse incoming DRW data packet.

    Returns (channel, index, payload) or None.
    """
    if len(data) < 7:
        return None
    magic, pkt_type, channel, index, size = struct.unpack(">BBBHH", data[:7])
    if pkt_type != PktType.DRW:
        return None
    payload = data[7:7 + size]
    return (channel, index, payload)


# =============================================================================
# Camera Command Layer (inside DRW payload)
# =============================================================================

def encode_command(msg_type: int, params: bytes = b"") -> bytes:
    """Encode a camera command for sending over PPPP.

    Format: command_id (2 bytes LE) + payload_len (2 bytes LE) + payload
    """
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


def encode_user_setting(
    user1: str, pwd1: str,
    user2: str, pwd2: str,
    user3: str, pwd3: str,
) -> bytes:
    """Encode user/password setting command (MSG_SET_USER = 10).

    Camera supports 3 user slots, each with 32-byte username + 32-byte password.
    Total payload: 192 bytes.
    """
    parts = []
    for u, p in [(user1, pwd1), (user2, pwd2), (user3, pwd3)]:
        parts.append(u.encode("ascii")[:32].ljust(32, b"\x00"))
        parts.append(p.encode("ascii")[:32].ljust(32, b"\x00"))
    return b"".join(parts)


def parse_user_info(payload: bytes) -> list[dict]:
    """Parse user info response (MSG_GET_USER_INFO = 66).

    Returns list of up to 3 user dicts: [{"username": ..., "password": ...}, ...]
    """
    users = []
    offset = 0
    for _ in range(3):
        if offset + 64 > len(payload):
            break
        username = payload[offset:offset + 32].split(b"\x00")[0].decode("ascii", errors="ignore")
        password = payload[offset + 32:offset + 64].split(b"\x00")[0].decode("ascii", errors="ignore")
        if username:
            users.append({"username": username, "password": password})
        offset += 64
    return users
