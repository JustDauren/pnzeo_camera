"""Tests for PNZEOCoordinator connection state integration (CONN-05)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pnzeo_camera.const import ConnectionState


# === CONN-05: Coordinator state gating (stubs -- filled by Plan 03) ===

class TestCoordinatorStateGating:
    """Test coordinator uses ConnectionState to gate reconnection."""

    @pytest.mark.skip(reason="Plan 03: implement state-aware _async_update_data()")
    async def test_coordinator_gates_reconnect_when_connecting(self):
        """CONN-05: Coordinator does not reconnect if state is CONNECTING."""
        pass

    @pytest.mark.skip(reason="Plan 03: implement state-aware _async_update_data()")
    async def test_coordinator_gates_reconnect_when_reconnecting(self):
        """CONN-05: Coordinator does not reconnect if state is RECONNECTING."""
        pass

    @pytest.mark.skip(reason="Plan 03: implement state-aware _async_update_data()")
    async def test_coordinator_triggers_reconnect_when_disconnected(self):
        """CONN-05: Coordinator triggers reconnect if state is DISCONNECTED."""
        pass

    @pytest.mark.skip(reason="Plan 03: implement state-aware _async_update_data()")
    async def test_coordinator_triggers_reconnect_when_failed(self):
        """CONN-05: Coordinator triggers reconnect if state is FAILED."""
        pass

    @pytest.mark.skip(reason="Plan 03: implement connection_state in coordinator data")
    async def test_state_queryable_via_coordinator_data(self):
        """CONN-05: connection_state available in coordinator.data for entities."""
        pass
