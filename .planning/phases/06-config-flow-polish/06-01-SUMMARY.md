---
phase: 06-config-flow-polish
plan: 01
subsystem: config-flow
tags: [config-flow, discovery, pppp, capabilities, voluptuous]

# Dependency graph
requires:
  - phase: 01-connection-reliability
    provides: PNZEOClient with connect(), capabilities, disconnect()
  - phase: 01-connection-reliability
    provides: pppp_discovery with discover_cameras(), check_rtsp()
provides:
  - Multi-step config flow with LAN auto-discovery and camera selection
  - Manual UID entry with optional IP for cloud relay cameras
  - Password validation via PPPP check_user.cgi during setup
  - Capability detection stored in config_entry.data for entity platforms
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Config flow capability capture: _verify_pppp_login populates self._capabilities from client.capabilities"
    - "Tri-state PPPP verification: True (auth OK), None (can't check, allow anyway), False (wrong password)"

key-files:
  created: []
  modified:
    - config_flow.py
    - const.py
    - strings.json
    - translations/en.json

key-decisions:
  - "Manual step accepts device_id (required) + host (optional) -- UID is the primary identifier, IP is only needed for LAN-only cameras without cloud relay"
  - "Credentials step removed device_id field -- moved to discovery/manual steps for cleaner UX flow"
  - "Capabilities stored as plain dict in config_entry.data -- JSON-serializable, persisted by HA in .storage/core.config_entries"
  - "Empty capabilities dict on timeout/error -- entities will use defaults when capabilities unknown"

patterns-established:
  - "CONF_CAPABILITIES in config_entry.data: entity platforms can read capabilities at setup to conditionally create entities"
  - "Device ID flows through discovery or manual steps, not credentials step"

requirements-completed: [CONF-01, CONF-02, CONF-03, CONF-04]

# Metrics
duration: 2min
completed: 2026-04-02
---

# Phase 6 Plan 1: Config Flow Polish Summary

**Multi-step config flow with LAN auto-discovery, manual UID entry, PPPP password validation, and capability storage in config_entry.data**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-02T17:12:19Z
- **Completed:** 2026-04-02T17:14:30Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Config flow auto-discovers cameras via LAN UDP broadcast and shows selection list with UID and IP
- Manual UID entry (required) with optional IP address for LAN-only or cloud relay cameras
- Password validated during setup via PPPP connect + check_user.cgi with 15s timeout
- Capabilities from check_user.cgi stored in config_entry.data[CONF_CAPABILITIES] for entity platform consumption

## Task Commits

Each task was committed atomically:

1. **Task 1: Add CONF_CAPABILITIES constant and update UI strings** - `6413a39` (feat)
2. **Task 2: Rewrite config_flow.py with discovery, manual UID, password validation, and capability storage** - `1559806` (feat)

## Files Created/Modified
- `const.py` - Added CONF_CAPABILITIES = "capabilities" constant
- `strings.json` - Updated manual step (device_id + host), credentials step (password + rtsp_port only), added unknown error
- `translations/en.json` - Synced with strings.json config section
- `config_flow.py` - Full rewrite: 6-step flow (user, discover, pick, manual, credentials, entry creation) with capability capture

## Decisions Made
- Manual step accepts device_id (required) + host (optional) -- UID is the primary identifier, IP is only needed for LAN-only cameras
- Credentials step removed device_id field -- moved to discovery/manual steps for cleaner UX
- Capabilities stored as plain dict in config_entry.data -- JSON-serializable, persisted by HA
- Empty capabilities dict on timeout/error -- entities use defaults when capabilities unknown

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- This is the final phase (Phase 6) of the v1.0 milestone
- Config flow is production-ready with full discovery, manual entry, password validation, and capability detection
- All CONF-01 through CONF-04 requirements completed

---
*Phase: 06-config-flow-polish*
*Completed: 2026-04-02*
