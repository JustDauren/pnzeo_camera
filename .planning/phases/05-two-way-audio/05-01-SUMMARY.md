---
phase: 05-two-way-audio
plan: 01
subsystem: audio
tags: [g711, alaw, codec, pppp, drw, channel-routing, asyncio-queue]

# Dependency graph
requires:
  - phase: 01-connection-reliability
    provides: PPPP client with DRW send/receive and keepalive
provides:
  - Pure Python G.711 A-law codec with lookup tables
  - Per-channel DRW dispatch routing audio vs commands
  - Audio streaming control methods (start/stop/send_talk)
  - Audio format constants and message types
affects: [05-two-way-audio]

# Tech tracking
tech-stack:
  added: []
  patterns: [lookup-table-codec, channel-routed-drw-dispatch, asyncio-queue-backpressure]

key-files:
  created:
    - custom_components/pnzeo_camera/audio_codec.py
  modified:
    - custom_components/pnzeo_camera/pppp_client.py
    - custom_components/pnzeo_camera/const.py

key-decisions:
  - "Encode table built by inverting decode table (binary search for closest) -- guarantees perfect roundtrip consistency"
  - "13-bit A-law linear values left-shifted by 3 to fill 16-bit PCM range"
  - "Audio queue maxsize=50 with drop-oldest backpressure policy"

patterns-established:
  - "Channel routing: DRW data[2] byte determines handler, not a single monolithic path"
  - "Audio queue: asyncio.Queue with put_nowait/get_nowait for real-time backpressure"

requirements-completed: [AUDI-04, AUDI-05]

# Metrics
duration: 5min
completed: 2026-04-02
---

# Phase 05 Plan 01: Audio Codec + Channel Routing Summary

**Pure Python G.711 A-law codec with 256/65536 lookup tables and per-channel DRW dispatch separating audio from CGI commands**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-02T16:51:11Z
- **Completed:** 2026-04-02T16:56:40Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- G.711 A-law codec with precomputed lookup tables (no per-sample arithmetic at runtime)
- DRW channel routing refactor separating CH_CMD (CGI) from CH_AUDIO (streaming) -- fixes Pitfall 2
- Audio streaming control methods (start_audio_stream, stop_audio_stream, send_talk_data)
- Audio format detection from DRW packet headers

## Task Commits

Each task was committed atomically:

1. **Task 1: Create audio_codec.py + audio constants** - `e304668` (feat)
2. **Task 2: Refactor DRW channel routing** - `a758b82` (feat)

## Files Created/Modified
- `audio_codec.py` - Pure Python G.711 A-law encode/decode with 256-entry decode and 65536-entry encode lookup tables, detect_audio_format()
- `pppp_client.py` - Channel-routed DRW dispatch: _handle_drw_data(data, channel) replaces monolithic _handle_drw_response; audio queue, streaming control methods
- `const.py` - Audio format constants (AUDIO_FORMAT_ALAW, MSG_START_AUDIO, AUDIO_FRAME_SIZE, etc.)

## Decisions Made
- Encode table built by inverting decode table via binary search for closest decoded value -- guarantees perfect roundtrip consistency instead of direct algorithm which had precision issues
- 13-bit A-law linear values left-shifted by 3 to produce full 16-bit PCM range (-32256..32256)
- Audio queue uses maxsize=50 with drop-oldest backpressure -- prevents memory growth during audio streaming
- Audio format detection defaults to A-law 8kHz mono when header bytes are out of expected range

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed G.711 A-law encode table algorithm**
- **Found during:** Task 1 (audio_codec.py creation)
- **Issue:** Direct compression algorithm produced incorrect exponent calculation, causing roundtrip error of 1016 for PCM value 1000 (decoded to 2016)
- **Fix:** Replaced direct algorithm with inverse-decode-table approach using binary search for closest decoded value
- **Files modified:** audio_codec.py
- **Verification:** All test vectors pass within G.711 lossy tolerance (5% or 256 absolute)
- **Committed in:** e304668 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Essential bug fix for codec correctness. No scope creep.

## Issues Encountered
- HA module imports prevented direct `from custom_components.pnzeo_camera.audio_codec import ...` testing. Used sys.modules mocking approach consistent with project test pattern (tests/conftest.py).

## User Setup Required

None - no external service configuration required.

## Known Stubs

None - all functions are fully implemented with real logic.

## Next Phase Readiness
- Audio codec ready for Plan 05-02 (HA TwoWayAudio provider + camera entity integration)
- Channel routing infrastructure in place -- audio packets will flow to _audio_queue
- start_audio_stream/stop_audio_stream/send_talk_data methods ready for provider to call

## Self-Check: PASSED

All files exist. All commits verified.

---
*Phase: 05-two-way-audio*
*Completed: 2026-04-02*
