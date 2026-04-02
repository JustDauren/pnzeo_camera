"""Tests for PNZEOClient connection reliability (CONN-01, CONN-02, CONN-03, CONN-05)."""
from __future__ import annotations

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pnzeo_camera.const import (
    ConnectionState,
    BACKOFF_BASE,
    MAX_RECONNECT_ATTEMPTS,
)
from custom_components.pnzeo_camera.pppp_client import PNZEOClient


# === CONN-05: ConnectionState enum ===

class TestConnectionStateEnum:
    """Test ConnectionState IntEnum definition."""

    def test_connection_state_enum_values(self):
        """CONN-05: Enum has exactly 6 states with correct integer values."""
        assert ConnectionState.DISCONNECTED == 0
        assert ConnectionState.CONNECTING == 1
        assert ConnectionState.AUTHENTICATING == 2
        assert ConnectionState.CONNECTED == 3
        assert ConnectionState.RECONNECTING == 4
        assert ConnectionState.FAILED == 5
        assert len(ConnectionState) == 6

    def test_connection_state_is_intenum(self):
        """CONN-05: ConnectionState is IntEnum for numeric comparison."""
        assert isinstance(ConnectionState.CONNECTED, int)
        assert ConnectionState.CONNECTED > ConnectionState.DISCONNECTED

    def test_connection_state_names(self):
        """CONN-05: Enum members have readable .name property."""
        assert ConnectionState.DISCONNECTED.name == "DISCONNECTED"
        assert ConnectionState.CONNECTED.name == "CONNECTED"
        assert ConnectionState.RECONNECTING.name == "RECONNECTING"


# === CONN-05: State transitions ===

class TestStateTransitions:
    """Test _set_state() transition logging."""

    def test_state_transition_logging(self, client, caplog):
        """CONN-05: State transitions are logged at INFO level."""
        with caplog.at_level(logging.INFO):
            client._set_state(ConnectionState.CONNECTING)
        assert "DISCONNECTED -> CONNECTING" in caplog.text
        assert client._state == ConnectionState.CONNECTING

    def test_state_no_op_same_state(self, client, caplog):
        """CONN-05: Setting same state does not log."""
        assert client._state == ConnectionState.DISCONNECTED
        with caplog.at_level(logging.INFO):
            client._set_state(ConnectionState.DISCONNECTED)
        assert caplog.text == ""
        assert client._state == ConnectionState.DISCONNECTED

    def test_connection_state_property(self, client):
        """CONN-05: connection_state property returns current ConnectionState."""
        assert client.connection_state == ConnectionState.DISCONNECTED
        client._state = ConnectionState.CONNECTED
        assert client.connection_state == ConnectionState.CONNECTED
        assert client.connected is True


# === CONN-01: Reconnect with backoff ===

