---
phase: 01-connection-reliability
plan: 01
subsystem: protocol
tags: [enum, connection-state, pytest, asyncio, testing]

requires:
  - phase: none
    provides: n/a (first plan in first phase)
provides:
  - ConnectionState IntEnum with 6 lifecycle states
  - Backoff constants for reconnection (BACKOFF_BASE, BACKOFF_MAX_LAN, BACKOFF_MAX_CLOUD, MAX_RECONNECT_ATTEMPTS)
  - pytest + pytest-asyncio test infrastructure
  - Shared test fixtures (mock_transport, client, connected_client)
  - Test stubs for CONN-01, CONN-02, CONN-03, CONN-05
affects: [01-02-PLAN, 01-03-PLAN, all-future-test-plans]

tech-stack:
  added: [pytest, pytest-asyncio, voluptuous]
  patterns: [IntEnum for state machine, HA-mock test conftest, no-__init__-in-tests pattern]

key-files:
  created:
    - pyproject.toml
    - tests/conftest.py
    - tests/test_pppp_client.py
    - tests/test_coordinator.py
    - .gitignore
  modified:
    - const.py

key-decisions:
  - "ConnectionState uses IntEnum (not Enum) for numeric comparison support"
  - "tests/ has no __init__.py to avoid triggering pnzeo_camera/__init__.py import chain (homeassistant not available outside HA runtime)"
  - "HA dependencies mocked in conftest.py via sys.modules -- standard pattern for HA custom component testing without full HA stack"
  - "Tests must be run from outside repo root (cd /tmp && pytest) to avoid select.py shadowing Python stdlib"

patterns-established:
  - "HA mock pattern: sys.modules mocks for homeassistant in tests/conftest.py before component imports"
  - "No tests/__init__.py: prevents parent package __init__.py resolution in HA custom components"
  - "Test invocation: cd /tmp && python3 -m pytest <repo>/tests/ -v --rootdir=<repo>"

requirements-completed: [CONN-05]

duration: 14min
completed: 2026-04-02
---

# Phase 01 Plan 01: ConnectionState Enum and Test Scaffold Summary

**ConnectionState IntEnum with 6 lifecycle states, backoff constants, and pytest test scaffold with 3 passing + 21 skipped stub tests**

## Performance

- **Duration:** 14 min
- **Started:** 2026-04-02T14:24:48Z
- **Completed:** 2026-04-02T14:39:32Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- ConnectionState IntEnum with 6 states (DISCONNECTED=0 through FAILED=5) in const.py, replacing legacy PPPP_STATUS_* constants
- Backoff constants (BACKOFF_BASE=2.0, BACKOFF_MAX_LAN=30.0, BACKOFF_MAX_CLOUD=60.0, MAX_RECONNECT_ATTEMPTS=5) for Plans 02-03
- Full pytest scaffold with HA-mocked conftest, 3 passing enum tests, and 21 skipped stubs covering CONN-01/02/03/05

## Task Commits

Each task was committed atomically:

1. **Task 1: Add ConnectionState enum and backoff constants** - `0fa0913` (feat)
2. **Task 1 fix: Remove legacy constant reference from docstring** - `802f5d7` (fix)
3. **Task 2: Create test scaffold with fixtures and placeholder tests** - `9f73f9e` (feat)

## Files Created/Modified
- `const.py` - Added ConnectionState IntEnum and backoff constants, removed PPPP_STATUS_* block
- `pyproject.toml` - pytest configuration with asyncio_mode=auto
- `tests/conftest.py` - HA dependency mocking, sys.path setup, shared fixtures (mock_transport, client, connected_client)
- `tests/test_pppp_client.py` - 3 passing enum tests + 16 skipped stubs for CONN-01/02/03/05
- `tests/test_coordinator.py` - 5 skipped coordinator stubs for CONN-05
- `.gitignore` - __pycache__ and .pytest_cache exclusions

