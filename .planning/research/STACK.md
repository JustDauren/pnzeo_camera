# Technology Stack

**Project:** PNZEO Camera Full Feature Parity
**Researched:** 2026-04-02
**Mode:** Ecosystem research for milestone: full feature parity

## Executive Summary

The existing stack is solid and requires no fundamental changes. The integration already has a working pure-Python PPPP protocol implementation, coordinator-based polling, and a clean entity hierarchy. Expanding to full feature parity (two-way audio, alarms, SD card, settings) means extending the existing protocol layer and adding new HA entity platforms -- not replacing anything.

The biggest technical challenge is two-way audio. Home Assistant has no native two-way audio support in the camera entity platform. The camera entity only supports `CameraEntityFeature.ON_OFF` and `CameraEntityFeature.STREAM` -- no audio backchannel. The proven community approach is go2rtc with WebRTC, but that requires an external binary. For this proprietary PPPP protocol, we must implement audio streaming at the protocol level using DRW channels 2 (audio receive) and 3 (talk/send), which the decompiled APK confirms exist.

## Recommended Stack

### Core Framework (unchanged)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python | >=3.13 | Runtime | HA 2026.x requires Python 3.13+. Current manifest says 2024.1.0 minimum -- update to 2025.1.0 minimum. No external C deps needed. |
| Home Assistant Framework | 2025.1.0+ | Entity management, coordinator, config flow | Already in use. Update minimum version to gain EventEntity, improved diagnostics |
| asyncio (stdlib) | n/a | Async UDP transport, task management | Already in use for PPPP. UDP DatagramProtocol is the right abstraction for DRW channels |
| struct (stdlib) | n/a | Binary packet encoding/decoding | Already in use. Sufficient for all PPPP packet types |
| voluptuous | bundled | Config/service schema validation | Already in use. No version pin needed (HA bundles it) |

**Confidence:** HIGH -- verified from existing codebase and HA developer docs.

### New HA Platforms Required

| Platform | Purpose | Why This Platform |
|----------|---------|-------------------|
| `binary_sensor` | Motion detection state, sound detection, SD card presence, connection status | Standard HA pattern for on/off state sensors. Motion detection maps to `BinarySensorDeviceClass.MOTION`. Camera already fires CGI alarm events -- expose them as binary_sensor state. |
| `event` | Alarm event notifications (motion triggered, GPIO, sound) | `EventEntity` with `EventDeviceClass.MOTION` is the 2025+ HA pattern for stateless event firing. Use `_trigger_event()` to fire events that users can trigger automations from. Better than `hass.bus.async_fire()` because events are tied to the device in the UI. |
| `sensor` | SD card capacity (total/used/free), firmware version, device name, WiFi signal | Standard HA pattern for read-only values. Use `entity_category: EntityCategory.DIAGNOSTIC` for firmware/device info sensors. |
| `text` | FTP server address, email recipient, WiFi SSID, device name | `TextEntity` for free-form string input. Better than `input_text` because it is device-bound. |

**Confidence:** HIGH -- verified from HA developer documentation at developers.home-assistant.io.

### Protocol Layer Extensions