class TestReconnectBackoff:
    """Test _reconnect_with_backoff() exponential delays."""

    @pytest.mark.asyncio
    async def test_reconnect_backoff_delays(self, client):
        """CONN-01: Backoff delays increase exponentially with jitter."""
        client._connection_method = "lan"
        sleep_delays = []

        async def mock_sleep(delay):
            sleep_delays.append(delay)

        with patch.object(client, "_do_connect", new_callable=AsyncMock, return_value=False), \
             patch.object(client, "_cleanup_transport", new_callable=AsyncMock), \
             patch("custom_components.pnzeo_camera.pppp_client.asyncio.sleep", side_effect=mock_sleep), \
             patch("custom_components.pnzeo_camera.pppp_client.random.uniform", side_effect=lambda a, b: b):
            await client._reconnect_with_backoff()

        # Verify delays increase: base * 2^attempt, capped at BACKOFF_MAX_LAN
        assert len(sleep_delays) == MAX_RECONNECT_ATTEMPTS
        for i, delay in enumerate(sleep_delays):
            expected = min(BACKOFF_BASE * (2 ** i), 30.0)
            assert delay == pytest.approx(expected), f"Attempt {i}: expected {expected}, got {delay}"

    @pytest.mark.asyncio
    async def test_max_reconnect_attempts(self, client):
        """CONN-01: After MAX_RECONNECT_ATTEMPTS failures, state becomes FAILED."""
        client._connection_method = "lan"

        with patch.object(client, "_do_connect", new_callable=AsyncMock, return_value=False) as mock_connect, \
             patch.object(client, "_cleanup_transport", new_callable=AsyncMock), \
             patch("custom_components.pnzeo_camera.pppp_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._reconnect_with_backoff()
            assert mock_connect.call_count == MAX_RECONNECT_ATTEMPTS

        assert result is False
        assert client._state == ConnectionState.FAILED

    @pytest.mark.asyncio
    async def test_reconnect_success_restores_connected(self, client):
        """CONN-01: Successful reconnect transitions to CONNECTED."""
        client._connection_method = "lan"

        async def do_connect_side_effect():
            if client._do_connect.call_count <= 1:
                return False
            client._state = ConnectionState.CONNECTED
            return True

        with patch.object(client, "_do_connect", new_callable=AsyncMock, side_effect=do_connect_side_effect), \
             patch.object(client, "_cleanup_transport", new_callable=AsyncMock), \
             patch("custom_components.pnzeo_camera.pppp_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._reconnect_with_backoff()

        assert result is True
        assert client._state == ConnectionState.CONNECTED


# === CONN-02: Watchdog ===

class TestWatchdog:
    """Test _connection_watchdog() task supervision."""

    @pytest.mark.asyncio
    async def test_watchdog_detects_dead_keepalive(self, connected_client, caplog):
        """CONN-02: Watchdog detects when keepalive task has stopped."""
        # Create a done task to simulate dead keepalive
        done_task = MagicMock()
        done_task.done.return_value = True
        connected_client._keepalive_task = done_task

        iteration_count = 0

        async def mock_sleep(delay):
            nonlocal iteration_count
            iteration_count += 1
            if iteration_count >= 1:
                connected_client._state = ConnectionState.DISCONNECTED

        with caplog.at_level(logging.WARNING), \
             patch("custom_components.pnzeo_camera.pppp_client.asyncio.sleep", side_effect=mock_sleep), \
             patch("custom_components.pnzeo_camera.pppp_client.asyncio.create_task") as mock_create:
            await connected_client._connection_watchdog()

        assert "Keepalive task died" in caplog.text

    @pytest.mark.asyncio
    async def test_watchdog_triggers_reconnect_after_failures(self, connected_client):
        """CONN-02: 3 consecutive keepalive failures trigger reconnection."""
        done_task = MagicMock()
        done_task.done.return_value = True
        connected_client._keepalive_task = done_task

        iteration_count = 0

        async def mock_sleep(delay):
            nonlocal iteration_count
            iteration_count += 1

        with patch.object(connected_client, "_reconnect_with_backoff", new_callable=AsyncMock) as mock_reconnect, \
             patch("custom_components.pnzeo_camera.pppp_client.asyncio.sleep", side_effect=mock_sleep), \
             patch("custom_components.pnzeo_camera.pppp_client.asyncio.create_task"):
            # Mock reconnect to break the loop
            async def reconnect_break():
                connected_client._state = ConnectionState.DISCONNECTED
                return False
            mock_reconnect.side_effect = reconnect_break

            await connected_client._connection_watchdog()

        mock_reconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_watchdog_logs_with_timestamps(self, connected_client, caplog):
        """CONN-02: Watchdog logs failures at WARNING level with timestamps."""
        done_task = MagicMock()
        done_task.done.return_value = True
        connected_client._keepalive_task = done_task

        iteration_count = 0

        async def mock_sleep(delay):
            nonlocal iteration_count
            iteration_count += 1
            if iteration_count >= 1:
                connected_client._state = ConnectionState.DISCONNECTED

        with caplog.at_level(logging.WARNING), \
             patch("custom_components.pnzeo_camera.pppp_client.asyncio.sleep", side_effect=mock_sleep), \
             patch("custom_components.pnzeo_camera.pppp_client.asyncio.create_task"):
            await connected_client._connection_watchdog()

        # Check WARNING log with HH:MM:SS timestamp pattern
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) >= 1
        # Timestamp format is HH:MM:SS in the message
        import re
        assert any(re.search(r"\d{2}:\d{2}:\d{2}", r.message) for r in warning_records)


# === CONN-02: Keepalive ===

class TestKeepalive:
    """Test _keepalive_loop() failure tracking."""

    @pytest.mark.asyncio
    async def test_keepalive_failure_logged_warning(self, connected_client, caplog):
        """CONN-02: Keepalive send failure logged at WARNING with timestamp."""
        connected_client._transport.sendto.side_effect = OSError("Network unreachable")

        with caplog.at_level(logging.WARNING):
            await connected_client._keepalive_loop()

        assert "Keepalive send failed" in caplog.text
        # Check timestamp pattern HH:MM:SS in log
        import re
        assert re.search(r"\d{2}:\d{2}:\d{2}", caplog.text)

    @pytest.mark.asyncio
    async def test_keepalive_breaks_on_transport_closed(self, connected_client, caplog):
        """CONN-02: Keepalive exits loop when transport is closing."""
        connected_client._transport.is_closing.return_value = True

        with caplog.at_level(logging.WARNING):
            await connected_client._keepalive_loop()

        assert "transport closed" in caplog.text
        # sendto should NOT have been called since transport is closing
        connected_client._transport.sendto.assert_not_called()

    @pytest.mark.asyncio
    async def test_keepalive_tracks_last_sent_timestamp(self, connected_client):
        """CONN-02: _last_keepalive_sent updated on successful send."""
        connected_client._last_keepalive_sent = 0.0
        iteration_count = 0

        async def mock_sleep(delay):
            nonlocal iteration_count
            iteration_count += 1
            if iteration_count >= 1:
                connected_client._state = ConnectionState.DISCONNECTED

        with patch("custom_components.pnzeo_camera.pppp_client.asyncio.sleep", side_effect=mock_sleep):
            await connected_client._keepalive_loop()

        assert connected_client._last_keepalive_sent > 0


# === CONN-03: Socket lifecycle ===

class TestSocketLifecycle:
    """Test try-finally cleanup patterns."""

    @pytest.mark.asyncio
    async def test_socket_cleanup_on_connect_failure(self, client):
        """CONN-03: Transport cleaned up when _do_connect() fails mid-handshake."""
        with patch.object(client, "_cleanup_transport", new_callable=AsyncMock), \
             patch.object(client, "_cloud_discover_port", new_callable=AsyncMock, return_value=None), \
             patch.object(client, "_lan_discover_port", new_callable=AsyncMock, return_value=None):
            result = await client._do_connect()

        assert result is False
        assert client._state == ConnectionState.DISCONNECTED
        # Protocol should be cleaned up via finally block
        assert client._protocol is None

    @pytest.mark.asyncio
    async def test_transport_close_guarded_by_is_closing(self, connected_client):
        """CONN-03: _cleanup_transport() checks is_closing() before calling close()."""
        transport = connected_client._transport
        transport.is_closing.return_value = True

        await connected_client._cleanup_transport()

        # close() should NOT have been called since is_closing() returned True
        transport.close.assert_not_called()
        assert connected_client._transport is None

    @pytest.mark.asyncio
    async def test_send_cgi_returns_none_when_not_connected(self, client):
        """CONN-03: _send_cgi() returns None if state is not CONNECTED."""
        assert client._state == ConnectionState.DISCONNECTED
        result = await client._send_cgi("test.cgi")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_zombie_sockets_after_disconnect(self, connected_client):
        """CONN-03: After disconnect(), transport is None and state is DISCONNECTED."""
        assert connected_client.connected is True

        await connected_client.disconnect()

        assert connected_client._transport is None
        assert connected_client._state == ConnectionState.DISCONNECTED
        assert connected_client._keepalive_task is None
        assert connected_client._watchdog_task is None
