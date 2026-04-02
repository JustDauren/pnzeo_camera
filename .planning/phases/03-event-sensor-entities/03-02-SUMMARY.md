---
phase: 03-event-sensor-entities
plan: 02
subsystem: diagnostics
tags: [diagnostics, ha-diagnostics-panel, connection-stats, capability-dump]

# Dependency graph
requires:
  - phase: 01-connection-reliability
    provides: ConnectionState enum, PNZEOClient properties (connection_state, connection_method, capabilities)
  - phase: 02-cgi-command-expansion
    provides: PNZEOCoordinator with full camera_params polling
provides:
  - HA diagnostics panel integration (Settings > Devices > PNZEO Camera > Diagnostics)
  - Connection troubleshooting data (state, method, pppp_available, host, device_id)
  - Camera capability dump for debugging
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns: [ha-diagnostics-convention, async_redact_data-privacy]

key-files:
  created: [diagnostics.py]
  modified: []

key-decisions:
  - "diagnostics.py is auto-discovered by HA -- no PLATFORMS registration needed"
  - "TO_REDACT covers HA constants plus CGI-specific password fields (loginuse, loginpas, pwd1-3)"

patterns-established:
  - "HA diagnostics: single function returning 4-section dict (config_entry, connection, capabilities, camera_state)"

requirements-completed: [DIAG-01, DIAG-02]

# Metrics
duration: 1min
completed: 2026-04-02
---

# Phase 3 Plan 2: Diagnostics Summary

**HA diagnostics panel with connection stats, protocol state, and full camera capability dump -- passwords redacted via async_redact_data**

## Performance

- **Duration:** 1 min
- **Started:** 2026-04-02T16:16:37Z
- **Completed:** 2026-04-02T16:17:20Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- Created diagnostics.py with async_get_config_entry_diagnostics for HA diagnostics panel
- Connection section exposes state, method, pppp_available, host, device_id for troubleshooting (DIAG-01)
- Capabilities section dumps raw RTGetCapability dict for debugging (DIAG-02)
- Camera state section includes full coordinator.data with sensitive fields redacted

## Task Commits

Each task was committed atomically:

1. **Task 1: Create diagnostics.py with connection stats and capability dump** - `374dd6d` (feat)
2. **Task 2: Verify diagnostics.py standalone syntax and HA import compatibility** - verification-only, no file changes

## Files Created/Modified
- `diagnostics.py` - HA diagnostics panel integration with 4-section diagnostic dump (config_entry, connection, capabilities, camera_state)

## Decisions Made
- diagnostics.py is auto-discovered by HA convention -- no PLATFORMS list entry or platform registration needed
- TO_REDACT set covers both HA standard fields (CONF_PASSWORD, CONF_USERNAME) and CGI-specific credential fields (loginuse, loginpas, pwd1-3)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Diagnostics panel fully functional once integration is loaded
- No blockers for subsequent phases

## Self-Check: PASSED

- diagnostics.py: FOUND
- Commit 374dd6d: FOUND
- 03-02-SUMMARY.md: FOUND

---
*Phase: 03-event-sensor-entities*
*Completed: 2026-04-02*
