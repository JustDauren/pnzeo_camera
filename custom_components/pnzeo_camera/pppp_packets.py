"""PPPP protocol packet encoding/decoding for PNZEO cameras.

Three protocol layers:
1. F1xx signaling — P2P handshake, relay negotiation, device registration
2. Relay bridging — session management between client and camera via relay
3. Data layer — DRW command/response packets after connection established

Also implements DH (DaHua-derived) LAN discovery on port 8600.
"""
from __future__ import annotations

import json
import logging
import struct
from enum import IntEnum
from urllib.parse import quote

_LOGGER = logging.getLogger(__name__)


class PktType(IntEnum):
    """PPPP packet types (second byte in F1xx header)."""
    # P2P handshake
    HELLO = 0x00
    HELLO_ACK = 0x01
    DEV_LGN = 0x10
    DEV_LGN_ACK = 0x11
    DEV_LGN_CRC = 0x12
    DEV_LGN_CRC_ACK = 0x13
    P2P_REQ = 0x20
    P2P_REQ_ACK = 0x21
    LAN_SEARCH = 0x30
    LAN_NOTIFY = 0x31
    PUNCH_TO = 0x40
    PUNCH_PKT = 0x41
    P2P_RDY = 0x42
    P2P_RDY_ACK = 0x43
    # Relay
    RLY_SERVER_REQ = 0x60
    RLY_SERVER_ACK = 0x61
    LIST_REQ1 = 0x67
    LIST_REQ = 0x68
    LIST_REQ_ACK = 0x69
    RLY_HELLO = 0x70
    RLY_HELLO_ACK = 0x71
    RLY_PORT = 0x72
    RLY_PORT_ACK = 0x73
    RLY_BYTE_COUNT = 0x78
    RLY_REQ = 0x80
    RLY_REQ_ACK = 0x81
    RLY_TO = 0x82
    RLY_PKT = 0x83
    RLY_RDY = 0x84
    RLY_TO_ACK = 0x85
    # Data
    DRW = 0xD0
    DRW_ACK = 0xD1
    # Keepalive/close
    ALIVE = 0xE0
    ALIVE_ACK = 0xE1
    CLOSE = 0xF0


# =============================================================================
# PPRT UID Encoding
# =============================================================================

def encode_uid(device_id: str) -> bytes:
    """Encode device ID into PPRT UID block (20 bytes).

    Format: "PPRT" + 4x00 + prefix(2) + transformed_suffix(10)
    """
    parts = device_id.split("-")
    header = b"PPRT\x00\x00\x00\x00"

    if len(parts) >= 3:
        prefix = struct.pack(">H", 0x0009)
        uid_content = _transform_uid_suffix(device_id)
        uid_payload = prefix + uid_content.ljust(10, b"\x00")[:10]
    else:
        raw = device_id.encode("ascii")[:12]
        uid_payload = raw.ljust(12, b"\x00")

    return header + uid_payload


def decode_uid(data: bytes) -> str | None:
    """Extract device ID string from a PPRT UID block (20 bytes).

    Returns device ID or None if not a valid PPRT block.
    """
    if len(data) < 20 or data[:4] != b"PPRT":
        return None
    # The UID is in bytes 8-19 — try to decode as ASCII
    uid_raw = data[8:20].rstrip(b"\x00")
    try:
        # Skip prefix bytes (2 bytes), decode rest
        if len(uid_raw) > 2:
            suffix = uid_raw[2:].decode("ascii", errors="ignore")
            if suffix:
                return suffix
    except Exception:
        pass
    return uid_raw.hex()


def _transform_uid_suffix(device_id: str) -> bytes:
    """Transform device ID into UID content bytes."""
    parts = device_id.split("-")
    suffix = parts[-1] if parts else device_id
    result = bytearray()
    serial = parts[1] if len(parts) > 1 else "000000"
    result.append((sum(ord(c) for c in serial) & 0xFF) | 0x40)
    result.append((sum(ord(c) for c in suffix) & 0xFF) | 0x40)
    result.extend(suffix.encode("ascii"))
    return bytes(result)


# =============================================================================
# F1xx Packet Builder — Generic
# =============================================================================

