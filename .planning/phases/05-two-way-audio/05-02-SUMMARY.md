---
phase: 05-two-way-audio
plan: 02
subsystem: audio
tags: [audio, g711, alaw, microphone, cgi, services, switch]

# Dependency graph
requires:
  - phase: 05-01
    provides: "Audio streaming methods (start_audio_stream, stop_audio_stream, send_talk_data), G.711 codec (alaw_encode/alaw_decode), audio constants"
provides:
  - "listen_audio/stop_audio/talk HA services for audio control"
  - "PNZEOMicrophoneSwitch entity for mic on/off"
  - "set_voice_enable CGI method in pppp_client.py"
  - "Audio service definitions in services.yaml"
affects: [06-config-flow]

# Tech tracking
tech-stack:
  added: []
  patterns: ["service-call audio pipeline: base64 PCM -> alaw_encode -> send_talk_data -> DRW CH_TALK"]

key-files:
  created: []
  modified:
    - "custom_components/pnzeo_camera/__init__.py"
    - "custom_components/pnzeo_camera/switch.py"
    - "custom_components/pnzeo_camera/pppp_client.py"
    - "custom_components/pnzeo_camera/services.yaml"
    - "custom_components/pnzeo_camera/strings.json"

key-decisions:
  - "Microphone switch uses coordinator-data-driven state (voice_enable param) matching PNZEOMotionSwitch pattern"
  - "Talk service accepts base64 PCM and encodes to A-law inline -- simple one-shot pipeline"
  - "Audio events fired on HA bus (pnzeo_camera_audio_started/stopped) for automation triggers"

patterns-established:
  - "Audio service pattern: base64 input -> codec encode -> DRW channel send"

requirements-completed: [AUDI-01, AUDI-02, AUDI-03]

# Metrics
duration: 3min
completed: 2026-04-02
---

# Phase 05 Plan 02: Audio Services + Microphone Switch Summary

**Audio services (listen/stop/talk) registered in HA with base64 PCM->A-law pipeline, plus microphone switch via set_voice.cgi CGI**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-02T16:59:24Z
- **Completed:** 2026-04-02T17:02:40Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Microphone switch entity (PNZEOMicrophoneSwitch) with coordinator-data-driven state and set_voice.cgi CGI
- Three audio services: listen_audio (starts DRW CH_AUDIO stream), stop_audio (stops stream), talk (base64 PCM -> A-law -> DRW CH_TALK)
- Service definitions in services.yaml and strings.json for HA UI integration
- Audio events fired on HA bus for automation triggers (pnzeo_camera_audio_started, pnzeo_camera_audio_stopped)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add microphone switch to switch.py + set_voice_enable CGI method** - `6695a97` (feat)
2. **Task 2: Register audio services in __init__.py and services.yaml** - `f0ca599` (feat)

## Files Created/Modified
- `custom_components/pnzeo_camera/pppp_client.py` - Added set_voice_enable() method using set_voice.cgi CGI endpoint
- `custom_components/pnzeo_camera/switch.py` - Added PNZEOMicrophoneSwitch class and registered in async_setup_entry
- `custom_components/pnzeo_camera/__init__.py` - Added handle_listen_audio, handle_stop_audio, handle_talk service handlers
- `custom_components/pnzeo_camera/services.yaml` - Added listen_audio, stop_audio, talk service definitions
- `custom_components/pnzeo_camera/strings.json` - Added audio service strings for HA UI

## Decisions Made
- Microphone switch uses coordinator-data-driven state (voice_enable key, default "1" = on) matching PNZEOMotionSwitch pattern for real camera state accuracy
- Talk service accepts base64 PCM and encodes to A-law inline (simple one-shot, no streaming required)
- Audio started/stopped events fired on HA bus to enable automations

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Two-way audio phase complete: protocol layer (05-01) + service layer (05-02) both done
- Ready for Phase 06 (config flow polish)
- Audio functionality testable when camera is connected (listen_audio, stop_audio, talk services available in HA)

## Self-Check: PASSED

All 5 modified files verified present. Both task commits (6695a97, f0ca599) verified in git log. SUMMARY.md exists.

---
*Phase: 05-two-way-audio*
*Completed: 2026-04-02*
