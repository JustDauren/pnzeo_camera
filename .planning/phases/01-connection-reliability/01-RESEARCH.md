# Phase 1: Connection Reliability - Research

**Researched:** 2026-04-02
**Domain:** asyncio UDP protocol lifecycle, Home Assistant DataUpdateCoordinator, connection state machine
**Confidence:** HIGH

## Summary

This phase addresses the four most critical infrastructure requirements: auto-reconnect with exponential backoff (CONN-01), keepalive watchdog with logging (CONN-02), socket lifecycle with context managers (CONN-03), and an explicit ConnectionState enum (CONN-05). All changes are contained within `pppp_client.py` and `coordinator.py`, with a minor addition to `const.py` for the new enum.

The current codebase has a working connection flow but multiple fragility points: the keepalive loop silently swallows all exceptions (line 398), there is no state machine (just boolean flags `_connected`/`_authenticated`), socket cleanup is scattered without context managers, and reconnection only happens passively when the coordinator polls and notices the connection is down (60s gap). The fix is a proper `ConnectionState` enum driving all state transitions, a watchdog task that monitors keepalive health independently, exponential backoff with jitter for reconnect attempts, and try-finally patterns around all socket operations.

**Primary recommendation:** Implement a `ConnectionState` enum with 6 states (DISCONNECTED, CONNECTING, AUTHENTICATING, CONNECTED, RECONNECTING, FAILED), replace all boolean flags, add a `_connection_watchdog()` coroutine that supervises the keepalive task and triggers reconnection, and wrap all socket operations in try-finally blocks. No external dependencies required -- pure asyncio stdlib.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
None -- all implementation choices are at Claude's discretion (infrastructure phase).

### Claude's Discretion
All implementation choices are at Claude's discretion. Use ROADMAP phase goal, success criteria, and codebase conventions to guide decisions.

Key constraints from codebase analysis:
- Current code uses raw UDP sockets without context managers (CONCERNS.md)
- Keepalive loop swallows all exceptions silently (pppp_client.py line 398)
- No explicit state machine -- boolean flags `_connected`, `_authenticated` (pppp_client.py lines 60-66)
- Cloud relay IPs hardcoded (pppp_client.py lines 43-46)
- Exponential backoff must not block the HA event loop

### Deferred Ideas (OUT OF SCOPE)
None -- infrastructure phase.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CONN-01 | Camera auto-reconnects on disconnect with exponential backoff | ConnectionState enum drives reconnection; `_connection_watchdog()` task detects disconnect and calls `_reconnect_with_backoff()` using full jitter algorithm (base 2s, max 30s LAN / 60s cloud) |
| CONN-02 | Keepalive task never dies silently -- watchdog and logging | `_connection_watchdog()` supervises `_keepalive_task`, logs all failures at WARNING level with timestamps, restarts keepalive or triggers full reconnection |
| CONN-03 | Socket lifecycle managed with context managers / try-finally | All socket operations wrapped in try-finally blocks; `_cleanup()` restructured as guaranteed cleanup path; transport close guarded by `is_closing()` check |
| CONN-05 | Protocol state machine uses explicit ConnectionState enum | `ConnectionState(IntEnum)` with states: DISCONNECTED=0, CONNECTING=1, AUTHENTICATING=2, CONNECTED=3, RECONNECTING=4, FAILED=5; replaces `_connected` and `_authenticated` booleans |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncio (stdlib) | Python 3.12+ | Event loop, DatagramProtocol, tasks, events | Already used; zero external deps per project constraint |
| enum (stdlib) | Python 3.12+ | IntEnum for ConnectionState | Already used in pppp_packets.py (PktType); consistent pattern |
| logging (stdlib) | Python 3.12+ | Structured logging with timestamps | Already used; HA standard |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| homeassistant.helpers.update_coordinator | HA 2024.1+ | DataUpdateCoordinator base class | Already used in coordinator.py; drives reconnect awareness |
| random (stdlib) | Python 3.12+ | Jitter for exponential backoff | `random.uniform()` for full jitter calculation |
| time (stdlib) | Python 3.12+ | `time.monotonic()` for keepalive timestamps | Monotonic clock avoids NTP drift issues |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Manual backoff math | `backoff` PyPI package | Adds external dependency; project constraint is zero external deps |
| Manual state machine | `transitions` or `python-statemachine` PyPI | Adds external dependency; ConnectionState has only 6 states, overkill |
| `asyncio.Event` for DRW response | `asyncio.Queue` | Queue is heavier; Event is sufficient for single-response protocol |