def _build_f1xx(pkt_type: int, payload: bytes = b"") -> bytes:
    """Build any F1xx packet: F1 + type(1) + length(2) + payload."""
    return struct.pack(">BBH", 0xF1, pkt_type, len(payload)) + payload


# =============================================================================
# P2P Handshake Packets (Client ↔ P2P Server)
# =============================================================================

def build_hello() -> bytes:
    """F100 Hello. Client → P2P Server."""
    return _build_f1xx(PktType.HELLO)


def build_hello_ack(session_id: bytes = b"\x00" * 16) -> bytes:
    """F101 Hello ACK. Server → Client. 16-byte session payload."""
    return _build_f1xx(PktType.HELLO_ACK, session_id[:16].ljust(16, b"\x00"))


def build_dev_lgn_ack(result: int = 0) -> bytes:
    """F111 Device Login ACK. Server → Camera. Result 0 = success."""
    return _build_f1xx(PktType.DEV_LGN_ACK, struct.pack("<I", result))


def build_dev_lgn_crc_ack(result: int = 0) -> bytes:
    """F113 Device Login CRC ACK. Server → Camera. Result 0 = success."""
    return _build_f1xx(PktType.DEV_LGN_CRC_ACK, struct.pack("<I", result))


def build_p2p_connect(device_id: str) -> bytes:
    """F120 P2P Connect. Client → P2P Server. Contains PPRT UID."""
    uid_block = encode_uid(device_id)
    # Pad to standard 36 bytes payload
    payload = uid_block.ljust(36, b"\x00")
    return _build_f1xx(PktType.P2P_REQ, payload)


def build_punch_to(ip: str, port: int) -> bytes:
    """F140 Punch To. Server → Client. Camera's IP:port."""
    ip_parts = [int(x) for x in ip.split(".")]
    payload = bytes(ip_parts) + struct.pack(">H", port)
    return _build_f1xx(PktType.PUNCH_TO, payload.ljust(16, b"\x00"))


def build_p2p_rdy() -> bytes:
    """F142 P2P Ready. Bidirectional after punch."""
    return _build_f1xx(PktType.P2P_RDY)


# =============================================================================
# Relay Packets (Client ↔ P2P Server → Relay Node)
# =============================================================================

def build_relay_request(device_id: str) -> bytes:
    """F167 Relay/List Request. Client → P2P Server. Request relay node list."""
    uid_block = encode_uid(device_id)
    return _build_f1xx(PktType.LIST_REQ1, uid_block)


def build_relay_list_ack(relay_servers: list[tuple[str, int]]) -> bytes:
    """F169 Relay List ACK. Server → Client. List of relay node addresses.

    Each entry: IP(4 bytes BE) + port(2 bytes BE) + padding(2 bytes).
    """
    payload = bytearray()
    for ip, port in relay_servers:
        ip_parts = [int(x) for x in ip.split(".")]
        payload.extend(bytes(ip_parts))
        payload.extend(struct.pack(">H", port))
        payload.extend(b"\x00\x00")  # padding
    return _build_f1xx(PktType.LIST_REQ_ACK, bytes(payload))


def build_relay_hello() -> bytes:
    """F170 Relay Hello. Client → Relay Node."""
    return _build_f1xx(PktType.RLY_HELLO)


def build_relay_hello_ack() -> bytes:
    """F171 Relay Hello ACK. Relay → Client/Camera."""
    return _build_f1xx(PktType.RLY_HELLO_ACK)


def build_relay_port_req() -> bytes:
    """F172 Relay Port Request. Client → Relay Node."""
    return _build_f1xx(PktType.RLY_PORT)


def build_relay_port_ack(ip: str, port: int, session_token: bytes = b"") -> bytes:
    """F173 Relay Port ACK. Relay → Client. Assigned endpoint + session token."""
    ip_parts = [int(x) for x in ip.split(".")]
    payload = bytes(ip_parts) + struct.pack(">H", port)
    if session_token:
        payload += session_token[:8]
    return _build_f1xx(PktType.RLY_PORT_ACK, payload)


def build_relay_to(relay_ip: str, relay_port: int, session_magic: bytes = b"") -> bytes:
    """F182 Relay To. Server → Camera. Tells camera to connect to relay node."""
    ip_parts = [int(x) for x in relay_ip.split(".")]
    payload = bytes(ip_parts) + struct.pack(">H", relay_port)
    if session_magic:
        payload += session_magic[:8]
    return _build_f1xx(PktType.RLY_TO, payload.ljust(16, b"\x00"))