| Component | Purpose | Implementation Approach |
|-----------|---------|------------------------|
| Multi-channel DRW | Audio receive (CH 2), talk send (CH 3) | Extend `_PNZEOProtocol.datagram_received()` to dispatch by DRW channel byte. Currently only handles CH 0 (command). Add channel routing: `{0: cmd, 1: video, 2: audio_rx, 3: audio_tx}`. Constants already exist in `const.py`: `CH_CMD=0, CH_VIDEO=1, CH_AUDIO=2, CH_TALK=3`. |
| Audio codec | G.711 A-law or PCM 16-bit 8kHz encoding/decoding | Pure Python implementation. The decompiled `CustomAudioRecorder.java` confirms 8000 Hz, mono, 16-bit PCM (Android `ENCODING_PCM_16BIT`). The `RTAudioType` enum shows: `PCM=0, AAC=1, OTHER=2`. Implement G.711 A-law encode/decode as ~50 lines of pure Python lookup tables (no numpy, no C). Do NOT use the `audioop` stdlib module -- it was removed in Python 3.13. Do NOT use the `g711` pip package -- it requires numpy and C compilation, violating the zero-deps constraint. |
| CGI command expansion | set_alarm.cgi, get_alarm.cgi, set_ftp.cgi, set_mail.cgi, set_record_param.cgi, get_wifi_params.cgi, set_wifi.cgi, get_sd_card_params.cgi | Extend `build_cgi_url()` calls in `pppp_client.py`. The CGI constants already exist in `pppp_packets.py` (`CGI_GET_ALARM`, `CGI_SET_ALARM`, `CGI_GET_WIFI`, etc.). Each new command is just a new method like existing `set_brightness()`. |
| Alarm polling / push | Periodic alarm status polling OR alarm event listener on DRW | Two approaches: (1) Poll `get_alarm.cgi` every 60s via coordinator -- simple, already works with existing pattern. (2) Register for push via `MSG_SET_FCM_PUSH` (97) and handle incoming alarm DRW packets on channel 0 -- more complex, lower latency. Start with approach 1. |

**Confidence:** HIGH for CGI commands (verified from decompiled APK and existing code), MEDIUM for audio (protocol reverse-engineered but not yet tested in Python).

### Audio Implementation Strategy

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| Audio receive from camera | DRW channel 2, decode A-law/PCM, expose as audio stream | Camera sends audio on CH_AUDIO (2). The `RTStartAudio(did, mode)` JNI call starts audio streaming. We need to send the equivalent DRW command to start audio and then handle incoming audio packets on channel 2. |
| Audio send to camera (talk) | DRW channel 3, encode PCM to A-law, send as DRW | `RTStartTalk(did)` starts talk mode. `RTTalkAudioData(did, data, len, type)` sends audio data. Type 0 = PCM, type 1 = AAC. Send raw PCM 8kHz 16-bit mono in 1028-byte DRW payloads on CH_TALK (3). |
| HA integration approach | Separate TTS/media service, NOT camera entity two-way audio | HA camera entity has no two-way audio API. Implement `pnzeo_camera.play_audio` service that accepts media content or TTS output and streams it to camera via DRW channel 3. For listening, consider a media_player entity with `SUPPORT_PLAY_MEDIA` that proxies the audio stream. |
| G.711 codec | Pure Python lookup table implementation | 256-entry A-law encode + 256-entry decode tables. ~100 lines. No external deps. Performance: 8000 samples/sec * 1 byte = 8KB/s -- trivial for any CPU. |

**Confidence:** MEDIUM -- audio channel architecture is confirmed from decompiled APK, but exact DRW packet format for audio start/stop commands needs verification via Wireshark capture.

### SD Card File Access

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| File listing | CGI `get_record_param.cgi` + MSG_GET_RECORD_FILE (23) | JNI method: `RTGetSDCardRecordFileList(did, startDate, endDate, type, startIdx, count)`. Returns paginated file list. Implement as sensor attributes or MediaSource. |
| Calendar view | MSG_GET_REC_CALENDAR (83) | `RTGetSDRecordCalendar(did, month)` returns bitmask of days with recordings. Expose as sensor attribute with JSON calendar data. |
| File playback | NOT in scope for HA | `RTStartPlayBack(did, file, mode)` streams via PPPP. HA has no custom media player that can render proprietary protocol video. Listing files is feasible; playing them in HA dashboard is not. |
| MediaSource integration | Implement for file listing and download | Inherit from `MediaSource`, implement `async_browse_media()` and `async_resolve_media()`. List recordings by date. For actual playback, provide download URL via HA's media serving infrastructure. This is how Reolink does it. |
| SD card status | Sensor entity (total/used/free capacity) | Poll `get_status.cgi` which returns SD card info. Create diagnostic sensor entities. |