**Installation:**
```bash
# No installation needed -- all stdlib
```

## Architecture Patterns

### Current vs. Target State Flow

```
CURRENT:
  _connected=False, _authenticated=False
    -> connect() -> _connected=True
    -> _cgi_login() -> _authenticated=True
    -> [keepalive dies silently] -> connection stalls for up to 60s
    -> [coordinator polls] -> notices client.connected==False -> reconnect

TARGET:
  DISCONNECTED
    -> connect() -> CONNECTING
    -> P2P handshake OK -> AUTHENTICATING
    -> CGI login OK -> CONNECTED (start keepalive + watchdog)
    -> [keepalive miss] -> RECONNECTING (watchdog triggers reconnect with backoff)
    -> reconnect OK -> CONNECTED
    -> reconnect fails N times -> FAILED (log error, wait for coordinator cycle)
    -> coordinator cycle -> DISCONNECTED -> retry
```

### Pattern 1: ConnectionState Enum

**What:** Replace boolean flags with an explicit enum that governs all state transitions.
**When to use:** Always -- this is the single source of truth for connection state.
**Example:**

```python
from enum import IntEnum

class ConnectionState(IntEnum):
    """PPPP connection states."""
    DISCONNECTED = 0   # Not connected, can attempt connect
    CONNECTING = 1     # P2P handshake in progress
    AUTHENTICATING = 2 # Handshake done, CGI login in progress
    CONNECTED = 3      # Fully operational (keepalive + watchdog running)
    RECONNECTING = 4   # Connection lost, attempting recovery with backoff
    FAILED = 5         # Max retries exhausted, waiting for next coordinator cycle
```

The `connected` property becomes: `return self._state == ConnectionState.CONNECTED`

State transitions are logged at INFO level: `"State: CONNECTING -> CONNECTED"`.

### Pattern 2: Watchdog Coroutine

**What:** A background task that monitors keepalive health and triggers reconnection when needed.
**When to use:** Always active while in CONNECTED state.
**Example:**

```python
async def _connection_watchdog(self) -> None:
    """Monitor connection health. Restart keepalive or trigger reconnect."""
    consecutive_failures = 0
    while self._state in (ConnectionState.CONNECTED, ConnectionState.RECONNECTING):
        try:
            if not self._keepalive_task or self._keepalive_task.done():
                _LOGGER.warning(
                    "Keepalive task died at %s. Restarting.",
                    time.strftime("%H:%M:%S"),
                )
                if self._state == ConnectionState.CONNECTED:
                    self._keepalive_task = asyncio.create_task(
                        self._keepalive_loop()
                    )
                    consecutive_failures += 1
                if consecutive_failures >= 3:
                    _LOGGER.warning("3 keepalive failures. Triggering reconnect.")
                    await self._reconnect_with_backoff()
                    consecutive_failures = 0
            else:
                consecutive_failures = 0

            await asyncio.sleep(KEEPALIVE_INTERVAL * 2)  # Check every 6s

        except asyncio.CancelledError:
            break
        except Exception as ex:
            _LOGGER.warning("Watchdog error: %s", ex)
            await asyncio.sleep(KEEPALIVE_INTERVAL)
```

### Pattern 3: Exponential Backoff with Full Jitter

**What:** Reconnection attempts use increasing delays with randomization to avoid thundering herd.
**When to use:** Every reconnection attempt after the first failure.
**Example:**