def build_relay_punch(device_id: str, session_token: bytes = b"") -> bytes:
    """F183 Relay Punch. Client → Relay Node. UID + session token, sent 10-15x."""
    uid_block = encode_uid(device_id)
    payload = uid_block
    if session_token:
        payload += session_token[:8]
    else:
        payload += b"\x00" * 8
    return _build_f1xx(PktType.RLY_PKT, payload)


def build_relay_rdy() -> bytes:
    """F184 Relay Ready. Relay → Client. Session established."""
    return _build_f1xx(PktType.RLY_RDY)


# =============================================================================
# Relay Parsers
# =============================================================================

def parse_relay_info(data: bytes) -> list[tuple[str, int]]:
    """Parse F169 Relay Info response. Returns list of (ip, port) tuples.

    Tries multiple payload formats (8-byte and 6-byte entries) with various
    header sizes to handle different firmware variants.
    """
    if len(data) < 8:
        return []

    payload = data[4:]  # skip F1 69 LL LL header
    relays = []

    # Try 8-byte entries (IP:4 + port:2 + padding:2) with different header offsets
    for skip in (0, 4, 8, 2):
        if skip >= len(payload):
            continue
        chunk = payload[skip:]
        temp = []
        offset = 0
        while offset + 6 <= len(chunk):
            ip_bytes = chunk[offset:offset + 4]
            port = struct.unpack(">H", chunk[offset + 4:offset + 6])[0]
            ip = f"{ip_bytes[0]}.{ip_bytes[1]}.{ip_bytes[2]}.{ip_bytes[3]}"
            if _is_valid_relay_addr(ip, port):
                temp.append((ip, port))
            offset += 8  # 8-byte entries
        if temp:
            relays = temp
            break

    # Fallback: try 6-byte entries (IP:4 + port:2, no padding)
    if not relays:
        for skip in (0, 4, 2):
            if skip >= len(payload):
                continue
            chunk = payload[skip:]
            temp = []
            offset = 0
            while offset + 6 <= len(chunk):
                ip_bytes = chunk[offset:offset + 4]
                port = struct.unpack(">H", chunk[offset + 4:offset + 6])[0]
                ip = f"{ip_bytes[0]}.{ip_bytes[1]}.{ip_bytes[2]}.{ip_bytes[3]}"
                if _is_valid_relay_addr(ip, port):
                    temp.append((ip, port))
                offset += 6
            if temp:
                relays = temp
                break

    _LOGGER.debug("Parsed relay info: %d servers from %d bytes", len(relays), len(data))
    return relays


def parse_relay_port_ack(data: bytes) -> dict | None:
    """Parse F173 Relay Port ACK. Returns {ip, port, session_token}."""
    if len(data) < 10:  # 4 header + 4 IP + 2 port minimum
        return None
    payload = data[4:]
    result = {}
    if len(payload) >= 6:
        ip_bytes = payload[0:4]
        result["ip"] = f"{ip_bytes[0]}.{ip_bytes[1]}.{ip_bytes[2]}.{ip_bytes[3]}"
        result["port"] = struct.unpack(">H", payload[4:6])[0]
        result["session_token"] = payload[6:] if len(payload) > 6 else b""
    return result


def parse_relay_to(data: bytes) -> dict | None:
    """Parse F182 Relay To. Returns {ip, port, session_magic}."""
    if len(data) < 10:
        return None
    payload = data[4:]
    if len(payload) >= 6:
        ip_bytes = payload[0:4]
        return {
            "ip": f"{ip_bytes[0]}.{ip_bytes[1]}.{ip_bytes[2]}.{ip_bytes[3]}",
            "port": struct.unpack(">H", payload[4:6])[0],
            "session_magic": payload[6:] if len(payload) > 6 else b"",
        }
    return None


def _is_valid_relay_addr(ip: str, port: int) -> bool:
    """Check if address is a plausible relay server."""
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        octets = [int(p) for p in parts]
        return (
            all(0 <= o <= 255 for o in octets)
            and octets[0] > 0
            and octets[0] != 127
            and octets != [0, 0, 0, 0]
            and 1024 < port < 65535
        )
    except ValueError:
        return False


