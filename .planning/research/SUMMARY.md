# Research Summary: PNZEO Camera Full Feature Parity

**Domain:** IoT IP camera Home Assistant custom component (proprietary PPPP protocol)
**Researched:** 2026-04-02
**Overall confidence:** MEDIUM-HIGH

## Executive Summary

The PNZEO Camera integration already has a solid foundation: working PPPP P2P connection, RTSP video, PTZ control, basic settings, and coordinator-based polling. The path to full feature parity with the MTCam HD Android app is well-defined because the protocol has been reverse-engineered from the decompiled APK (70+ JNI methods documented, DRW channel constants already in const.py).

The expansion splits cleanly into three difficulty tiers. Tier 1 (easy): CGI command expansion for alarm settings, SD card management, WiFi config, FTP/email, IR settings, user management -- these are all variations of the existing `build_cgi_url()` + `_send_cgi()` pattern with new parameters. Tier 2 (moderate): EventEntity for alarm notifications, binary_sensor for motion state, MediaSource for SD card recording browsing, diagnostics sensor entities -- standard HA patterns that need protocol-level data. Tier 3 (hard): Two-way audio over DRW channels 2/3, which requires implementing G.711 codec in pure Python and handling real-time UDP audio streaming.

The zero-external-dependencies constraint is the most impactful technical decision. It rules out using the `g711` pip package (C + numpy), `pydub` (ffmpeg), and any audio processing library. But it is achievable: G.711 A-law is a simple 256-entry lookup table, and the audio data rate (8KB/s at 8kHz mono) is trivial for any CPU. The `audioop` stdlib module was removed in Python 3.13, so pure Python lookup tables are the only viable approach.

Home Assistant's lack of native two-way audio in the camera entity platform means we must expose talk functionality as a custom service (`pnzeo_camera.send_audio` or `pnzeo_camera.talk`) rather than through the standard camera entity. This is the same approach used by Reolink, Ring, and other integrations that support two-way audio -- they all use external tools (go2rtc/WebRTC) rather than the camera entity API.

## Key Findings

**Stack:** No changes to core stack. Pure Python, zero deps, asyncio UDP. Add new HA entity platforms (binary_sensor, event, sensor, text). Implement G.711 A-law as pure Python lookup tables (~100 lines).

**Architecture:** Extend existing DRW protocol handler to route by channel (0=cmd, 1=video, 2=audio, 3=talk). Add ~15 new CGI command methods to PNZEOClient. Add ~20 new entities across 5 new platforms.

**Critical pitfall:** Two-way audio DRW packet format is inferred from JNI signatures but not yet captured via Wireshark. Must verify before implementation. Risk: audio start/stop commands may require binary protocol messages (not CGI), which would need different packet encoding.

## Implications for Roadmap

Based on research, suggested phase structure:

1. **CGI Command Expansion** - Low risk, high value
   - Addresses: Alarm settings, SD card management, WiFi config, IR settings, user management, FTP/email, time sync
   - Avoids: Audio complexity; builds on proven CGI pattern
   - Rationale: Every new CGI command follows the exact same pattern as existing `set_brightness()`. Maximum features with minimum risk.

2. **Event/Sensor Entities** - Standard HA patterns
   - Addresses: Motion detection binary_sensor, alarm EventEntity, SD card status sensors, diagnostics, connection status
   - Avoids: Protocol changes; uses data already available from CGI responses
   - Rationale: These entities consume data that phase 1 CGI commands already fetch. No new protocol work needed.

3. **SD Card MediaSource** - Moderate complexity
   - Addresses: SD card recording browsing, file calendar, download
   - Avoids: Video playback in HA (out of scope)
   - Rationale: Requires implementing MediaSource provider, which is well-documented but involves async browsing of remote file trees.

4. **Two-Way Audio** - Highest complexity, highest uncertainty
   - Addresses: Listen from camera, talk to camera
   - Avoids: Premature audio work before command layer is proven
   - Rationale: Requires new DRW channel handling, G.711 codec, and real-time audio streaming. Must Wireshark-capture the exact audio start/stop DRW packets first. Defer until all CGI-based features are done.

**Phase ordering rationale:**
- Phase 1 before 2: Entities in phase 2 need CGI data from phase 1
- Phase 3 after 2: MediaSource needs file list CGI from phase 1, and sensor infrastructure from phase 2
- Phase 4 last: Highest risk, most protocol uncertainty, and independent of other features

**Research flags for phases:**
- Phase 1: Standard patterns, unlikely to need research (all CGI endpoints documented)
- Phase 2: Standard HA patterns, minimal research needed (EventEntity, binary_sensor well-documented)
- Phase 3: Needs deeper research for MediaSource API (BrowseMediaSource, async_resolve_media implementation)
- Phase 4: NEEDS RESEARCH -- must capture audio DRW packets via Wireshark before implementation

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | No changes needed. Pure Python + HA stdlib. Zero new deps. |
| CGI Commands | HIGH | All endpoints from decompiled APK. Response parsing proven. |
| HA Entity Patterns | HIGH | binary_sensor, event, sensor, text, select, number all well-documented. |
| Alarm System | MEDIUM | CGI endpoints confirmed, but alarm event delivery mechanism untested. Polling works, push (FCM) is uncertain. |
| SD Card Access | MEDIUM | File list CGI confirmed, but response parsing untested. MediaSource API documented but complex. |
| Audio Streaming | MEDIUM | DRW channels 2/3 confirmed from const.py and APK. Audio format (8kHz PCM/A-law) confirmed. But DRW packet format for start/stop commands is inferred, not captured. |
| G.711 Codec | HIGH | ITU-T standard. Pure Python implementation is well-established (pydub, pyVoIP both have reference implementations). |

## Gaps to Address

- **Audio DRW packet format**: Must Wireshark-capture `RTStartAudio` and `RTStartTalk` commands from the Android emulator to verify exact byte sequences
- **SD card file list response**: Need actual `get_record_param.cgi` response from camera to build parser
- **Alarm push mechanism**: `MSG_SET_FCM_PUSH` (97) exists but protocol is undocumented. Can defer (polling is sufficient)
- **WiFi scan results**: `get_wifi_params.cgi` response format needs verification
- **Exact HA minimum version**: Should target HA 2025.1.0+ minimum for EventEntity support, but verify exact version when EventEntity was introduced