```python
import random

BACKOFF_BASE = 2.0       # seconds
BACKOFF_MAX_LAN = 30.0   # max delay for LAN reconnect
BACKOFF_MAX_CLOUD = 60.0 # max delay for cloud reconnect
MAX_RECONNECT_ATTEMPTS = 5

async def _reconnect_with_backoff(self) -> bool:
    """Reconnect with exponential backoff + full jitter."""
    self._set_state(ConnectionState.RECONNECTING)
    max_delay = (BACKOFF_MAX_CLOUD
                 if self._connection_method == "cloud"
                 else BACKOFF_MAX_LAN)

    for attempt in range(MAX_RECONNECT_ATTEMPTS):
        delay = min(BACKOFF_BASE * (2 ** attempt), max_delay)
        jitter = random.uniform(0, delay)
        _LOGGER.info(
            "Reconnect attempt %d/%d in %.1fs",
            attempt + 1, MAX_RECONNECT_ATTEMPTS, jitter,
        )
        await asyncio.sleep(jitter)
        await self._cleanup()
        if await self._do_connect():
            return True

    self._set_state(ConnectionState.FAILED)
    _LOGGER.error(
        "Failed to reconnect after %d attempts. "
        "Will retry on next coordinator cycle.",
        MAX_RECONNECT_ATTEMPTS,
    )
    return False
```

### Pattern 4: Socket Lifecycle with try-finally

**What:** All socket/transport operations wrapped in try-finally to guarantee cleanup.
**When to use:** Every place a socket is created or transport is used.
**Example:**

```python
async def _do_connect(self) -> bool:
    """Single connection attempt with guaranteed cleanup on failure."""
    self._set_state(ConnectionState.CONNECTING)
    transport = None
    try:
        drw_port = await self._discover_port()
        if not drw_port:
            return False

        self._cam_port = drw_port
        loop = asyncio.get_running_loop()
        self._protocol = _PNZEOProtocol(self)
        transport, _ = await asyncio.wait_for(
            loop.create_datagram_endpoint(
                lambda: self._protocol,
                local_addr=("0.0.0.0", 0),
            ),
            timeout=5,
        )
        self._transport = transport

        # ... punch + login ...

        self._set_state(ConnectionState.CONNECTED)
        return True
    except Exception as ex:
        _LOGGER.debug("Connection failed: %s", ex)
        return False
    finally:
        if not self._state == ConnectionState.CONNECTED:
            # Cleanup only on failure -- successful connect keeps transport
            if transport and not transport.is_closing():
                transport.close()
            self._transport = None
            self._protocol = None
            if self._state == ConnectionState.CONNECTING:
                self._set_state(ConnectionState.DISCONNECTED)
```

### Pattern 5: Keepalive with Failure Tracking

**What:** Keepalive loop tracks consecutive send failures and timestamps for diagnostics.
**When to use:** Replaces the current silent keepalive loop.
**Example:**

```python
async def _keepalive_loop(self) -> None:
    """Send keepalive packets. Track failures for watchdog."""
    self._last_keepalive_sent = time.monotonic()
    while self._state == ConnectionState.CONNECTED:
        try:
            if self._transport and not self._transport.is_closing():
                self._transport.sendto(
                    build_alive(), (self.host, self._cam_port)
                )
                self._last_keepalive_sent = time.monotonic()
            else:
                _LOGGER.warning(
                    "Keepalive: transport closed at %s",
                    time.strftime("%H:%M:%S"),
                )
                break
            await asyncio.sleep(KEEPALIVE_INTERVAL)
        except asyncio.CancelledError:
            _LOGGER.debug("Keepalive cancelled")
            raise  # Re-raise to let task complete properly
        except OSError as ex:
            _LOGGER.warning(
                "Keepalive send failed at %s: %s",
                time.strftime("%H:%M:%S"), ex,
            )
            break
        except Exception as ex:
            _LOGGER.warning(
                "Keepalive unexpected error at %s: %s",
                time.strftime("%H:%M:%S"), ex,
            )
            break
```

### Anti-Patterns to Avoid
- **Swallowing CancelledError:** The current code catches `Exception` broadly in keepalive (line 398). `CancelledError` must be re-raised or handled explicitly -- never silently caught (in Python 3.9+ `CancelledError` derives from `BaseException`, not `Exception`, but catching `Exception` still catches other real errors silently).
- **Checking `_connected` boolean from protocol callback:** The `connection_lost()` callback in `_PNZEOProtocol` sets `client._connected = False` directly. With the state enum, it must call `client._set_state(ConnectionState.DISCONNECTED)` to trigger proper transition logging.
- **Blocking sockets in async context:** The current `_cloud_discover_port()` and `_lan_discover_port()` use blocking `socket.socket()`. This is acceptable during initial setup (CONTEXT.md confirms) but must NOT be copied for any new code. CONN-03 wraps existing ones in try-finally but does not refactor to async (that is a separate concern).
- **Reconnecting inside `_async_update_data()` without backoff:** The current coordinator calls `disconnect()` then `async_setup()` on every poll if not connected. This must be gated by the ConnectionState to avoid reconnect storms.

