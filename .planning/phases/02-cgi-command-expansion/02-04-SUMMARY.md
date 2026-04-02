---
phase: 02-cgi-command-expansion
plan: 04
subsystem: notifications
tags: [ftp, email, smtp, fcm, push-notifications, cgi, pppp]

# Dependency graph
requires:
  - phase: 02-cgi-command-expansion (plans 01-03)
    provides: CGI command pattern, service registration pattern, coordinator polling cycle
provides:
  - FTP upload configuration via set_ftp service and get_ftp_settings on-demand retrieval
  - Email notification configuration via set_email service and get_email_settings on-demand retrieval
  - FCM push notification token registration via set_push_token service
  - 5 CGI endpoint constants (CGI_GET_FTP, CGI_SET_FTP, CGI_GET_MAIL, CGI_SET_MAIL, CGI_SET_FCM)
  - 5 client methods (get_ftp_params, set_ftp, get_mail_params, set_mail, set_push_token)
affects: [phase-03, phase-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "On-demand service calls for infrequent settings (not polled) to protect Pi5 60s budget"
    - "HA event bus for settings retrieval results (pnzeo_camera_ftp_settings, pnzeo_camera_email_settings)"

key-files:
  created: []
  modified:
    - custom_components/pnzeo_camera/pppp_packets.py
    - custom_components/pnzeo_camera/pppp_client.py
    - custom_components/pnzeo_camera/__init__.py
    - custom_components/pnzeo_camera/services.yaml
    - custom_components/pnzeo_camera/strings.json

key-decisions:
  - "FTP/email settings are service-call-only (NOT polled) to protect Pi5 60s coordinator budget"
  - "get_ftp_settings and get_email_settings fire HA events for result delivery (same pattern as wifi_scan, get_users)"
  - "set_push_token logs warning on failure since MSG_SET_FCM_PUSH=97 may require binary protocol on some cameras"

patterns-established:
  - "On-demand settings retrieval: service call fires HA event with results, no coordinator polling"

requirements-completed: [NOTF-01, NOTF-02, NOTF-03]

# Metrics
duration: 3min
completed: 2026-04-02
---

# Phase 02 Plan 04: Notification Settings Summary

**FTP upload, email notification, and FCM push token configuration via 5 on-demand service calls with CGI-over-DRW protocol**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-02T15:57:16Z
- **Completed:** 2026-04-02T16:00:29Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- 5 CGI endpoint constants and 5 client methods for FTP, email, and push notification configuration
- 5 HA services registered: set_ftp, set_email, set_push_token, get_ftp_settings, get_email_settings
- FTP/email retrieval is on-demand only (fires HA events), NOT polled -- protects Pi5 60s budget
- Service guard unchanged (ptz_control sentinel preserved)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add FTP, email, and push notification CGI methods** - `b507ecd` (feat)
2. **Task 2: Register FTP, email, push, and settings retrieval services** - `84382e7` (feat)

## Files Created/Modified
- `pppp_packets.py` - Added CGI_GET_FTP, CGI_SET_FTP, CGI_GET_MAIL, CGI_SET_MAIL, CGI_SET_FCM constants
- `pppp_client.py` - Added get_ftp_params, set_ftp, get_mail_params, set_mail, set_push_token methods
- `__init__.py` - Registered 5 new services with vol schemas and event-based retrieval
- `services.yaml` - Service definitions with field descriptions for all 5 services
- `strings.json` - UI strings for all 5 services and their fields

## Decisions Made
- FTP/email settings are service-call-only (NOT polled) to protect Pi5 60s coordinator budget
- get_ftp_settings and get_email_settings fire HA events for result delivery (consistent with wifi_scan, get_users pattern)
- set_push_token logs warning on failure since MSG_SET_FCM_PUSH=97 may require binary protocol on some cameras

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None - all services are fully wired to client methods with real CGI endpoints.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All Phase 02 plans (01-04) complete
- Camera now has full CGI command expansion: alarm settings, IR/device/recording/time, WiFi/network/users, and FTP/email/push notifications
- Ready for Phase 03 (SD card management) or Phase 04 (alarm events)

## Self-Check: PASSED

All files verified on disk. Both task commits (b507ecd, 84382e7) confirmed in git log.

---
*Phase: 02-cgi-command-expansion*
*Completed: 2026-04-02*