**Confidence:** MEDIUM -- CGI endpoints confirmed from APK decompilation, but response parsing needs Wireshark capture verification.

### Alarm and Event System

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| Motion detection binary_sensor | `binary_sensor` with `BinarySensorDeviceClass.MOTION` | Poll alarm status via `get_alarm.cgi` every coordinator cycle (60s). Set binary_sensor state based on `motion_armed` + `motion_detected` response fields. |
| Alarm settings | Switch + Number + Select entities | `set_alarm.cgi` parameters: `motion_armed` (switch), `motion_sensitivity` (select: high/medium/low/ultra-low), `input_armed` (switch), `mail` notification (switch), `upload_interval` (number). Full 33-param `RTAlarmSetting` exposed progressively. |
| Event notifications | `EventEntity` with `EventDeviceClass.MOTION` | Define event_types: `["motion", "sound", "gpio", "smoke"]`. Call `self._trigger_event("motion", {"sensitivity": ..., "area": ...})` when alarm fires. This creates automatable events in HA UI. |
| Alarm push (optional, deferred) | MSG_SET_FCM_PUSH (97) registration | Camera can push alarm events via FCM. Would require receiving push server role. Complex, defer to later. |

**Confidence:** HIGH for binary_sensor/switch/event patterns (standard HA). MEDIUM for alarm CGI parameter mapping (needs testing).

### WiFi and Network Configuration

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| WiFi scan | Button entity + sensor entity | `RTWifiSetting` with scan params. Button triggers scan, sensor shows results as attribute list. |
| WiFi configuration | Text + Select entities | `set_wifi.cgi` with SSID, password, security type. Use text entity for SSID/password, select for encryption type. |
| Network settings | Text entities with `entity_category: config` | `set_network.cgi` for IP, mask, gateway, DNS. Mark as config category so they don't pollute dashboards. |

**Confidence:** MEDIUM -- CGI endpoints exist but parameter format needs verification.

### User Management

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| 3 user slots | Service call, NOT entities | `RTUserSetting(did, u1, p1, u2, p2, u3, p3)` sets all 3 slots atomically. Too complex for individual entities. Implement as `pnzeo_camera.set_users` service with schema validation. Current `change_password` already works this way. |
| User info display | Diagnostic sensor | `get_user_params.cgi` response as sensor attribute. `entity_category: diagnostic`. |

**Confidence:** HIGH -- `change_password` already implemented via this mechanism.

### FTP / Email Settings

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| FTP settings | Text + Number + Select entities | `set_ftp.cgi` params: `svr` (text), `port` (number), `user` (text), `pwd` (text), `mode` (select: passive/active), `dir` (text), `upload_interval` (number). Group under `entity_category: config`. |
| Email/SMTP settings | Text + Number + Switch entities | `set_mail.cgi` params: `svr` (text), `port` (number), `user` (text), `pwd` (text), `sender` (text), `receiver1-4` (text), `mail_inet_ip` (switch). |
| Approach | Progressive disclosure | Don't create 15+ entities at once. Use HA's options flow to let user enable FTP/email config sections. Only create entities when user opts in. |

**Confidence:** HIGH for entity pattern, MEDIUM for exact CGI parameters.

## What NOT to Use (and Why)

