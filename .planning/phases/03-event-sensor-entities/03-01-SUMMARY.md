---
phase: 03-event-sensor-entities
plan: 01
subsystem: entities
tags: [binary_sensor, sensor, event, coordinator, ha-entities]

# Dependency graph
requires:
  - phase: 02-cgi-command-expansion
    provides: alarm params polling (motion_armed, input_armed, ioEnable), get_status fields (sdtotal, sdfree, sysver)
provides:
  - Connection status binary sensor (PPPP connected/disconnected)
  - Motion detection binary sensor (motion_armed state)
  - Alarm event entity (fires HA events on motion_armed transitions)
  - SD card capacity sensors (total/free/used in MB)
  - Device info sensors (firmware version, device name)
affects: [04-sd-card-management, 06-config-flow-polish]

# Tech tracking
tech-stack:
  added: []
  patterns: [EventEntity with _handle_coordinator_update for state transition detection, always-available binary sensor for connectivity]

key-files:
  created:
    - binary_sensor.py
    - sensor.py
    - event.py
  modified:
    - __init__.py

key-decisions:
  - "Connection binary sensor overrides available=True to remain visible when camera is disconnected"
  - "Event entity uses _handle_coordinator_update to detect motion_armed 0->1 transitions without adding extra polling"
  - "SD used sensor computed from total-free rather than separate CGI query"

patterns-established:
  - "EventEntity pattern: track previous state in _handle_coordinator_update, fire _trigger_event on transition"
  - "Diagnostic sensor pattern: EntityCategory.DIAGNOSTIC for system info (firmware, SD card, connection)"
  - "Always-available entity: override available property to True for connectivity sensors"

requirements-completed: [CONN-04, ALRM-05, ALRM-06, SDCD-01, SYST-02]

# Metrics
duration: 2min
completed: 2026-04-02
---

# Phase 3 Plan 1: Event/Sensor Entities Summary

**Binary sensors for connection/motion, 5 diagnostic sensors (SD card + device info), and alarm event entity with state transition detection**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-02T16:16:33Z
- **Completed:** 2026-04-02T16:18:29Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Connection binary sensor shows PPPP connectivity state with connection_method attribute, always visible even when disconnected
- Motion binary sensor reflects motion_armed state from polling, satisfying ALRM-05
- Alarm event entity detects motion_armed 0->1 transitions and fires HA events for automations (ALRM-06)
- 3 SD card sensors (total/free/used) with DATA_SIZE device class in megabytes (SDCD-01)
- 2 device info sensors (firmware version, device name) as diagnostics (SYST-02)
- All 9 platforms registered in __init__.py (6 existing + 3 new)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create binary_sensor.py, sensor.py, and event.py** - `65fcbde` (feat)
2. **Task 2: Register new platforms in __init__.py** - `0749cef` (feat)

## Files Created/Modified
- `binary_sensor.py` - Connection status + motion detection binary sensors (2 entities)
- `sensor.py` - SD card capacity + device info sensors (5 entities)
- `event.py` - Alarm event entity with state transition detection (1 entity)
- `__init__.py` - Added Platform.BINARY_SENSOR, Platform.SENSOR, Platform.EVENT to PLATFORMS list

## Decisions Made
- Connection binary sensor overrides available=True so it remains visible in HA even when camera is disconnected -- otherwise the connectivity sensor would disappear exactly when it's most useful
- Event entity uses _handle_coordinator_update (not custom polling) to detect motion_armed transitions, keeping the entity coordinator-driven
- SD used sensor is computed (total - free) rather than adding a separate CGI query, conserving the Pi5 60s polling budget

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All 8 entities (2 binary sensors, 5 sensors, 1 event) ready for HA dashboard exposure
- Alarm event entity provides automation trigger for motion detection
- SD card capacity sensors provide foundation for Phase 4 SD card management

## Self-Check: PASSED

- binary_sensor.py: FOUND
- sensor.py: FOUND
- event.py: FOUND
- Commit 65fcbde: FOUND
- Commit 0749cef: FOUND

---
*Phase: 03-event-sensor-entities*
*Completed: 2026-04-02*