# =============================================================================
# F1xx Message Parser (unified)
# =============================================================================

def parse_f1xx_header(data: bytes) -> tuple[int, int, bytes] | None:
    """Parse F1xx header. Returns (pkt_type, payload_len, payload) or None."""
    if len(data) < 4 or data[0] != 0xF1:
        return None
    pkt_type = data[1]
    payload_len = struct.unpack(">H", data[2:4])[0]
    payload = data[4:4 + payload_len]
    return (pkt_type, payload_len, payload)


def parse_f1xx_message(data: bytes) -> dict | None:
    """Parse any F1xx signaling message. Returns typed dict or None."""
    parsed = parse_f1xx_header(data)
    if not parsed:
        return None

    pkt_type, _, payload = parsed
    msg_type = 0xF100 | pkt_type

    base = {"type": "unknown", "msg_type": msg_type, "raw": data, "payload": payload}

    if pkt_type == PktType.HELLO_ACK:
        base["type"] = "hello_ack"
    elif pkt_type == PktType.DEV_LGN:
        base["type"] = "dev_lgn"
        base["uid"] = _extract_uid_from_payload(payload)
    elif pkt_type == PktType.DEV_LGN_CRC:
        base["type"] = "dev_lgn_crc"
        base["uid"] = _extract_uid_from_payload(payload)
    elif pkt_type == PktType.P2P_REQ_ACK:
        base["type"] = "p2p_ready"
    elif pkt_type == PktType.PUNCH_PKT:
        base["type"] = "punch_pkt"
        base["uid"] = _extract_uid_from_payload(payload)
    elif pkt_type == PktType.PUNCH_TO:
        base["type"] = "punch_to"
        if len(payload) >= 6:
            ip_bytes = payload[0:4]
            base["ip"] = f"{ip_bytes[0]}.{ip_bytes[1]}.{ip_bytes[2]}.{ip_bytes[3]}"
            base["port"] = struct.unpack(">H", payload[4:6])[0]
    elif pkt_type == PktType.LIST_REQ_ACK:
        base["type"] = "relay_info"
        base["relays"] = parse_relay_info(data)
    elif pkt_type == PktType.RLY_HELLO_ACK:
        base["type"] = "relay_hello_ack"
    elif pkt_type == PktType.RLY_PORT_ACK:
        base["type"] = "relay_port_ack"
        parsed_port = parse_relay_port_ack(data)
        if parsed_port:
            base.update(parsed_port)
    elif pkt_type == PktType.RLY_TO:
        base["type"] = "relay_to"
        parsed_rly = parse_relay_to(data)
        if parsed_rly:
            base.update(parsed_rly)
    elif pkt_type == PktType.RLY_RDY:
        base["type"] = "relay_rdy"
    elif pkt_type == PktType.RLY_REQ_ACK:
        base["type"] = "relay_req_ack"
    elif pkt_type == PktType.RLY_PKT:
        base["type"] = "relay_pkt"
    else:
        base["type"] = f"f1_{pkt_type:02x}"

    return base


def _extract_uid_from_payload(payload: bytes) -> str | None:
    """Try to extract device UID from payload containing PPRT block."""
    # Look for PPRT marker
    idx = payload.find(b"PPRT")
    if idx >= 0 and idx + 20 <= len(payload):
        return decode_uid(payload[idx:idx + 20])
    # Try to find MTC prefix
    try:
        text = payload.decode("ascii", errors="ignore")
        mtc_idx = text.find("MTC")
        if mtc_idx >= 0:
            device_id = text[mtc_idx:].split("\x00")[0].split(" ")[0]
            if len(device_id) >= 10:
                return device_id
    except Exception:
        pass
    return None


# =============================================================================
# DH LAN Discovery (port 8600)
# =============================================================================

def build_dh_discovery() -> bytes:
    """Build DH LAN discovery packet. Magic: 44 48 01 01."""
    return b"\x44\x48\x01\x01"


