"""PNZEO camera LAN discovery via PPPP UDP broadcast."""
from __future__ import annotations

import asyncio
import logging
import socket

from .pppp_packets import build_lan_search, parse_lan_search_ack

_LOGGER = logging.getLogger(__name__)
DISCOVERY_PORT = 32108
DISCOVERY_TIMEOUT = 5


async def discover_cameras(timeout: float = DISCOVERY_TIMEOUT) -> list[dict]:
    """Discover PNZEO cameras on LAN via UDP broadcast."""
    found: list[dict] = []
    loop = asyncio.get_event_loop()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setblocking(False)

    try:
        sock.sendto(build_lan_search(), ("255.255.255.255", DISCOVERY_PORT))

        end_time = loop.time() + timeout
        while loop.time() < end_time:
            try:
                data, addr = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 1024),
                    timeout=min(1.0, end_time - loop.time()),
                )
                result = parse_lan_search_ack(data)
                if result:
                    result["ip"] = addr[0]
                    result["port"] = addr[1]
                    if not any(d["device_id"] == result["device_id"] for d in found):
                        found.append(result)
                        _LOGGER.info("Discovered PNZEO camera: %s at %s", result["device_id"], addr[0])
            except asyncio.TimeoutError:
                continue
            except Exception:
                break
    finally:
        sock.close()

    return found


async def check_rtsp(host: str, port: int = 554, timeout: float = 3) -> bool:
    """Check if RTSP port is open."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False
