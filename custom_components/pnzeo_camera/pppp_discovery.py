"""PNZEO camera LAN discovery via RTSP port scan."""
from __future__ import annotations

import asyncio
import logging
import socket

_LOGGER = logging.getLogger(__name__)
RTSP_PORT = 554
DISCOVERY_TIMEOUT = 8


async def discover_cameras(timeout: float = DISCOVERY_TIMEOUT) -> list[dict]:
    """Discover cameras on LAN by scanning for open RTSP port 554.

    Scans the local /24 subnet for hosts with port 554 open,
    then verifies RTSP response contains valid stream.
    """
    found: list[dict] = []

    # Get local IP to determine subnet
    local_ip = _get_local_ip()
    if not local_ip:
        _LOGGER.warning("Cannot determine local IP for discovery")
        return found

    subnet = ".".join(local_ip.split(".")[:3])
    _LOGGER.info("Scanning %s.0/24 for RTSP cameras...", subnet)

    # Scan all IPs in parallel
    tasks = []
    for i in range(1, 255):
        ip = f"{subnet}.{i}"
        if ip == local_ip:
            continue
        tasks.append(_probe_rtsp(ip, RTSP_PORT, timeout=3))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for ip_result in results:
        if isinstance(ip_result, dict):
            found.append(ip_result)
            _LOGGER.info("Discovered camera: %s", ip_result["ip"])

    return found


async def _probe_rtsp(host: str, port: int = 554, timeout: float = 3) -> dict | None:
    """Check if host has RTSP open and responds."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        # Send RTSP OPTIONS to verify it's a real RTSP server
        writer.write(b"OPTIONS rtsp://%b:554/ RTSP/1.0\r\nCSeq: 1\r\n\r\n" % host.encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(512), timeout=2)
        writer.close()
        await writer.wait_closed()

        if b"RTSP" in data:
            return {"ip": host, "port": port, "device_id": f"PNZEO_{host.split('.')[-1]}"}
    except Exception:
        pass
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


def _get_local_ip() -> str | None:
    """Get local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None