def parse_dh_response(data: bytes) -> dict | None:
    """Parse DH discovery response from camera on port 8600."""
    if len(data) < 4 or data[0:2] != b"\x44\x48":
        return None
    result = {"protocol": "dh"}
    payload = data[4:]
    try:
        text = payload.decode("ascii", errors="ignore")
        idx = text.find("MTC")
        if idx >= 0:
            device_id = text[idx:].split("\x00")[0].split(" ")[0]
            if len(device_id) >= 10:
                result["device_id"] = device_id
    except Exception:
        pass
    result["raw"] = payload
    return result


# =============================================================================
# Standard PPPP LAN Discovery (port 32108)
# =============================================================================

def build_lan_search() -> bytes:
    """Build LAN search broadcast. F1 30 00 00 on port 32108."""
    return _build_f1xx(PktType.LAN_SEARCH)


def parse_lan_search_ack(data: bytes) -> dict | None:
    """Parse LAN search response. Returns device info dict or None."""
    if len(data) < 4:
        return None
    if data[0] == 0xF1:
        parsed = parse_f1xx_header(data)
        if parsed:
            _, _, payload = parsed
            return _extract_device_id(payload)
    if data[0:2] == b"\x44\x48":
        return parse_dh_response(data)
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
    header = struct.pack(">BBBHH", 0xF1, PktType.DRW, channel, index, len(data))
    return header + data


def build_drw_ack(channel: int, index: int) -> bytes:
    """Build DRW ACK packet."""
    return struct.pack(">BBBHH", 0xF1, PktType.DRW_ACK, channel, index, 0)


def build_alive() -> bytes:
    """Build keepalive packet. F1 E0 00 00."""
    return _build_f1xx(PktType.ALIVE)


def build_alive_ack() -> bytes:
    """Build keepalive ACK. F1 E1 00 00."""
    return _build_f1xx(PktType.ALIVE_ACK)


def build_close() -> bytes:
    """Build close connection packet. F1 F0 00 00."""
    return _build_f1xx(PktType.CLOSE)


def parse_drw_packet(data: bytes) -> tuple[int, int, bytes] | None:
    """Parse incoming DRW data packet. Returns (channel, index, payload) or None."""
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
    """Encode a camera command: cmd_id(2 LE) + payload_len(2 LE) + payload."""
    return struct.pack("<HH", msg_type, len(params)) + params


def decode_response(data: bytes) -> tuple[int, bytes]:
    """Decode a camera response. Returns (msg_type, payload)."""
    if len(data) < 4:
        return (-1, b"")
    msg_type, payload_len = struct.unpack("<HH", data[:4])
    return (msg_type, data[4:4 + payload_len])


def encode_login(username: str, password: str) -> bytes:
    """Encode login: username(32B) + password(32B), null-padded."""
    user_bytes = username.encode("ascii")[:32].ljust(32, b"\x00")
    pwd_bytes = password.encode("ascii")[:32].ljust(32, b"\x00")
    return user_bytes + pwd_bytes


def encode_camera_control(cmd_type: int, value: int) -> bytes:
    """Encode camera control command (brightness, contrast, etc.)."""
    return struct.pack("<BBH", cmd_type, value, 0)


def encode_ptz(direction: int, step_mode: int = 1) -> bytes:
    """Encode PTZ control command."""
    return struct.pack("<BB", direction, step_mode)


def encode_user_setting(
    user1: str, pwd1: str,
    user2: str, pwd2: str,
    user3: str, pwd3: str,
) -> bytes:
    """Encode user/password setting (3 slots × 64 bytes = 192 bytes)."""
    parts = []
    for u, p in [(user1, pwd1), (user2, pwd2), (user3, pwd3)]:
        parts.append(u.encode("ascii")[:32].ljust(32, b"\x00"))
        parts.append(p.encode("ascii")[:32].ljust(32, b"\x00"))
    return b"".join(parts)


def parse_user_info(payload: bytes) -> list[dict]:
    """Parse user info response (MSG_GET_USER_INFO). Up to 3 user slots."""
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


# =============================================================================
# CGI Command Layer (libRtMain.so cameras use HTTP-like CGI inside DRW)
# =============================================================================

