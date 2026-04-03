"""Shared fixtures for PNZEO Camera tests.

Sets up import paths and mocks Home Assistant dependencies so tests
can run without the full HA environment installed.

Note: tests/ intentionally has NO __init__.py to avoid triggering
pnzeo_camera/__init__.py (which imports homeassistant). pytest
discovers tests via testpaths in pyproject.toml instead.
"""
from __future__ import annotations

import pathlib
import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# 1. Set up import paths for custom_components.pnzeo_camera
# ---------------------------------------------------------------------------
_tests_dir = pathlib.Path(__file__).resolve().parent
_repo_root = _tests_dir.parent            # pnzeo_camera/
_custom_components_dir = _repo_root.parent  # custom_components/
_ha_root = _custom_components_dir.parent    # Documents/HA/

# Ensure custom_components is a package
(_custom_components_dir / "__init__.py").touch(exist_ok=True)

# Add HA root to sys.path for custom_components import
_ha_root_str = str(_ha_root)
if _ha_root_str not in sys.path:
    sys.path.insert(0, _ha_root_str)

# Remove repo root from sys.path to avoid select.py shadowing stdlib
_repo_root_str = str(_repo_root)
while _repo_root_str in sys.path:
    sys.path.remove(_repo_root_str)

# ---------------------------------------------------------------------------
# 2. Mock Home Assistant dependencies BEFORE any component import
# ---------------------------------------------------------------------------
for mod_name in [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.update_coordinator",
]:
    sys.modules.setdefault(mod_name, MagicMock())

# ---------------------------------------------------------------------------
# 3. Component imports (safe now)
# ---------------------------------------------------------------------------
from custom_components.pnzeo_camera.const import ConnectionState  # noqa: E402
from custom_components.pnzeo_camera.pppp_client import PNZEOClient  # noqa: E402

# ---------------------------------------------------------------------------
# 4. Fixtures
# ---------------------------------------------------------------------------
import pytest  # noqa: E402


@pytest.fixture
def mock_transport():
    """Mock asyncio DatagramTransport."""
    transport = MagicMock()
    transport.is_closing.return_value = False
    transport.sendto = MagicMock()
    transport.close = MagicMock()
    return transport


@pytest.fixture
def client():
    """Create a PNZEOClient instance for testing."""
    return PNZEOClient(
        host="192.168.1.100",
        username="admin",
        password="testpass",
        device_id="TESTDEVICE123",
    )


@pytest.fixture
def connected_client(client, mock_transport):
    """Create a PNZEOClient that appears connected."""
    client._transport = mock_transport
    client._state = ConnectionState.CONNECTED
    client._cam_port = 10000
    client._last_keepalive_sent = 0.0
    return client
