---
phase: 04-sd-card-features
plan: 01
subsystem: camera-control
tags: [sd-card, recording, cgi, pppp, ha-entities]

# Dependency graph
requires:
  - phase: 02-camera-controls
    provides: CGI client pattern, _send_cgi, button/select entity patterns
provides:
  - CGI constants for unmount_sd, set_record_sch, get_record_file, get_record_calendar
  - RECORDING_MODE_MAP (Off/Continuous/Motion/Schedule)
  - RECORDING_SCHEDULE_PARAMS list (25 schedule parameters)
  - PNZEOClient.unmount_sd(), get_record_mode(), set_recording_schedule()
  - PNZEOClient.get_record_file_list(), get_record_calendar() (for Plan 04-02 MediaSource)
  - PNZEOUnmountSDButton entity
  - PNZEORecordingMode select entity
  - set_recording_schedule service (25-param schema)
affects: [04-02-sd-playback]

# Tech tracking
tech-stack:
  added: []
  patterns: [recording-schedule-bitmask-params, coordinator-record-mode-polling]

key-files:
  created: []
  modified:
    - custom_components/pnzeo_camera/pppp_packets.py
    - custom_components/pnzeo_camera/pppp_client.py
    - custom_components/pnzeo_camera/button.py
    - custom_components/pnzeo_camera/select.py
    - custom_components/pnzeo_camera/coordinator.py
    - custom_components/pnzeo_camera/__init__.py
    - custom_components/pnzeo_camera/services.yaml
    - custom_components/pnzeo_camera/strings.json

key-decisions:
  - "Recording mode polling added to every coordinator cycle (not 5th cycle like WiFi) since mode changes frequently"
  - "get_record_file_list and get_record_calendar added proactively for Plan 04-02 MediaSource"
  - "Unmount SD button disabled by default (destructive action)"

patterns-established:
  - "Recording schedule uses bitmask params (rec_sch_*_0/1/2 per day) matching camera CGI protocol"
  - "RECORDING_SCHEDULE_PARAMS list mirrors ALARM_PARAMS pattern for param validation"

requirements-completed: [SDCD-02, SDCD-03, SDCD-04, SDCD-05]

# Metrics
duration: 4min
completed: 2026-04-02
---

# Phase 04 Plan 01: SD Card Management Summary

**Unmount SD button, recording mode select (Off/Continuous/Motion/Schedule), 25-param recording schedule service, plus file list and calendar CGI client methods for MediaSource**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-02T16:28:03Z
- **Completed:** 2026-04-02T16:32:48Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- Full SD card unmount capability via button entity (mdi:eject, disabled by default)
- Recording mode select entity reads rec_mode from coordinator polling and sets via CGI
- set_recording_schedule service with complete 25-parameter schema for weekly schedule bitmasks
- Client methods for file list and calendar queries pre-built for Plan 04-02 MediaSource

## Task Commits

Each task was committed atomically:

1. **Task 1: Add CGI constants + client methods** - `6b537b7` (feat)
2. **Task 2: Add unmount button + recording mode select + service** - `1628ae5` (feat)

## Files Created/Modified
- `pppp_packets.py` - Added CGI_UNMOUNT_SD, CGI_SET_RECORD_SCH, CGI_GET_RECORD_FILE, CGI_GET_RECORD_CALENDAR constants + RECORDING_MODE_MAP
- `pppp_client.py` - Added unmount_sd(), get_record_mode(), set_recording_schedule(), get_record_file_list(), get_record_calendar() methods + RECORDING_SCHEDULE_PARAMS
- `button.py` - Added PNZEOUnmountSDButton entity
- `select.py` - Added PNZEORecordingMode entity with RECORDING_MODE_MAP
- `coordinator.py` - Added get_record_mode() polling in update cycle
- `__init__.py` - Registered set_recording_schedule service with 25-param vol.Schema
- `services.yaml` - Added set_recording_schedule with all 25 field definitions
- `strings.json` - Added set_recording_schedule service translations

## Decisions Made
- Recording mode polling runs every coordinator cycle (not throttled like WiFi) since recording mode can change frequently
- get_record_file_list and get_record_calendar pre-built for Plan 04-02 to avoid touching pppp_client.py again
- Unmount SD button disabled by default to prevent accidental SD card corruption

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all entities are wired to real client methods and coordinator data.

## Next Phase Readiness
- get_record_file_list() and get_record_calendar() client methods ready for Plan 04-02 MediaSource
- rec_mode available in coordinator.data for any future UI entities

## Self-Check: PASSED

All 8 modified files exist. Both task commits (6b537b7, 1628ae5) verified in git log. SUMMARY.md exists.

---
*Phase: 04-sd-card-features*
*Completed: 2026-04-02*
