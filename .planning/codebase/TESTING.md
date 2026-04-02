# Testing Patterns

**Analysis Date:** 2026-04-02

## Test Framework

**Runner:**
- No test runner currently configured
- No `pytest.ini`, `tox.ini`, or `unittest` configuration present

**Assertion Library:**
- Not applicable (no tests exist)

**Run Commands:**
- No automated testing infrastructure present
- Manual testing via Home Assistant dev environment required

## Test Coverage Status

**Current State:**
- **0% automated test coverage** — No unit tests, integration tests, or fixtures present
- No test files detected (`test_*.py`, `*_test.py`, or `conftest.py` absent)
- All testing is manual/exploratory

## Test File Organization

**Recommended Location:**
- `tests/` directory at package root (not created yet)
- Unit tests: `tests/test_pppp_client.py`, `tests/test_pppp_packets.py`, etc.
- Fixtures: `tests/fixtures/` for mock data and packet samples
- Configuration: `tests/conftest.py` for pytest setup

**Current Structure (No Tests):**
```
pnzeo_camera/
├── __init__.py
├── pppp_client.py
├── pppp_packets.py
├── pppp_discovery.py
├── coordinator.py
├── ...
└── [NO TESTS DIRECTORY]
```

## Areas Requiring Testing

**Priority 1 - Critical Protocol Logic:**

**`pppp_packets.py` — Binary encoding/decoding:**
- UID encoding/decoding: `encode_uid()`, `decode_uid()` with various device ID formats
- Packet builders: `build_hello()`, `build_punch_to()`, `build_lan_search()`
- Response parsers: `parse_drw_cgi_response()`, `parse_lan_search_ack()`
- Test vectors needed for each packet type with known inputs/outputs

**`pppp_client.py` — State machine and connection:**
- Connection flow: `connect()` → successful P2P handshake
- Fallback logic: Cloud discovery fails → LAN discovery fallback
- CGI commands: `_send_cgi()` retry logic (25 retries with 0.3s interval)
- Keepalive: `_keepalive_loop()` sends packets every 3 seconds
- Cleanup: `disconnect()` cancels tasks and closes sockets properly
- Error recovery: Invalid auth → graceful failure, not exception

**`pppp_discovery.py` — LAN discovery:**
- Broadcast socket handling: `discover_cameras()` sends DH and PPPP probes
- Response parsing: Deduplication by IP (same camera on 2 ports)
- Specific host probe: `discover_camera_at()` timeout handling
- RTSP check: `check_rtsp()` port connectivity

**Priority 2 - Integration Layer:**

**`coordinator.py` — Data polling:**
- State recovery: Reconnect if PPPP drops mid-cycle
- Graceful degradation: Don't raise UpdateFailed if PPPP unavailable
- RTSP video continues even if PPPP control fails

**`config_flow.py` — User input validation:**
- Auto-discovery step: Multiple cameras found → pick step
- Manual entry: RTSP reachability check before password prompt
- Password verification: PPPP login attempt with timeout

**`device.py`, entity implementations:**
- RTSP URL construction: `rtsp://username:password@host:port/11`
- Unique ID generation: Device ID or host with sanitization
- Entity state updates: State calls trigger UI updates

**Priority 3 - Edge Cases:**
- Unreachable cloud servers (both fail) → LAN discovery only
- Socket send during shutdown (exception safety)
- Large CGI responses (fragmented across multiple DRW packets)
- Invalid JSON in CGI responses (graceful parsing)

## Mocking Strategy

**Framework:** Mock using `unittest.mock` (built-in to Python)

**What to Mock:**
- UDP sockets: Return synthetic packets with known data
- PPPP protocol responses: Simulate camera behavior for each command
- Home Assistant services: Mock `hass.services.async_register()`, `hass.config_entries`
- External servers: Cloud P2P servers (use local test alternatives)
- FFmpeg subprocess: Snapshot image generation

**What NOT to Mock:**
- asyncio Event/Task primitives (use real async)
- Connection state machine logic (test actual flow)
- Packet encoding/decoding (these are the functions being tested)
- Protocol timing (use short intervals for testing, not 3-second keepalive)

## Recommended Test Structure

**Example: Protocol Packet Tests**

```python
# tests/test_pppp_packets.py
import unittest
from pnzeo_camera.pppp_packets import encode_uid, decode_uid, build_hello

class TestUIDEncoding(unittest.TestCase):
    def test_encode_uid_with_valid_device_id(self):
        """Test encoding device ID in PPPP UID format."""
        device_id = "PNZEO-ABC123-XYZ789"
        uid = encode_uid(device_id)
        assert len(uid) == 20
        assert uid.startswith(b"PPRT")
        
    def test_decode_uid_roundtrip(self):
        """Verify encode->decode produces original ID."""
        device_id = "PNZEO-ABC123-XYZ789"
        uid = encode_uid(device_id)
        decoded = decode_uid(uid)
        # Note: Roundtrip may not be perfect due to transformation
        assert decoded is not None

class TestPacketBuilders(unittest.TestCase):
    def test_build_hello_packet(self):
        """Test F100 hello packet construction."""
        pkt = build_hello()
        assert pkt[0] == 0xF1
        assert pkt[1] == 0x00
        # Length bytes in big-endian
        assert struct.unpack(">H", pkt[2:4])[0] == 0
```

