"""PNZEO camera LAN discovery via PPPP UDP broadcast.

Supports two discovery methods:
1. DH protocol on port 8600 (magic 44 48 01 01) — primary for PNZEO W8
2. Standard PPPP on port 32108 (magic f1 30 00 00) — fallback
"""
from __future__ import annotations

import asyncio
import logging
import socket

from .const import PPPP_PORT_DH_LAN, PPPP_PORT_STANDARD
from .pppp_packets import (
    build_dh_discovery,
    build_lan_search,
    parse_dh_response,
    parse_lan_search_ack,
)

_LOGGER = logging.getLogger(__name__)
DISCOVERY_TIMEOUT = 5


async def discover_cameras(timeout: float = DISCOVERY_TIMEOUT) -> list[dict]:
    """Discover PNZEO cameras on LAN via UDP broadcast.

    Sends both DH (port 8600) and standard PPPP (port 32108) discovery
    packets in parallel, deduplicates results.
    """
    found: list[dict] = []
    loop = asyncio.get_event_loop()

    # Create socket for broadcast
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setblocking(False)

    try:
        # Send DH discovery on port 8600 (primary)
        try:
            sock.sendto(build_dh_discovery(), ("255.255.255.255", PPPP_PORT_DH_LAN))
            _LOGGER.debug("Sent DH discovery to port %d", PPPP_PORT_DH_LAN)
        except Exception as ex:
            _LOGGER.debug("DH discovery send failed: %s", ex)

        # Send standard PPPP on port 32108 (fallback)
        try:
            sock.sendto(build_lan_search(), ("255.255.255.255", PPPP_PORT_STANDARD))
            _LOGGER.debug("Sent PPPP discovery to port %d", PPPP_PORT_STANDARD)
        except Exception as ex:
            _LOGGER.debug("PPPP discovery send failed: %s", ex)

        end_time = loop.time() + timeout
        while loop.time() < end_time:
            try:
                data, addr = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 1024),
                    timeout=min(1.0, end_time - loop.time()),
                )
                result = _parse_any_response(data)
                if result:
                    result["ip"] = addr[0]
                    result["port"] = addr[1]
                    # Deduplicate by IP (same camera may respond on both ports)
                    if not any(d["ip"] == result["ip"] for d in found):
                        found.append(result)
                        _LOGGER.info(
                            "Discovered PNZEO camera: %s at %s:%d (protocol: %s)",
                            result.get("device_id", "unknown"),
                            addr[0],
                            addr[1],
                            result.get("protocol", "pppp"),
                        )
            except asyncio.TimeoutError:
                continue
            except Exception:
                break
    finally:
        sock.close()

    return found


async def discover_camera_at(host: str, timeout: float = 3.0) -> dict | None:
    """Try to discover a specific camera by IP using DH and PPPP probes.

    Sends targeted (non-broadcast) packets to the given host.
    Returns discovery info dict or None.
    """
    loop = asyncio.get_event_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setblocking(False)

    try:
        # Send DH probe to port 8600
        try:
            sock.sendto(build_dh_discovery(), (host, PPPP_PORT_DH_LAN))
        except Exception:
            pass
        # Send PPPP probe to port 32108
        try:
            sock.sendto(build_lan_search(), (host, PPPP_PORT_STANDARD))
        except Exception:
            pass

        end_time = loop.time() + timeout
        while loop.time() < end_time:
            try:
                data, addr = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 1024),
                    timeout=min(1.0, end_time - loop.time()),
                )
                if addr[0] == host:
                    result = _parse_any_response(data)
                    if result:
                        result["ip"] = addr[0]
                        result["port"] = addr[1]
                        return result
            except asyncio.TimeoutError:
                continue
            except Exception:
                break
    finally:
        sock.close()

    return None


def _parse_any_response(data: bytes) -> dict | None:
    """Try to parse a response as either DH or standard PPPP."""
    if len(data) < 4:
        return None

    # Check DH response first (starts with 44 48)
    if data[0:2] == b"\x44\x48":
        result = parse_dh_response(data)
        if result:
            result["protocol"] = "dh"
            return result

    # Try standard PPPP response
    result = parse_lan_search_ack(data)
    if result:
        result["protocol"] = "pppp"
        return result

    return None


async def check_rtsp(host: str, port: int = 554, timeout: float = 3) -> bool:
    """Check if RTSP port is open."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False
