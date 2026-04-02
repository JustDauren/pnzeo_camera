---
phase: 01-connection-reliability
plan: 02
subsystem: protocol
tags: [connection-state, watchdog, reconnect, backoff, keepalive, asyncio, try-finally]

requires:
  - phase: 01-01
    provides: ConnectionState IntEnum, backoff constants, test scaffold with fixtures
provides:
  - Full ConnectionState-driven lifecycle in pppp_client.py
  - Connection watchdog coroutine (_connection_watchdog) for keepalive supervision
  - Exponential backoff reconnection (_reconnect_with_backoff) with full jitter
  - try-finally socket cleanup in _do_connect with is_closing() guards
  - State-guarded _send_cgi (returns None when not CONNECTED/AUTHENTICATING)
  - Refactored keepalive loop with failure tracking and WARNING-level logging
  - 19 passing tests covering CONN-01, CONN-02, CONN-03, CONN-05
affects: [01-03-PLAN, coordinator-integration, all-future-client-consumers]

tech-stack:
  added: []
  patterns: [ConnectionState enum replaces boolean flags, watchdog task supervises keepalive, exponential backoff with full jitter, try-finally for transport cleanup, is_closing() guard before transport.close()]

key-files:
  created: []
  modified:
    - pppp_client.py
    - tests/test_pppp_client.py
    - tests/conftest.py

key-decisions:
  - "_send_cgi allows both CONNECTED and AUTHENTICATING states to support CGI login during connection flow"
  - "_cleanup_transport() does NOT change connection state -- state transitions are explicit via _set_state()"
  - "Watchdog triggers reconnect after 3 consecutive keepalive failures, not on first failure"
  - "connection_lost() and CLOSE handler only transition to DISCONNECTED if currently CONNECTED -- prevents state conflicts during reconnection"

patterns-established:
  - "State transition via _set_state(): all state changes go through this method for consistent INFO-level logging"
  - "Watchdog pattern: background task checks keepalive health every 6s (2x KEEPALIVE_INTERVAL)"
  - "Backoff formula: min(BACKOFF_BASE * 2^attempt, max_delay) with random.uniform(0, delay) for full jitter"
  - "Transport cleanup: always check is_closing() before calling close() to avoid double-close errors"

requirements-completed: [CONN-01, CONN-02, CONN-03, CONN-05]

duration: 5min
completed: 2026-04-02
---

# Phase 01 Plan 02: Connection State Machine, Watchdog, and Reconnect Summary

**ConnectionState-driven lifecycle with watchdog, exponential backoff reconnect, try-finally cleanup, and 19 green tests**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-02T14:42:28Z
- **Completed:** 2026-04-02T14:47:30Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Replaced boolean _connected/_authenticated flags with ConnectionState enum throughout pppp_client.py (zero boolean state assignments remaining)
- Added _connection_watchdog() that detects dead keepalive within 6 seconds and triggers reconnection after 3 consecutive failures
- Added _reconnect_with_backoff() with exponential delays (base 2s, max 30s LAN / 60s cloud) and full jitter
- Filled all 16 test stubs with real assertions -- 19 tests PASSED, 0 FAILED, 0 SKIPPED, 48 assertions total

## Task Commits

Each task was committed atomically:

1. **Task 1: Refactor pppp_client.py with ConnectionState, watchdog, reconnect, and cleanup** - `2442421` (feat)
2. **Task 2: Fill test stubs with real assertions for pppp_client** - `e8387bd` (test)

## Files Created/Modified
- `pppp_client.py` - Full ConnectionState-driven lifecycle: _set_state(), _connection_watchdog(), _reconnect_with_backoff(), refactored _keepalive_loop(), _cleanup_transport() with is_closing() guard, state-guarded _send_cgi()
- `tests/test_pppp_client.py` - 19 tests covering CONN-01 (reconnect backoff), CONN-02 (watchdog + keepalive), CONN-03 (socket lifecycle), CONN-05 (state transitions)
- `tests/conftest.py` - Updated connected_client fixture to use ConnectionState.CONNECTED instead of boolean flags

## Decisions Made
- Allowed _send_cgi() during both CONNECTED and AUTHENTICATING states because _cgi_login() is called inside _do_connect() before state transitions to CONNECTED
- _cleanup_transport() is state-agnostic (only cleans transport/protocol) -- state transitions remain explicit through _set_state() to prevent accidental state changes during reconnection
- connection_lost() and CLOSE handler only transition to DISCONNECTED if currently CONNECTED, preventing state conflicts when transport cleanup fires during reconnection
- Watchdog threshold is 3 consecutive keepalive failures before triggering reconnect -- single failures get a restart attempt

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test assertion accessing mock after patch exit**
- **Found during:** Task 2 (test_max_reconnect_attempts)
- **Issue:** `client._do_connect.call_count` was accessed after the `with patch.object(...)` context manager exited, so `_do_connect` was restored to the original method which has no `call_count` attribute
- **Fix:** Moved the call_count assertion inside the `with` block and captured the mock via `as mock_connect`
- **Files modified:** tests/test_pppp_client.py
- **Verification:** All 19 tests pass
- **Committed in:** e8387bd (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Minor test code fix. No scope creep.

## Issues Encountered
None -- plan executed as specified.

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all code is production-ready. No TODO/FIXME/placeholder patterns found in modified files.

## Next Phase Readiness
- pppp_client.py has complete ConnectionState lifecycle -- ready for coordinator integration in Plan 03
- All 19 client-side tests pass -- coordinator tests (test_coordinator.py) still have 5 skipped stubs for Plan 03
- Backward-compatible `connected` property works for existing coordinator.py and entity.py consumers

## Self-Check: PASSED

All 3 modified files verified present. Both commit hashes (2442421, e8387bd) found in git log.

---
*Phase: 01-connection-reliability*
*Completed: 2026-04-02*
