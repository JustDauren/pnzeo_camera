# Phase 5: Two-Way Audio - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped)

<domain>
## Phase Boundary

Listen from camera + talk through camera speaker. Requirements: AUDI-01 (listen via DRW channel 2), AUDI-02 (talk via DRW channel 3), AUDI-03 (microphone switch), AUDI-04 (pure Python G.711 codec), AUDI-05 (audio format auto-detection).

CRITICAL: Audio DRW packet format is INFERRED from JNI signatures, not verified via Wireshark. Audio start/stop commands may use binary protocol messages (not CGI). This is the highest-risk phase.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion. Key technical notes:

- DRW channel routing needed: currently all DRW goes to one _drw_response Event
- CH_AUDIO=2 (receive from camera), CH_TALK=3 (send to camera) — from const.py
- Audio format likely 8kHz mono PCM or A-law (from decompiled app)
- G.711 A-law: 256-entry encode + decode lookup tables (~100 lines)
- Python 3.13 removed audioop — MUST use pure Python lookup tables
- HA has no native two-way audio API — expose as services (pnzeo_camera.listen_audio, pnzeo_camera.talk)
- Microphone on/off: RTSetVoiceEnable via CGI

Research findings suggest audio start/stop may need binary protocol messages:
- RTStartAudio(did, mode) → may send encode_command(MSG_TYPE, params)
- RTStopAudio(did) → may send encode_command(MSG_TYPE)
- RTStartTalk(did) → may need separate binary message
- RTTalkAudioData(did, data, len, type) → DRW channel 3 data

Since we can't Wireshark-capture right now, implement the CGI-based approach first, and fall back to binary protocol if CGI fails.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- pppp_client.py — DRW send/receive infrastructure
- pppp_packets.py — build_drw_packet, parse_drw_response
- const.py — CH_CMD=0, CH_VIDEO=1, CH_AUDIO=2, CH_TALK=3
- switch.py — existing switches for on/off entities

### Key Challenge
- pppp_client.py currently routes ALL DRW packets to single _drw_response Event
- Need channel-based routing: channel 0 → command queue, channel 2 → audio callback
- This is a significant refactor of the receive path

</code_context>

<specifics>
## Specific Ideas

From research: implement audio as service calls, not streaming entities. go2rtc integration would be ideal but is v2 scope.

</specifics>

<deferred>
## Deferred Ideas

- WebRTC integration (v2)
- go2rtc backchannel (v2)
- Audio recording to file (v2)

</deferred>