### Recommended Changes by File

```
pppp_client.py:
  - Add ConnectionState enum (or import from const.py)
  - Replace _connected/_authenticated with _state: ConnectionState
  - Add _set_state() method with transition logging
  - Add _connection_watchdog() coroutine
  - Add _reconnect_with_backoff() method
  - Refactor _keepalive_loop() with failure tracking + timestamps
  - Refactor _do_connect() with try-finally cleanup
  - Refactor _cleanup() to check transport.is_closing()
  - Add _last_keepalive_sent timestamp for diagnostics
  - Add watchdog_task lifecycle management in connect/disconnect

coordinator.py:
  - Use client state enum instead of client.connected boolean
  - Gate reconnection: only call connect if state is DISCONNECTED or FAILED
  - Expose connection_state as data for entities to query
  - Log state transitions at coordinator level

const.py:
  - Add ConnectionState IntEnum (preferred location for project conventions)
  - Remove PPPP_STATUS_* constants (replaced by ConnectionState)
  - Add backoff constants: BACKOFF_BASE, BACKOFF_MAX_LAN, BACKOFF_MAX_CLOUD, MAX_RECONNECT_ATTEMPTS
```

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Exponential backoff | Custom retry decorator | Simple inline math: `min(base * 2**attempt, max)` + `random.uniform(0, delay)` | Only 5 lines of code; adding a library is overkill for one callsite |
| Task supervision | Custom event loop monitoring | asyncio `task.done()` + `task.exception()` checks in watchdog loop | Standard asyncio pattern; no framework needed |
| State machine | Full FSM library (transitions, python-statemachine) | IntEnum + `_set_state()` method with transition validation | 6 states with linear transitions; FSM library adds 50KB+ for no benefit |
| Timestamp formatting | Custom datetime helpers | `time.monotonic()` for intervals, `time.strftime()` for log messages | stdlib, zero overhead |
| UDP socket cleanup | Custom context manager class | try-finally around `create_datagram_endpoint()` result | Asyncio transports have `close()` + `is_closing()` -- context managers add indirection |

**Key insight:** This phase is pure asyncio stdlib work. Every problem has a <20-line solution using built-in asyncio primitives. Adding any external dependency would violate the project constraint (`"requirements": []` in manifest.json).

## Common Pitfalls

### Pitfall 1: Reconnect Storm on Coordinator Poll
**What goes wrong:** Coordinator polls every 60s. If connection is down, every poll triggers a full reconnect attempt. With multiple entities listening, this can cause 5+ reconnect attempts per minute.
**Why it happens:** Current code in `coordinator._async_update_data()` calls `disconnect()` then `async_setup()` unconditionally when `client.connected` is False.
**How to avoid:** Gate reconnection by checking `client.state_enum` -- only attempt reconnect if state is `DISCONNECTED` or `FAILED`, not if already `CONNECTING` or `RECONNECTING`. Let the watchdog own reconnection; coordinator just observes.
**Warning signs:** Multiple "Connected to camera" log lines in rapid succession.

### Pitfall 2: Keepalive Task as Zombie
**What goes wrong:** Keepalive task exception is swallowed. Task appears alive (`not task.done()`) but is stuck in a bad state where `sendto()` silently fails.
**Why it happens:** Current line 398: `except Exception: pass`. OSError from a closed socket is caught and ignored.
**How to avoid:** Break out of keepalive loop on any non-CancelledError exception. Log at WARNING level. Let watchdog detect the stopped task and trigger recovery.
**Warning signs:** No keepalive log entries for >10 seconds despite connection being "active".