| Technology | Why Not |
|------------|---------|
| `audioop` (Python stdlib) | **Removed in Python 3.13.** HA 2025.x requires Python 3.13+. Cannot use for G.711 encoding. |
| `g711` pip package | Requires numpy + C compilation. Violates `requirements: []` (zero external deps) constraint. Would fail on some HA installations. |
| `pydub` | Audio processing library. Overkill. Requires ffmpeg. We only need G.711 lookup tables. |
| `go2rtc` for two-way audio | External binary. Not suitable for a pure-Python HA custom component. Good for users who install separately, but we cannot depend on it. |
| WebRTC native | HA's WebRTC support is for video streaming only. No API for custom protocol audio backchannel. |
| `aiopppp` library | Different PPPP variant (X5/A9 cameras, JSON/Binary protocol). PNZEO uses CGI-over-DRW in libRtMain.so variant. Incompatible at the command layer. |
| `pppp_camera` HA component | Based on `aiopppp`. Different protocol variant. Cannot reuse. |
| MQTT for events | Would require an MQTT broker. The camera doesn't speak MQTT. Polling via coordinator is simpler and sufficient. |
| FFmpeg for audio | HA uses ffmpeg for RTSP video. Audio over PPPP is a separate channel (DRW CH 2/3), not RTSP. ffmpeg cannot help here. |
| `homeassistant.components.stream` | HA's stream component is for RTSP/HLS video. Our audio is proprietary UDP. Not compatible. |
| External HTTP API | Camera has NO HTTP/CGI server. All commands go through PPPP DRW packets. Do not try to access camera on port 80/8080 -- they are closed. |

**Confidence:** HIGH -- verified from codebase analysis, protocol documentation, and HA developer docs.

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Audio codec | Pure Python G.711 tables | `audioop` module | Removed in Python 3.13. HA requires 3.13+. |
| Audio codec | Pure Python G.711 tables | `g711` pip package | C extension + numpy dependency. Violates zero-deps. |
| Alarm events | EventEntity + binary_sensor | hass.bus.async_fire | EventEntity ties events to device in UI. bus.fire is anonymous. |
| SD card browse | MediaSource integration | Custom Lovelace card | MediaSource is the standard HA pattern. Works with existing Media Browser. |
| Config settings UI | Options flow + entity categories | Lovelace cards | Options flow is the HA-native way. No custom frontend needed. |
| Audio streaming | DRW channel 2/3 in protocol layer | go2rtc exec source | go2rtc is external binary. Custom component cannot depend on it. |
| Alarm delivery | Coordinator polling (60s) | FCM push registration | Push requires acting as push server. Polling is simple, reliable, already implemented. 60s is fine for home security -- not a bank vault. |

## Pure Python G.711 A-law Codec Reference

Since `audioop` is gone and we cannot use external deps, here is the verified approach. This is what pydub and pyVoIP did when audioop was removed:

```python
# G.711 A-law encode/decode lookup tables
# Input: 16-bit signed PCM samples at 8kHz mono
# Output: 8-bit A-law encoded bytes (and reverse)
# ~100 lines of pure Python, zero dependencies
# Performance: 8000 samples/sec = 8KB/s -- trivial

# Encode: PCM 16-bit -> A-law 8-bit
def pcm_to_alaw(pcm_sample: int) -> int:
    """Convert 16-bit signed PCM to A-law byte."""
    # Standard ITU-T G.711 algorithm
    # ...lookup table or algorithmic implementation...

# Decode: A-law 8-bit -> PCM 16-bit
def alaw_to_pcm(alaw_byte: int) -> int:
    """Convert A-law byte to 16-bit signed PCM."""
    # Reverse lookup
    # ...
```

**Confidence:** HIGH -- G.711 A-law algorithm is a public ITU-T standard. Pure Python implementations exist in pydub, pyVoIP, and multiple GitHub repos.

## HA Entity Platform Summary

| Entity Type | Count (approx) | Features |
|-------------|----------------|----------|
| camera | 1 (existing) | RTSP stream, snapshot, motion detection enable/disable |
| switch | 6-8 | Motion detection, sound detection, recording, IR LED, status LED, FTP upload, email notifications |
| button | 3-4 (existing: reboot, factory reset, format SD; new: unmount SD, WiFi scan) | One-shot actions |
| number | 5-6 | Brightness, contrast (existing); upload interval, alarm sensitivity (if numeric), FTP port |
| select | 3-4 | Resolution, mirror (existing); motion sensitivity (high/med/low), recording mode, IR mode |
| binary_sensor | 3-4 | Motion detected, SD card present, connection status, sound detected |
| sensor | 4-5 | SD card capacity, firmware version, device name, WiFi signal |
| event | 1-2 | Motion alarm events, sound alarm events |
| text | 5-8 | FTP server/user/dir, email server/sender/recipients, WiFi SSID (only if user enables FTP/email config) |