## Decisions Made
- Used IntEnum (not Enum) so ConnectionState values can be compared numerically (e.g., `state > DISCONNECTED`)
- Omitted `tests/__init__.py` because having it causes Python to resolve `pnzeo_camera/__init__.py` (which imports `homeassistant`) before any test code runs. This is the standard pattern for HA custom component testing without the full HA stack.
- Tests must be invoked from outside the repo root (`cd /tmp && python3 -m pytest <repo>/tests/`) because the repo contains `select.py` which shadows Python's stdlib `select` module when CWD is on sys.path
- Installed `voluptuous` as test dependency since it is imported by `__init__.py` and is a small pure-Python package (unlike `homeassistant`)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Omitted tests/__init__.py to avoid import chain failure**
- **Found during:** Task 2 (test scaffold creation)
- **Issue:** When `tests/__init__.py` exists, Python treats `tests/` as a subpackage of `pnzeo_camera/`, triggering `pnzeo_camera/__init__.py` which imports `homeassistant` (unavailable outside HA runtime). This caused `ModuleNotFoundError: No module named 'homeassistant'` before any test code could run.
- **Fix:** Removed `tests/__init__.py`. pytest discovers tests via `testpaths` in `pyproject.toml` instead of Python package resolution.
- **Files modified:** tests/__init__.py (removed)
- **Verification:** `cd /tmp && python3 -m pytest <repo>/tests/ -v` collects and runs 24 tests (3 passed, 21 skipped)
- **Committed in:** 9f73f9e (Task 2 commit)

**2. [Rule 3 - Blocking] Installed voluptuous and mocked homeassistant in conftest.py**
- **Found during:** Task 2 (test scaffold creation)
- **Issue:** Component's `__init__.py` imports `voluptuous` and `homeassistant`, both unavailable in test environment. Even importing `const.py` triggers the full package import chain.
- **Fix:** Installed `voluptuous` via pip (small pure-Python dependency). Mocked `homeassistant` modules via `sys.modules` in `tests/conftest.py` before any component imports.
- **Files modified:** tests/conftest.py
- **Verification:** All imports resolve correctly, tests run without errors
- **Committed in:** 9f73f9e (Task 2 commit)

**3. [Rule 3 - Blocking] Tests require invocation from outside repo root**
- **Found during:** Task 2 (test scaffold creation)
- **Issue:** Repo root contains `select.py` (HA SelectEntity platform file) which shadows Python's stdlib `select` module when CWD is on sys.path. pytest adds CWD to sys.path before any conftest runs.
- **Fix:** Documented test invocation pattern: `cd /tmp && python3 -m pytest <repo>/tests/ -v --rootdir=<repo>`. conftest.py also removes repo root from sys.path.
- **Files modified:** tests/conftest.py (sys.path cleanup)
- **Verification:** Tests run successfully from /tmp
- **Committed in:** 9f73f9e (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (3 blocking issues)
**Impact on plan:** All auto-fixes necessary for tests to work without the full Home Assistant environment installed. The omission of `tests/__init__.py` is standard practice for HA custom component testing. No scope creep.

## Issues Encountered
- Python's import resolution triggers `__init__.py` of parent packages before any test code can mock dependencies. Solved by removing `tests/__init__.py` and mocking in `conftest.py` at module level.
- `select.py` in repo root shadows Python stdlib `select` module. Solved by running tests from outside repo root directory.

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all code in this plan is production-ready (enum and constants) or intentionally marked as test stubs (pytest.mark.skip for Plans 02-03).

## Next Phase Readiness
- ConnectionState enum ready for import by Plans 02 (pppp_client) and 03 (coordinator)
- Backoff constants ready for reconnection logic in Plan 02
- Test stubs ready -- Plans 02-03 will remove `@pytest.mark.skip` and add real assertions
- Test invocation pattern documented for all future test plans

## Self-Check: PASSED

All 6 created files verified present. All 3 commit hashes found in git log.

---
*Phase: 01-connection-reliability*
*Completed: 2026-04-02*