### Pitfall 3: Stale Transport Reference After Cleanup
**What goes wrong:** `_cleanup()` sets `_transport = None`, but a concurrent `_send_cgi()` call still holds a reference to the old transport and calls `sendto()` on a closed socket.
**Why it happens:** No synchronization between cleanup and send operations.
**How to avoid:** Check `self._transport and not self._transport.is_closing()` before every `sendto()`. Use the ConnectionState enum as a guard: `_send_cgi()` returns None immediately if state is not CONNECTED.
**Warning signs:** `OSError: [Errno 9] Bad file descriptor` in logs.

### Pitfall 4: CancelledError Propagation Break
**What goes wrong:** When HA unloads the integration, it cancels all tasks. If keepalive or watchdog catch `CancelledError` and don't re-raise, the unload hangs until timeout.
**Why it happens:** Broad `except Exception` catches, or `except asyncio.CancelledError: pass` without `raise`.
**How to avoid:** Always re-raise `CancelledError`. In Python 3.9+, `CancelledError` is a `BaseException`, so `except Exception` does NOT catch it -- but verify this is true in the project's minimum Python version (3.9+). The existing `except asyncio.CancelledError: break` pattern in `_keepalive_loop()` is acceptable because the loop exits cleanly.
**Warning signs:** HA logs "Setup of PNZEO Camera is taking over 10 seconds".

### Pitfall 5: connection_lost() vs. Protocol State
**What goes wrong:** `_PNZEOProtocol.connection_lost()` fires when asyncio closes the transport. This sets `_connected = False` but the watchdog/backoff may already be mid-reconnection, causing a state conflict.
**Why it happens:** `connection_lost()` is called by the event loop, not by our code. It can fire at any time.
**How to avoid:** In `connection_lost()`, only transition to DISCONNECTED if current state is CONNECTED. If state is already RECONNECTING or CONNECTING, ignore the callback (it is from the old transport being cleaned up).
**Warning signs:** State flip-flops: RECONNECTING -> DISCONNECTED -> RECONNECTING in rapid succession.

### Pitfall 6: Blocking Socket in Discovery Blocking Event Loop
**What goes wrong:** `_cloud_discover_port()` uses blocking `socket.socket()` with 3s timeout. This blocks the HA event loop.
**Why it happens:** Original implementation predates async refactoring. It works for initial setup but is problematic during reconnection.
**How to avoid:** For Phase 1, wrap existing blocking sockets in `hass.async_add_executor_job()` if called during reconnection. Full async refactor is a separate concern. Alternatively, accept the 3s block during reconnection as it only happens on failure paths. Document this debt.
**Warning signs:** HA logs "Detected blocking call to ... in the event loop".

## Code Examples

Verified patterns from official sources:

### State Transition Logging
```python
# Source: project convention (const.py IntEnum pattern)
def _set_state(self, new_state: ConnectionState) -> None:
    """Transition connection state with logging."""
    old_state = self._state
    if old_state == new_state:
        return
    self._state = new_state
    _LOGGER.info(
        "Connection state: %s -> %s (%s)",
        old_state.name, new_state.name, self.host,
    )
```

### Coordinator State-Aware Update
```python
# Source: HA DataUpdateCoordinator pattern (developers.home-assistant.io)
async def _async_update_data(self) -> dict[str, Any]:
    client = self.device.client
    state = client.connection_state

    if state == ConnectionState.CONNECTED:
        # Normal path: poll camera state
        try:
            await client.get_status()
            await client.get_camera_params()
            self._pppp_available = True
            return client.state
        except Exception as ex:
            _LOGGER.debug("PPPP update failed: %s", ex)
            self._pppp_available = False
            return client.state

    if state in (ConnectionState.CONNECTING, ConnectionState.RECONNECTING,
                 ConnectionState.AUTHENTICATING):
        # Reconnection in progress -- don't interfere, return last state
        return client.state

    if state in (ConnectionState.DISCONNECTED, ConnectionState.FAILED):
        # Trigger reconnection
        try:
            await client.disconnect()
            result = await client.connect()
            self._pppp_available = result
            if not result:
                _LOGGER.debug(
                    "PPPP not available for %s. Video still works via RTSP.",
                    self.device.host,
                )
            return client.state
        except Exception as ex:
            _LOGGER.debug("PPPP setup failed: %s", ex)
            self._pppp_available = False
            return {}

    return client.state
```

