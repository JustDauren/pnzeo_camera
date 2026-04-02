---
phase: 02-cgi-command-expansion
plan: 01
subsystem: api
tags: [pppp, cgi, alarm, motion-detection, gpio, sound-detection, homeassistant]

# Dependency graph
requires:
  - phase: 01-connection-reliability
    provides: stable PPPP connection, CGI command infrastructure, coordinator polling
provides:
  - 7 alarm CGI client methods (get/set alarm, get/set alarm_ex, alarm log, sound, gpio)
  - 2 alarm switch entities (sound detection, GPIO alarm)
  - 1 motion sensitivity number entity (0-9 range)
  - 1 alarm action select entity (mail/snapshot/record combinations)
  - alarm params polling in coordinator (5s timeout per call)
  - get_alarm_log service
affects: [02-cgi-command-expansion, 03-media-sd-card]

# Tech tracking
tech-stack:
  added: []
  patterns: [GET-before-SET for alarm params, coordinator-data-driven entity state]

key-files:
  created: []
  modified:
    - custom_components/pnzeo_camera/pppp_packets.py
    - custom_components/pnzeo_camera/pppp_client.py
    - custom_components/pnzeo_camera/coordinator.py
    - custom_components/pnzeo_camera/switch.py
    - custom_components/pnzeo_camera/number.py
    - custom_components/pnzeo_camera/select.py
    - custom_components/pnzeo_camera/__init__.py
    - custom_components/pnzeo_camera/services.yaml
    - custom_components/pnzeo_camera/strings.json

key-decisions:
  - "GET-before-SET for all alarm params -- always fetch current 33/11 values, merge changes, send full set"
  - "Motion sensitivity uses camera-native 0-9 range (0=most sensitive) rather than inverting for UX"
  - "New alarm switches disabled by default (entity_registry_enabled_default=False) since not all cameras support them"
  - "Motion switch now reads from coordinator data instead of internal boolean for real camera state"

patterns-established:
  - "GET-before-SET pattern: always fetch current params before setting to avoid partial updates"
  - "Coordinator-data-driven entity state: entities read from coordinator.data instead of internal booleans"
  - "Alarm polling with 5s timeout per call to protect Pi5 60s polling budget"

requirements-completed: [ALRM-01, ALRM-02, ALRM-03, ALRM-04, ALRM-07, ALRM-08, ALRM-09]

# Metrics
duration: 4min
completed: 2026-04-02
---

# Phase 02 Plan 01: Alarm CGI Commands Summary

**Full alarm CGI command suite with GET-before-SET safety, motion/sound/GPIO switches, sensitivity slider, and alarm action select**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-02T15:37:09Z
- **Completed:** 2026-04-02T15:41:13Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- 7 alarm CGI methods in pppp_client.py with full GET-before-SET merge pattern
- 2 new switch entities (sound detection alarm, GPIO alarm) and 1 select entity (alarm action)
- Motion sensitivity number entity with camera-native 0-9 range
- Coordinator polls alarm params with 5s timeout each (Pi5 safe)
- get_alarm_log service fires HA event with alarm log entries
- Existing motion switch upgraded to read state from coordinator data

## Task Commits

Each task was committed atomically:

1. **Task 1: Add alarm CGI methods to pppp_client.py and constants to pppp_packets.py** - `fc4dfb7` (feat)
2. **Task 2: Add alarm entities and coordinator polling** - `04e197a` (feat)

## Files Created/Modified
- `pppp_packets.py` - Added CGI_GET_ALARM_EX, CGI_SET_ALARM_EX, CGI_GET_ALARM_LOG constants
- `pppp_client.py` - Added 7 alarm methods, ALARM_PARAMS (33) and ALARM_EX_PARAMS (11) validation lists
- `coordinator.py` - Added alarm params polling with asyncio.wait_for 5s timeout
- `switch.py` - Added PNZEOSoundAlarmSwitch, PNZEOGPIOAlarmSwitch; updated PNZEOMotionSwitch to use coordinator data
- `number.py` - Added PNZEOMotionSensitivity (0-9 range, slider mode)
- `select.py` - Added PNZEOAlarmAction (8 mail/snapshot/record combinations)
- `__init__.py` - Added get_alarm_log service handler with event firing
- `services.yaml` - Added get_alarm_log service definition
- `strings.json` - Added get_alarm_log service strings

## Decisions Made
- GET-before-SET for all alarm params: always fetch current 33/11 values before setting to avoid partial updates (per Pitfall 11 from APK decompilation)
- Motion sensitivity uses camera-native 0-9 range (0=most sensitive, 9=least sensitive) rather than inverting for UX -- matches what camera firmware expects
- New alarm switches disabled by default since not all PNZEO cameras support sound/GPIO alarm
- Upgraded existing PNZEOMotionSwitch from internal boolean state to coordinator data-driven state for accuracy

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Alarm CGI infrastructure complete, ready for remaining CGI command plans (02-02 through 02-04)
- Pattern established for GET-before-SET can be reused for SD card recording params
- Coordinator polling pattern with timeouts ready for additional param polling

## Self-Check: PASSED

All 9 modified files verified present. Both task commits (fc4dfb7, 04e197a) verified in git log. SUMMARY.md created successfully.

---
*Phase: 02-cgi-command-expansion*
*Completed: 2026-04-02*