def build_drw_cgi(seq: int, cgi_text: str) -> bytes:
    """Build DRW packet with CGI command for libRtMain.so cameras.

    These cameras use HTTP-like CGI commands inside DRW packets:
      GET /check_user.cgi?loginuse=X&loginpas=Y&user=X&pwd=Y&
      GET /camera_control.cgi?param=14&value=1&loginuse=X&loginpas=Y&...
      GET /get_camera_params.cgi?loginuse=X&loginpas=Y&...

    DRW format: F1 D0 SIZE(2 BE) + inner_header(12) + cgi_ascii
    Inner header: D1 00 00 SEQ 01 0A 00 00 CGI_LEN(4 LE)
    """
    cgi = cgi_text.encode("ascii")
    inner = struct.pack("<BBBBBBBB", 0xD1, 0x00, 0x00, seq & 0xFF, 0x01, 0x0A, 0x00, 0x00)
    inner += struct.pack("<I", len(cgi))
    payload = inner + cgi
    return struct.pack(">BBH", 0xF1, PktType.DRW, len(payload)) + payload


def build_cgi_url(endpoint: str, username: str, password: str, **params) -> str:
    """Build a CGI URL string for camera commands.

    All commands require loginuse/loginpas authentication.
    All values are URL-encoded to prevent CGI injection.
    """
    parts = [f"GET /{quote(endpoint, safe='')}?"]
    for key, val in params.items():
        parts.append(f"{quote(str(key), safe='')}={quote(str(val), safe='')}&")
    parts.append(f"loginuse={quote(username, safe='')}&loginpas={quote(password, safe='')}&")
    parts.append(f"user={quote(username, safe='')}&pwd={quote(password, safe='')}&")
    return "".join(parts)


def parse_drw_cgi_response(data: bytes) -> dict | None:
    """Parse DRW response containing CGI result.

    Camera responds with: F1 D0 SIZE(2BE) + inner_header(12) + result_text
    Result text format: "result=0\\nresult=0;\\njsonvalue={...}"
    """
    if len(data) < 16 or data[0] != 0xF1 or data[1] != PktType.DRW:
        return None

    # Skip outer header (4 bytes) + inner header (12 bytes)
    text_start = 16
    try:
        text = data[text_start:].decode("ascii", errors="ignore").strip()
    except Exception:
        return None

    result = {"raw": text, "success": False}

    # Parse "result=X"
    for line in text.split("\n"):
        line = line.strip().rstrip(";")
        if line.startswith("result="):
            try:
                result["result"] = int(line.split("=")[1])
                result["success"] = result["result"] == 0
            except ValueError:
                pass
        elif line.startswith("jsonvalue="):
            try:
                result["json"] = json.loads(line[len("jsonvalue="):])
            except Exception:
                pass
        elif "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip().rstrip(";")

    return result


# CGI endpoint constants
CGI_CHECK_USER = "check_user.cgi"
CGI_GET_PARAMS = "get_camera_params.cgi"
CGI_GET_STATUS = "get_status.cgi"
CGI_CAMERA_CONTROL = "camera_control.cgi"
CGI_SET_DATETIME = "set_mobiletime.cgi"
CGI_GET_RECORD = "get_record_param.cgi"
CGI_SET_RECORD = "set_record_param.cgi"
CGI_GET_ALARM = "get_alarm.cgi"
CGI_SET_ALARM = "set_alarm.cgi"
CGI_GET_WIFI = "get_wifi_params.cgi"
CGI_SET_WIFI = "set_wifi.cgi"
CGI_GET_NETWORK = "get_network_params.cgi"
CGI_SET_NETWORK = "set_network.cgi"
CGI_GET_USER = "get_user_params.cgi"
CGI_SET_USER = "set_user.cgi"
CGI_REBOOT = "reboot.cgi"
CGI_FACTORY_RESET = "factory_reset.cgi"
CGI_FORMAT_SD = "format_sd.cgi"
CGI_SNAPSHOT = "snapshot.cgi"

# Camera control param IDs (for camera_control.cgi?param=X&value=Y)
CGI_PARAM_RESOLUTION = 0
CGI_PARAM_BRIGHTNESS = 1
CGI_PARAM_CONTRAST = 2
CGI_PARAM_POWER_FREQ = 3
CGI_PARAM_MIRROR = 5
CGI_PARAM_IR_CUT = 14      # IR LED / night vision
CGI_PARAM_STATUS_LED = 15  # Indicator LED