### Transport Guard in _send_cgi
```python
# Source: Python asyncio docs (docs.python.org/3/library/asyncio-protocol.html)
async def _send_cgi(self, cgi_url: str) -> dict | None:
    if self._state != ConnectionState.CONNECTED:
        return None
    if not self._transport or self._transport.is_closing():
        return None
    # ... existing send logic ...
```

### Cleanup with is_closing() Guard
```python
# Source: Python asyncio BaseTransport docs
async def _cleanup(self) -> None:
    """Clean up transport and reset state."""
    if self._transport:
        try:
            if not self._transport.is_closing():
                self._transport.close()
        except Exception:
            pass
        self._transport = None
    self._protocol = None
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Boolean `_connected`/`_authenticated` flags | IntEnum state machine with transition logging | This phase | Eliminates invalid state combinations; queryable state |
| Silent keepalive `except: pass` | Watchdog coroutine supervising keepalive | This phase | No more zombie connections; automatic recovery |
| Coordinator-driven reconnection (60s gap) | Watchdog-driven reconnection (6s detection) | This phase | Recovery from 60s to <30s (LAN) |
| Raw socket without cleanup | try-finally around all socket ops | This phase | No socket leaks on exception paths |
| No backoff on reconnect | Exponential backoff with full jitter | This phase | Prevents reconnect storms; respects camera resources |

**Deprecated/outdated:**
- `PPPP_STATUS_*` constants in `const.py` (lines 49-61): These integer constants predate the work but are never used in code. They will be replaced by the `ConnectionState` enum. However, they may have been intended for future use. Safe to remove and replace with the new enum.

## Open Questions

1. **Blocking discovery during reconnection**
   - What we know: `_cloud_discover_port()` and `_lan_discover_port()` use blocking sockets. This is documented as acceptable during initial setup.
   - What's unclear: During watchdog-triggered reconnection (which happens in the event loop), the 3s blocking call may cause HA warnings. Need to decide whether to wrap in `async_add_executor_job()` or accept the debt.
   - Recommendation: Accept the 3s block for Phase 1. The reconnection path is infrequent (only on connection loss). Log a TODO for async refactor in Phase 6 or later.

2. **Camera-side keepalive timeout**
   - What we know: We send keepalive (F1E0) every 3 seconds. Camera expects them.
   - What's unclear: Exact timeout before camera drops the session. Observed behavior suggests ~10-15 seconds of missed keepalives causes camera to stop responding.
   - Recommendation: Watchdog checks every 6 seconds (2x keepalive interval). If keepalive task is dead for >6 seconds, trigger reconnection. This gives a ~9-12 second detection window.

3. **PPPP_STATUS constants reuse**
   - What we know: `const.py` has `PPPP_STATUS_*` constants (UNKNOWN, CONNECTING, ONLINE, etc.) that are never referenced in code.
   - What's unclear: Whether these were planned for integration with the Android app's status codes.
   - Recommendation: Replace with `ConnectionState` enum. Keep the PPPP_STATUS values as comments in the enum definition for reference mapping.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | none -- see Wave 0 |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CONN-01 | Auto-reconnect with exponential backoff | unit | `pytest tests/test_pppp_client.py::test_reconnect_backoff -x` | Wave 0 |
| CONN-01 | Backoff delays increase exponentially with jitter | unit | `pytest tests/test_pppp_client.py::test_backoff_delays -x` | Wave 0 |
| CONN-01 | Max reconnect attempts triggers FAILED state | unit | `pytest tests/test_pppp_client.py::test_max_reconnect_attempts -x` | Wave 0 |
| CONN-02 | Watchdog detects dead keepalive task | unit | `pytest tests/test_pppp_client.py::test_watchdog_detects_dead_keepalive -x` | Wave 0 |
| CONN-02 | Watchdog logs failures with timestamps | unit | `pytest tests/test_pppp_client.py::test_watchdog_logs_timestamps -x` | Wave 0 |
| CONN-02 | Keepalive failure logged at WARNING level | unit | `pytest tests/test_pppp_client.py::test_keepalive_failure_logged -x` | Wave 0 |
| CONN-03 | Socket cleanup on connect failure | unit | `pytest tests/test_pppp_client.py::test_socket_cleanup_on_failure -x` | Wave 0 |
| CONN-03 | Transport close guarded by is_closing() | unit | `pytest tests/test_pppp_client.py::test_transport_close_guarded -x` | Wave 0 |
| CONN-03 | No zombie sockets after disconnect | unit | `pytest tests/test_pppp_client.py::test_no_zombie_sockets -x` | Wave 0 |
| CONN-05 | ConnectionState enum has correct values | unit | `pytest tests/test_pppp_client.py::test_connection_state_enum -x` | Wave 0 |
| CONN-05 | State transitions logged correctly | unit | `pytest tests/test_pppp_client.py::test_state_transition_logging -x` | Wave 0 |
| CONN-05 | State queryable via coordinator data | unit | `pytest tests/test_coordinator.py::test_state_queryable -x` | Wave 0 |
| CONN-05 | Coordinator gates reconnect by state | unit | `pytest tests/test_coordinator.py::test_coordinator_gates_reconnect -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/ -x -q`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/` directory -- does not exist, must create
- [ ] `tests/__init__.py` -- package init
- [ ] `tests/conftest.py` -- shared fixtures (mock transport, mock protocol, mock coordinator)
- [ ] `tests/test_pppp_client.py` -- covers CONN-01, CONN-02, CONN-03, CONN-05 (client-side)
- [ ] `tests/test_coordinator.py` -- covers CONN-05 coordinator integration
- [ ] `pytest.ini` or `pyproject.toml` `[tool.pytest.ini_options]` -- test configuration
- [ ] Framework install: `pip install pytest pytest-asyncio` -- pytest is available globally but pytest-asyncio likely needed for async test support

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | All code | Yes | 3.12.10 | -- |
| pytest | Unit tests | Yes | 9.0.2 | -- |
| pytest-asyncio | Async test support | Unknown | -- | `pip install pytest-asyncio` |
| asyncio (stdlib) | All async code | Yes | built-in | -- |
| Home Assistant | Runtime | N/A (dev machine) | -- | Tests use mocks, not real HA |

