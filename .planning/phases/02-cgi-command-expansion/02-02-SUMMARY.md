---
phase: 02-cgi-command-expansion
plan: 02
subsystem: camera-settings
tags: [ir-nightvision, power-frequency, device-name, time-sync, recording, cgi, text-entity]

requires:
  - phase: 02-01
    provides: "Alarm CGI methods, alarm switches, alarm action select, coordinator alarm polling"
provides:
  - "IR night vision mode select entity (auto/on/off)"
  - "Power frequency select entity (50Hz/60Hz)"
  - "Device name text entity"
  - "sync_time service"
  - "start_recording service"
  - "6 new client methods (get/set_ircut_params, set_power_freq, set_device_name, sync_time, start_recording)"
  - "IR_MODE_MAP and POWER_FREQ_MAP constants"
  - "Platform.TEXT registered"
affects: [02-03, 02-04, phase-03]

tech-stack:
  added: [homeassistant.components.text.TextEntity]
  patterns: [select-entity-with-coordinator-data-binding, text-entity-pattern, cgi-method-with-fallback]

key-files:
  created:
    - custom_components/pnzeo_camera/text.py
  modified:
    - custom_components/pnzeo_camera/pppp_packets.py
    - custom_components/pnzeo_camera/pppp_client.py
    - custom_components/pnzeo_camera/select.py
    - custom_components/pnzeo_camera/__init__.py
    - custom_components/pnzeo_camera/coordinator.py
    - custom_components/pnzeo_camera/services.yaml
    - custom_components/pnzeo_camera/strings.json

key-decisions:
  - "CGI_SET_MOBILETIME alias added alongside existing CGI_SET_DATETIME since both reference set_mobiletime.cgi -- sync_time uses CGI_SET_DATETIME"
  - "IR mode set_ircut_params tries full CGI first, falls back to camera_control param=14 for compatibility"
  - "Timezone offset calculated from system timezone for time sync"

patterns-established:
  - "Text entity pattern: PNZEOEntity + TextEntity with native_value from coordinator.data"
  - "Select entity with coordinator data binding: current_option reads from coordinator.data with safe fallback"
  - "CGI method with fallback: try advanced endpoint first, fall back to basic camera_control"

requirements-completed: [CSET-01, CSET-02, CSET-03, CSET-04, SYST-01, SYST-03, SYST-04, SNAP-01, SNAP-02]

duration: 3min
completed: 2026-04-02
---

# Phase 02 Plan 02: Camera Settings, System Commands & Snapshot/Recording Summary

**IR/power-freq select entities, device-name text entity, time-sync and manual-recording services with 6 new CGI client methods**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-02T15:44:29Z
- **Completed:** 2026-04-02T15:47:39Z
- **Tasks:** 2
- **Files modified:** 8 (7 modified + 1 created)

## Accomplishments
- Added 6 new client methods for camera settings: IR cut get/set, power frequency, device name, time sync, manual recording
- Created 2 new select entities (IR Mode: auto/on/off, Power Frequency: 50Hz/60Hz) with coordinator data binding
- Created text.py with PNZEODeviceName entity -- first text platform for the integration
- Registered Platform.TEXT and 2 new services (sync_time, start_recording)
- Verified existing button entities (reboot, factory reset, snapshot) and change_password service still intact
- Service guard sentinel 'ptz_control' preserved unchanged

## Task Commits

Each task was committed atomically:

1. **Task 1: Add camera settings and system CGI methods to pppp_client.py** - `b1b7515` (feat)
2. **Task 2: Add camera settings entities, text platform, system services, and verify existing buttons** - `4fdec20` (feat)

## Files Created/Modified
- `pppp_packets.py` - Added CGI_GET_IRCUT, CGI_SET_IRCUT, CGI_SET_DEVNAME, CGI_SET_MOBILETIME, CGI_START_RECORDING constants; IR_MODE_MAP and POWER_FREQ_MAP
- `pppp_client.py` - Added 6 methods: get_ircut_params, set_ircut_params, set_power_freq, set_device_name, sync_time, start_recording
- `select.py` - Added PNZEOIRMode and PNZEOPowerFrequency select entities with import of maps
- `text.py` - NEW: PNZEODeviceName text entity with async_set_value
- `__init__.py` - Added Platform.TEXT to PLATFORMS, sync_time and start_recording service handlers
- `coordinator.py` - Added IR cut params polling with 5s timeout in CONNECTED block
- `services.yaml` - Added sync_time and start_recording service definitions
- `strings.json` - Added sync_time and start_recording service strings

## Decisions Made
- CGI_SET_MOBILETIME alias kept alongside CGI_SET_DATETIME (both are "set_mobiletime.cgi") -- sync_time method uses CGI_SET_DATETIME to avoid import duplication
- IR mode set_ircut_params tries full set_ircut.cgi first, then falls back to camera_control param=14 for cameras that may not support the extended endpoint
- Timezone offset for time sync computed from Python's local timezone via datetime.astimezone().utcoffset()

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All camera settings entities and services complete
- Ready for Phase 02 Plan 03 (SD card management) and Plan 04 (WiFi/network)
- Existing buttons (reboot, factory reset, snapshot) verified operational
- Service guard unchanged -- all future service registrations append safely

## Self-Check: PASSED

- FOUND: text.py (created)
- FOUND: 02-02-SUMMARY.md
- FOUND: b1b7515 (Task 1 commit)
- FOUND: 4fdec20 (Task 2 commit)

---
*Phase: 02-cgi-command-expansion*
*Completed: 2026-04-02*
