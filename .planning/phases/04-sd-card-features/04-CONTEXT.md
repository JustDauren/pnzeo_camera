# Phase 4: SD Card Features - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase — discuss skipped)

<domain>
## Phase Boundary

Full SD card management with recording browsing via MediaSource. Requirements: SDCD-02 (format), SDCD-03 (unmount), SDCD-04 (recording mode), SDCD-05 (recording schedule), SDCD-06 (recording list), SDCD-07 (recording calendar), SDCD-08 (file download via MediaSource).

CGI methods for SD card already partially exist from Phase 2 (get_status returns SD info). New CGI endpoints needed: format_sd.cgi, unmount_sd.cgi, set_record_mode.cgi, get_record_mode.cgi, set_record_sch.cgi, get_record.cgi, get_record_calendar.cgi.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion. Key considerations:
- SD card format/unmount should be button entities with confirmation
- Recording mode as select entity (continuous/motion/schedule/off)
- MediaSource provider for browsing recordings by date
- File list pagination (startIdx, count) to avoid OOM
- Recording schedule is complex (25 params) — service call, not entity

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- pppp_client.py with _send_cgi() pattern (proven in Phase 2)
- button.py with existing reboot/factory reset buttons
- sensor.py with SD card capacity sensors (Phase 3)
- coordinator.py with polling infrastructure

### Integration Points
- New CGI methods → pppp_client.py
- New buttons → button.py
- New select → select.py
- MediaSource → media_source.py (new file)
- Platform registration → __init__.py

</code_context>

<specifics>
## Specific Ideas

From decompiled app: RTGetSDCardRecordFileList(did, startIdx, count, type, startTime, endTime)
supports pagination. RTGetSDRecordCalendar(did, month) returns bitmask of days with recordings.

</specifics>

<deferred>
## Deferred Ideas

None.

</deferred>
