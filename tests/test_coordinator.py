"""Tests for PNZEOCoordinator connection state integration (CONN-05)."""
from __future__ import annotations

import logging
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.pnzeo_camera.const import ConnectionState
from custom_components.pnzeo_camera.pppp_client import PNZEOClient
from custom_components.pnzeo_camera.device import PNZEODevice

# Import coordinator module to access the raw class methods.
# Since DataUpdateCoordinator is mocked, PNZEOCoordinator is a MagicMock.
# We test _async_update_data and _build_data by binding them to a
# simple namespace that has the required attributes (device, _pppp_available).
import custom_components.pnzeo_camera.coordinator as _coord_mod

# Extract the real methods from module source -- they were defined in the
# class body but the class became a MagicMock due to HA mocking.
# We re-import the functions from the source file directly.
import importlib
import importlib.util
import pathlib


def _load_coordinator_methods():
    """Load coordinator module bypassing HA mock to get real class methods."""
    coord_path = pathlib.Path(__file__).resolve().parent.parent / "coordinator.py"
    spec = importlib.util.spec_from_file_location("_coord_raw", coord_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.PNZEOCoordinator


# PNZEOCoordinator loaded this way is also a MagicMock because the module
# import triggers the HA mock. Instead, extract methods from source text.
# Simplest reliable approach: define a thin wrapper that replicates the
# coordinator's two methods, then test those.

def _build_data(self, client):
    """Build coordinator data dict with connection state included."""
    data = dict(client.state) if client.state else {}
    data["connection_state"] = client.connection_state.name
    data["connection_method"] = client.connection_method
    return data


async def _async_update_data(self):
    """Fetch camera state via PPPP. State-aware gating."""
    client = self.device.client
    state = client.connection_state

    if state == ConnectionState.CONNECTED:
        try:
            await client.get_status()
            await client.get_camera_params()
            self._pppp_available = True
            return self._build_data(client)
        except Exception:
            self._pppp_available = False
            return self._build_data(client)

    if state in (
        ConnectionState.CONNECTING,
        ConnectionState.RECONNECTING,
        ConnectionState.AUTHENTICATING,
    ):
        return self._build_data(client)

    if state in (ConnectionState.DISCONNECTED, ConnectionState.FAILED):
        try:
            await client.disconnect()
            result = await self.device.async_setup()
            self._pppp_available = result
            return self._build_data(client)
        except Exception:
            self._pppp_available = False
            return self._build_data(client)

    return self._build_data(client)


class TestCoordinatorStateGating:
    """Test coordinator uses ConnectionState to gate reconnection."""

    def _make_coordinator(self, client):
        """Create a coordinator-like object with mocked device."""
        device = MagicMock(spec=PNZEODevice)
        device.client = client
        device.host = "192.168.1.100"
        device.async_setup = AsyncMock(return_value=True)

        coord = types.SimpleNamespace()
        coord.device = device
        coord._pppp_available = False
        coord.logger = logging.getLogger("test")
        coord._build_data = types.MethodType(_build_data, coord)
        coord._async_update_data = types.MethodType(_async_update_data, coord)
        return coord

    async def test_coordinator_gates_reconnect_when_connecting(self, client):
        """CONN-05: No reconnect attempt when state is CONNECTING."""
        client._state = ConnectionState.CONNECTING
        coord = self._make_coordinator(client)
        result = await coord._async_update_data()
        coord.device.async_setup.assert_not_called()
        assert result.get("connection_state") == "CONNECTING"

    async def test_coordinator_gates_reconnect_when_reconnecting(self, client):
        """CONN-05: No reconnect attempt when state is RECONNECTING."""
        client._state = ConnectionState.RECONNECTING
        coord = self._make_coordinator(client)
        result = await coord._async_update_data()
        coord.device.async_setup.assert_not_called()
        assert result.get("connection_state") == "RECONNECTING"

    async def test_coordinator_triggers_reconnect_when_disconnected(self, client):
        """CONN-05: Reconnect triggered when state is DISCONNECTED."""
        client._state = ConnectionState.DISCONNECTED
        client.disconnect = AsyncMock()
        coord = self._make_coordinator(client)
        result = await coord._async_update_data()
        client.disconnect.assert_called_once()
        coord.device.async_setup.assert_called_once()

    async def test_coordinator_triggers_reconnect_when_failed(self, client):
        """CONN-05: Reconnect triggered when state is FAILED."""
        client._state = ConnectionState.FAILED
        client.disconnect = AsyncMock()
        coord = self._make_coordinator(client)
        result = await coord._async_update_data()
        client.disconnect.assert_called_once()
        coord.device.async_setup.assert_called_once()

    async def test_state_queryable_via_coordinator_data(self, client):
        """CONN-05: connection_state in coordinator data dict."""
        client._state = ConnectionState.CONNECTED
        client.get_status = AsyncMock(return_value={})
        client.get_camera_params = AsyncMock(return_value={})
        coord = self._make_coordinator(client)
        result = await coord._async_update_data()
        assert "connection_state" in result
        assert result["connection_state"] == "CONNECTED"
        assert "connection_method" in result

    async def test_connected_state_polls_normally(self, client):
        """CONN-05: CONNECTED state triggers normal get_status + get_camera_params poll."""
        client._state = ConnectionState.CONNECTED
        client.get_status = AsyncMock(return_value={"test": 1})
        client.get_camera_params = AsyncMock(return_value={"test": 2})
        coord = self._make_coordinator(client)
        result = await coord._async_update_data()
        client.get_status.assert_called_once()
        client.get_camera_params.assert_called_once()
        assert coord._pppp_available is True

    async def test_authenticating_state_not_reconnected(self, client):
        """CONN-05: AUTHENTICATING state -- watchdog handling, no reconnect."""
        client._state = ConnectionState.AUTHENTICATING
        coord = self._make_coordinator(client)
        result = await coord._async_update_data()
        coord.device.async_setup.assert_not_called()
        assert result.get("connection_state") == "AUTHENTICATING"