**Total new entities:** ~20-25 (progressive, not all at once)

## Installation

```bash
# No installation required -- zero external dependencies
# manifest.json: "requirements": []
# All pure Python stdlib: asyncio, struct, socket, json, logging, enum, urllib.parse
```

## Manifest Update Recommendation

```json
{
  "domain": "pnzeo_camera",
  "name": "PNZEO Camera",
  "codeowners": ["@daurentakibaev"],
  "config_flow": true,
  "documentation": "https://github.com/daurentakibaev/pnzeo_camera",
  "integration_type": "device",
  "iot_class": "local_polling",
  "issue_tracker": "https://github.com/daurentakibaev/pnzeo_camera/issues",
  "requirements": [],
  "version": "2.0.0"
}
```

Note: Keep `iot_class: "local_polling"` even though alarm events might eventually be push-based. The primary data path is still coordinator polling.

## Sources

### HIGH Confidence (official docs, primary sources)
- [HA Camera Entity Developer Docs](https://developers.home-assistant.io/docs/core/entity/camera/) -- CameraEntityFeature flags, method signatures
- [HA Event Entity Developer Docs](https://developers.home-assistant.io/docs/core/entity/event/) -- EventEntity API, EventDeviceClass, _trigger_event
- [HA Events Developer Docs](https://developers.home-assistant.io/docs/dev_101_events/) -- hass.bus.fire, event naming
- [HA Fetching Data Developer Docs](https://developers.home-assistant.io/docs/integration_fetching_data/) -- DataUpdateCoordinator patterns
- [HA Integration Diagnostics](https://developers.home-assistant.io/docs/core/integration_diagnostics/) -- async_get_config_entry_diagnostics
- [HA Entity Developer Docs](https://developers.home-assistant.io/docs/core/entity/) -- entity_category, device_info, naming
- Decompiled MTCam HD APK (`com.rt.mtcamhd`) -- RTNativeCaller.java, RTAudioType.java, CustomAudioRecorder.java
- Project protocol docs: PPPP_PROTOCOL.md, PNZEO_W8_REVERSE.md
- Existing codebase: const.py (CH_CMD/CH_VIDEO/CH_AUDIO/CH_TALK constants)

### MEDIUM Confidence (verified with multiple sources)
- [PPPP Protocol Overview](https://palant.info/2025/11/05/an-overview-of-the-pppp-protocol-for-iot-cameras/) -- DRW channel structure, protocol layers
- [cam-reverse GitHub](https://github.com/DavidVentura/cam-reverse) -- DRW audio magic bytes, A-law PCM at 8kHz
- [aiopppp GitHub](https://github.com/devbis/aiopppp) -- Alternative PPPP implementation (different variant)
- [IP Camera CGI SDK v2.1](https://corz.org/windows/software/oodlecam/files/IP%20Camera%20SDK%20Commands%20v2.1.html) -- set_alarm.cgi, set_ftp.cgi parameters
- [g711 Python library](https://github.com/stolpa4/g711) -- G.711 codec reference (NOT recommended for use)
- [audioop removal Python 3.13](https://docs.python.org/3/library/audioop.html) -- Confirmed removal, alternatives

### LOW Confidence (needs validation)
- Exact DRW packet format for audio start/stop commands -- inferred from JNI signatures, not captured
- SD card file list response format -- CGI endpoint confirmed, but response parsing untested
- Alarm push via FCM mechanism -- `MSG_SET_FCM_PUSH` (97) exists in const.py but protocol unknown
- WiFi scan result format -- endpoint exists, response structure undocumented