**Missing dependencies with no fallback:**
- None (all code is pure stdlib)

**Missing dependencies with fallback:**
- pytest-asyncio: likely not installed; install with `pip install pytest-asyncio` before running async tests

## Sources

### Primary (HIGH confidence)
- Python asyncio DatagramProtocol documentation (https://docs.python.org/3/library/asyncio-protocol.html) -- transport lifecycle, connection_lost, is_closing, sendto API
- Home Assistant DataUpdateCoordinator documentation (https://developers.home-assistant.io/docs/integration_fetching_data/) -- UpdateFailed, ConfigEntryNotReady, first_refresh behavior
- Home Assistant async best practices (https://developers.home-assistant.io/docs/asyncio_working_with_async/) -- event loop rules, async_add_executor_job, background tasks
- Existing codebase analysis -- pppp_client.py, coordinator.py, const.py, entity.py (primary source of truth)

### Secondary (MEDIUM confidence)
- AWS Architecture Blog: Exponential Backoff and Jitter (https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/) -- full jitter algorithm formula
- ESPHome integration architecture via DeepWiki (https://deepwiki.com/home-assistant/core/7.2-esphome-integration) -- ReconnectLogic pattern reference
- HA community discussions on DataUpdateCoordinator reconnection issues (https://community.home-assistant.io/t/dataupdatecoordinator-based-integrations-become-unavailable-after-a-few-hours/986502)

### Tertiary (LOW confidence)
- None -- all findings verified with official documentation or codebase analysis

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- zero external deps, all stdlib, verified against project constraints
- Architecture: HIGH -- patterns derived from existing codebase analysis + official asyncio docs + HA developer docs
- Pitfalls: HIGH -- all pitfalls identified from direct code inspection of current bugs/concerns (CONCERNS.md + pppp_client.py line-by-line review)

**Research date:** 2026-04-02
**Valid until:** 2026-05-02 (stable domain -- asyncio and HA coordinator APIs change slowly)