**Example: Client Connection Tests**

```python
# tests/test_pppp_client.py
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pnzeo_camera.pppp_client import PNZEOClient

class TestPNZEOClient(unittest.TestCase):
    def setUp(self):
        self.client = PNZEOClient(
            host="192.168.1.100",
            username="admin",
            password="8888",
            device_id="PNZEO-ABC123-XYZ789"
        )

    @patch('pnzeo_camera.pppp_client.asyncio.DatagramProtocol')
    async def test_connect_lan_fallback(self, mock_protocol):
        """Test cloud discovery failure → LAN fallback."""
        # Mock cloud discover to return None
        self.client._cloud_discover_port = AsyncMock(return_value=None)
        # Mock LAN discover to return valid port
        self.client._lan_discover_port = AsyncMock(return_value=32108)
        
        # Should succeed via LAN
        result = await self.client.connect()
        assert result is False  # Will fail without actual socket, but flow tested
```

## Async Testing Pattern

**Using asyncio.run() or pytest-asyncio:**

```python
# tests/test_async_operations.py
import asyncio
import pytest

@pytest.mark.asyncio
async def test_send_cgi_with_retry():
    """Test CGI command retry logic."""
    client = PNZEOClient(host="192.168.1.100", ...)
    # Mock _transport to return no data on first attempt, data on second
    client._transport = MagicMock()
    
    # First call: timeout (no response)
    # Second call: success
    # Should retry and succeed
```

## Discovery Testing

**Mock Socket Responses:**

```python
# tests/test_discovery.py
from unittest.mock import MagicMock, AsyncMock

async def test_discover_cameras_dh_response():
    """Test discovery of camera via DH protocol."""
    # Create mock socket
    mock_sock = MagicMock()
    
    # Simulate DH response with device info
    dh_response = b"\x44\x48" + b"..." # DH protocol header + data
    mock_sock.recvfrom = AsyncMock(return_value=(dh_response, ("192.168.1.100", 8600)))
    
    # Mock broadcast send
    mock_sock.sendto = MagicMock()
    
    # Test discovery finds camera
    found = await discover_cameras()
    assert len(found) == 1
    assert found[0]["ip"] == "192.168.1.100"
```

## Coverage Gaps & Risks

**Untested Areas:**

| Area | Function | Risk | Solution |
|------|----------|------|----------|
| Packet binary format | `encode_uid()`, `build_*()` functions | Protocol failure if encoding wrong | Unit test with known vectors |
| Connection retry | `connect()` with 2 attempts | Silently fails without error | Test both success and failure paths |
| DRW retry logic | `_send_cgi()` 25 retries | Could hang or drop packets | Mock socket with timeout scenarios |
| Keepalive | `_keepalive_loop()` | Connection drops if loop breaks | Test task cancellation and timing |
| State corruption | `_camera_params.update()` | Partial updates on network error | Test merge semantics |
| CGI parsing | `parse_drw_cgi_response()` | Crashes on invalid JSON | Test malformed responses |
| Entity state | Platform entities (`camera.py`, `switch.py`) | UI doesn't update properly | Test `async_write_ha_state()` calls |

## Configuration for Testing

**Not Yet Configured:**

To enable testing, add to project root:

**`pyproject.toml`:**
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
python_files = ["test_*.py", "*_test.py"]
```

**`tests/conftest.py`:**
```python
import pytest
from unittest.mock import MagicMock

@pytest.fixture
def mock_hass():
    """Fixture providing mock Home Assistant instance."""
    hass = MagicMock()
    hass.data = {}
    return hass

@pytest.fixture
def mock_coordinator(mock_hass):
    """Fixture providing mock coordinator."""
    from pnzeo_camera.coordinator import PNZEOCoordinator
    # Return configured mock
```

## Manual Testing Checklist

**Until automated tests are written, manual verification required:**

**Connection Flow:**
- [ ] Cloud discovery succeeds (valid device ID, port 32100 reachable)
- [ ] Cloud discovery fails → LAN fallback succeeds
- [ ] LAN discovery finds camera on broadcast
- [ ] P2P handshake completes (F141 response received)
- [ ] CGI login via DRW succeeds
- [ ] Keepalive maintains connection for 10+ minutes

**Camera Control:**
- [ ] Get camera status (brightness, resolution, IR state)
- [ ] Set brightness via number entity
- [ ] Set resolution via select entity
- [ ] Enable/disable IR LED via switch
- [ ] Reboot via button
- [ ] Take snapshot via button (RTSP fallback if PPPP fails)

**Discovery:**
- [ ] Auto-discovery finds camera on fresh network
- [ ] Manual IP entry validates RTSP before password prompt
- [ ] Password verification times out gracefully (no hang)
- [ ] Multiple cameras found → pick step shows all

**Error Handling:**
- [ ] Network disconnect → reconnect on next polling cycle
- [ ] Invalid password → UpdateFailed in coordinator, UI still loads
- [ ] PPPP unavailable → RTSP video still plays (video stream component)

---

*Testing analysis: 2026-04-02*

**Note:** This component is in active development. Test coverage should be prioritized as features stabilize. Priority: Protocol encoding (P1), Connection state machine (P1), Integration layer (P2).
