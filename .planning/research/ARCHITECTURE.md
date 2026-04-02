# Architecture Patterns

**Domain:** P2P camera Home Assistant integration (PPPP/CS2 protocol)
**Researched:** 2026-04-02

## Recommended Architecture

The current 3-layer architecture (Protocol -> Device -> HA entities) with a 60s polling coordinator is solid for camera settings and control. The new features -- alarm events, audio streaming, SD card browsing -- each demand a distinct communication pattern that does not fit cleanly into the polling model. The architecture must evolve from "poll-only" to "poll + push + streaming" while preserving the existing working behavior.

### Target Architecture: Event-Driven Core with Polling Fallback

```
                    +-------------------+
                    |   Home Assistant   |
                    |    Event Bus       |
                    +--------+----------+
                             |
              +--------------+--------------+
              |              |              |
      +-------+------+ +----+----+ +-------+------+
      | binary_sensor | | camera  | | media_source |
      | (motion/alarm)| | (video) | | (SD card)    |
      +--------------+ +---------+ +--------------+
              |              |              |
      +-------+--------------+--------------+-------+
      |             PNZEOCoordinator                 |
      |  (polls 60s + dispatches pushed events)      |
      +----------------------------------------------+
              |
      +-------+-------+
      |  PNZEODevice   |
      +-------+--------+
              |
      +-------+----------------------------------+
      |         PNZEOClient (protocol layer)      |
      |                                           |
      |  CH_CMD(0)  CH_VIDEO(1) CH_AUDIO(2) CH_TALK(3)
      |  [CGI cmds] [not used]  [ADPCM in] [ADPCM out]
      |                                           |
      |  Channel Router: datagram_received()      |
      |    -> CH_CMD responses -> _drw_response    |
      |    -> CH_AUDIO data   -> audio_callback    |
      |    -> alarm push      -> event_callback    |
      +-------------------------------------------+
              |
        UDP Socket (single)
              |
        PNZEO Camera
```

### Component Boundaries

| Component | Responsibility | Communicates With | New in This Milestone |
|-----------|---------------|-------------------|----------------------|
| `PNZEOClient` | PPPP protocol, UDP transport, DRW encoding, channel routing | Camera (UDP), PNZEODevice | Channel-aware datagram handler, alarm event detection, audio rx/tx |
| `PNZEODevice` | Credentials, RTSP URLs, device metadata | PNZEOClient, PNZEOCoordinator | Audio stream URLs (if PPPP audio used) |
| `PNZEOCoordinator` | 60s polling, state management, event dispatching | PNZEODevice, all entities | Event callback dispatch, alarm state tracking |
| `camera.py` | Video entity, RTSP stream | HA stream component | No change (video stays RTSP) |
| `binary_sensor.py` | Motion/alarm/sound detection state | Coordinator events | **New** - alarm push binary sensors |
| `media_source.py` | SD card recording browser | Coordinator, PNZEOClient | **New** - BrowseMediaSource implementation |
| `sensor.py` | SD card capacity, device info | Coordinator polling | **New** - SD capacity/firmware sensors |
| `siren.py` or `switch.py` | Alarm siren on/off | PNZEOClient CGI | **New** - alarm output control |

### Data Flow

**1. Settings Poll (existing, unchanged):**
```
Every 60s:
  Coordinator -> client.get_status() -> DRW CH_CMD -> camera
  Coordinator -> client.get_camera_params() -> DRW CH_CMD -> camera
  Camera -> DRW CH_CMD response -> client._camera_params
  Coordinator -> entities read coordinator.data
```

**2. Alarm Event Push (new, event-driven):**
```
Camera detects motion:
  Camera -> DRW packet on CH_CMD -> client.datagram_received()
  _PNZEOProtocol parses channel + payload
  If alarm indicator detected -> client._alarm_callback(alarm_type, timestamp)
  Coordinator receives callback -> updates alarm state
  Coordinator -> async_set_updated_data() or hass.bus.async_fire()
  binary_sensor.motion picks up state change -> turns ON
  After configurable timeout (default 30s) -> turns OFF
```

**3. Audio Listen (new, streaming):**
```
User requests audio:
  client.start_audio_stream() -> sends audio start CGI on CH_CMD
  Camera begins sending ADPCM frames on CH_AUDIO (channel 2)
  _PNZEOProtocol routes CH_AUDIO to audio buffer
  Audio decoder (ADPCM -> PCM) runs in asyncio
  PCM data -> either go2rtc pipe or direct WebRTC offer
```

**4. Two-Way Talk (new, streaming):**
```
User speaks:
  Browser captures mic via WebRTC
  PCM -> ADPCM encoder
  client.send_audio(adpcm_frame) -> DRW CH_TALK (channel 3) -> camera
  Camera plays audio on speaker
```

**5. SD Card Browse (new, on-demand):**
```
User opens Media Browser:
  HA calls media_source.async_browse_media(identifier)
  If root -> return camera entry
  If camera -> client.get_record_calendar() -> DRW CH_CMD
  Camera returns dates with recordings
  If date selected -> client.get_record_files(date) -> DRW CH_CMD
  Camera returns file list
  If file selected -> async_resolve_media() -> proxy stream URL
  File download: client.get_record_file(filename) via DRW CH_CMD
  -> large DRW response, needs packet reassembly
```

## Patterns to Follow

### Pattern 1: Channel Router in Protocol Handler

**What:** Route incoming DRW packets by channel ID to different handlers instead of treating all responses as CGI.

**When:** Always -- this is the foundation for concurrent operations.

**Why:** Currently `datagram_received()` dumps ALL DRW data into `_drw_response`. This blocks concurrent operations. A channel router allows command responses, audio streams, and alarm events to flow independently.

**Example:**
```python
class _PNZEOProtocol(asyncio.DatagramProtocol):
    def datagram_received(self, data: bytes, addr: tuple) -> None:
        if len(data) < 2 or data[0] != 0xF1:
            return

        pkt_type = data[1]

        if pkt_type == PktType.DRW:
            parsed = parse_drw_packet(data)
            if parsed is None:
                return
            channel, index, payload = parsed

            if channel == CH_CMD:
                self.client._handle_cmd_response(index, payload)
            elif channel == CH_AUDIO:
                self.client._handle_audio_data(index, payload)
            elif channel == CH_VIDEO:
                self.client._handle_video_data(index, payload)
            elif channel == CH_TALK:
                pass  # outbound only, ignore inbound
        elif pkt_type in (PktType.PUNCH_PKT, PktType.P2P_RDY, ...):
            # existing handshake handling
            ...
```

**Confidence:** HIGH -- channel IDs 0-3 are already defined in `const.py` and the protocol spec confirms this pattern.

### Pattern 2: Async Event Callback for Alarms

**What:** Camera pushes alarm events as unsolicited DRW packets on CH_CMD. Detect these by MSG_TYPE and fire HA events.

**When:** Camera has motion/sound detection enabled and detects an event.

**Why:** The Reolink integration uses a similar hierarchy: TCP push > ONVIF push > long polling > fast polling. Our equivalent is "DRW push" (if camera sends unsolicited alarm packets) with "CGI polling" as fallback.

**Implementation approach:**
```python
# In coordinator
def _on_alarm_event(self, alarm_type: int, data: dict) -> None:
    """Called by client when alarm DRW arrives."""
    self._alarm_states[alarm_type] = True
    self._alarm_timestamps[alarm_type] = time.time()
    self.async_set_updated_data(self.data)
    self.hass.bus.async_fire(
        f"{DOMAIN}_alarm",
        {"device_id": self.device.unique_id, "type": alarm_type, **data}
    )
    # Schedule auto-clear after timeout
    self.hass.loop.call_later(
        self._alarm_timeout,
        self._clear_alarm, alarm_type
    )
```

**Confidence:** MEDIUM -- the protocol supports unsolicited DRW packets on any channel. Whether the PNZEO W8 firmware actually pushes alarm events without being asked, or only supports poll-based `get_alarm.cgi`, needs live testing. The MTCam app registers for FCM push (MSG_SET_FCM_PUSH = 97), suggesting the camera may only push via cloud FCM, not local DRW. Fallback: poll alarm status every 5-10 seconds.

### Pattern 3: MediaSource for SD Card Recordings

**What:** Implement `MediaSource` subclass with hierarchical browse: Camera -> Date -> Recording.

**When:** User opens Media Browser in HA sidebar.

**Why:** This is the established HA pattern. Reolink and Tapo integrations both use this approach. The camera exposes `get_record.cgi` (MSG_GET_RECORD) and `get_record_calendar.cgi` (MSG_GET_REC_CALENDAR) CGI endpoints.

**Implementation:**
```python
class PNZEOMediaSource(MediaSource):
    name = "PNZEO Camera"

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        if item.identifier is None:
            return self._build_root()  # list cameras
        parts = item.identifier.split("/")
        if len(parts) == 1:
            return await self._build_calendar(parts[0])  # dates
        if len(parts) == 2:
            return await self._build_day(parts[0], parts[1])  # files
        raise BrowseError("Unknown identifier")

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        # Download recording via DRW, serve from local cache
        entry_id, date, filename = item.identifier.split("/")
        path = await self._download_recording(entry_id, date, filename)
        return PlayMedia(f"/local/pnzeo/{entry_id}/{filename}", "video/mp4")
```

**Confidence:** HIGH -- HA MediaSource API is stable and well-documented. The camera has get_record CGI commands.

### Pattern 4: Audio via go2rtc Pipe (Not Direct WebRTC)

**What:** Pipe PPPP audio to go2rtc as an exec source rather than implementing WebRTC directly.

**When:** User wants to hear camera audio in HA dashboard.

**Why:** Implementing WebRTC natively (async_handle_async_webrtc_offer) requires STUN/TURN handling and complex SDP negotiation. The simpler and more robust approach: pipe ADPCM audio through go2rtc which handles all WebRTC complexity. go2rtc is built into HA since 2024.11.

**How it works:**
```
PPPP CH_AUDIO -> ADPCM decode -> PCM pipe -> go2rtc exec source -> WebRTC to browser
```

**Alternative (simpler, less elegant):** Decode ADPCM to PCM, write to a named pipe or file, expose as a secondary RTSP-like stream URL. Let HA's stream component handle it.

**Confidence:** MEDIUM -- go2rtc exec source pattern works, but ADPCM-to-PCM decoding at 11.025 kHz in pure Python may have latency. The `audioop` stdlib module handles ADPCM but was removed in Python 3.13. Need to verify HA's Python version and find alternative decoder.

### Pattern 5: DRW Packet Reassembly

**What:** Reassemble large DRW responses that span multiple consecutive packets (frames > 1024 bytes).

**When:** SD card file listings, large capability responses, recording downloads.

**Why:** Current implementation reads only the first DRW packet. The protocol splits payloads > 1024 bytes across consecutive packets, where only the first has the header. Without reassembly, SD card file lists and recording data will be truncated.

**Implementation:**
```python
class DRWReassembler:
    """Reassemble multi-packet DRW responses by index sequence."""

    def __init__(self):
        self._buffers: dict[int, bytearray] = {}  # channel -> buffer
        self._expected_size: dict[int, int] = {}

    def feed(self, channel: int, index: int, payload: bytes) -> bytes | None:
        if index == 0 or channel not in self._buffers:
            # First packet: extract expected size from header
            self._buffers[channel] = bytearray(payload)
            self._expected_size[channel] = self._parse_expected_size(payload)
        else:
            self._buffers[channel].extend(payload)

        if len(self._buffers[channel]) >= self._expected_size.get(channel, 0):
            result = bytes(self._buffers.pop(channel))
            self._expected_size.pop(channel, None)
            return result
        return None  # still accumulating
```

**Confidence:** HIGH -- the PPPP spec explicitly documents this splitting behavior. Current code already handles index in parse_drw_packet but discards continuation packets.

## Anti-Patterns to Avoid

### Anti-Pattern 1: Polling for Alarm State

**What:** Using the 60s coordinator poll to check alarm status.

**Why bad:** 60 seconds is far too slow for motion detection. Even 5-second polling is wasteful if the camera pushes events. However, polling should remain as a FALLBACK, not the primary mechanism.

**Instead:** Implement DRW push detection first. If live testing reveals the camera does not push alarm events, add a separate alarm polling loop at 5-10 second intervals (independent of the 60s coordinator). Never merge alarm polling into the main coordinator cycle.

### Anti-Pattern 2: Direct WebRTC Implementation

**What:** Implementing `async_handle_async_webrtc_offer` with full SDP/ICE handling in the integration.

**Why bad:** Massive complexity. SDP parsing, STUN binding, ICE candidate gathering, DTLS-SRTP -- all for audio-only. The integration would become fragile and hard to maintain.

**Instead:** Pipe audio to go2rtc. Let go2rtc handle WebRTC. The integration just provides the decoded PCM stream.

### Anti-Pattern 3: Downloading Full Recordings to Serve via MediaSource

**What:** Downloading entire video files from SD card to HA local storage before playback.

**Why bad:** SD card recordings can be large (hundreds of MB). Downloading via DRW over UDP is slow (1024-byte packets). Users would wait minutes before playback starts.

**Instead:** Provide the RTSP URL to the recording if the camera supports RTSP playback of stored files. Many MTCam cameras serve recordings on RTSP paths like `/record/YYYYMMDD/HHMMSS.264`. If not available, use chunked download with streaming playback (start playing while still downloading).

### Anti-Pattern 4: Single asyncio.Event for All Responses

**What:** Using one `_drw_response` Event for all DRW data (current implementation).

**Why bad:** When multiple operations are concurrent (polling status + receiving alarm event + streaming audio), all share one signal. A status response could be consumed by the alarm handler. Audio data could trigger the CGI response waiter.

**Instead:** Use per-channel or per-sequence response tracking:
```python
self._pending_commands: dict[int, asyncio.Future] = {}  # seq -> future
```

### Anti-Pattern 5: Blocking Socket in Async Code

**What:** The current `_cloud_discover_port()` uses synchronous `socket.socket` with `recvfrom()` in async context.

**Why bad:** Blocks the event loop for up to 3 seconds per server. Other async operations stall.

**Instead:** Use `loop.create_datagram_endpoint()` for cloud discovery too, or wrap in `loop.run_in_executor()`.

## Scalability Considerations

| Concern | Current (1 camera, control only) | After milestone (1 camera, full features) | Future (N cameras) |
|---------|----------------------------------|-------------------------------------------|---------------------|
| UDP socket count | 1 per camera | 1 per camera (channels multiplex) | N sockets |
| Event loop load | Minimal (60s poll) | Moderate (audio stream + alarm listener) | High if audio active on multiple |
| Memory | ~10KB camera_params | +buffer for audio, +cache for SD listings | Needs per-camera limits |
| DRW packet rate | ~2 per 60s cycle | ~50/s during audio stream | Must rate-limit per camera |
| Reconnection | Simple reconnect on poll fail | Must preserve alarm subscription on reconnect | Connection pool manager |

## Build Order (Dependencies)

The features must be built in this order due to protocol-level dependencies:

**Phase 1: Channel Router (Foundation)**
- Refactor `_PNZEOProtocol.datagram_received()` to route by channel ID
- Implement per-sequence response tracking (replace single `_drw_response` Event)
- Implement DRW packet reassembly for multi-packet responses
- **Why first:** Every other feature depends on channel-aware routing. Without it, concurrent operations corrupt each other.

**Phase 2: Alarm Events**
- Add `binary_sensor.py` platform with motion/sound/GPIO detection
- Implement alarm event detection in channel router (CH_CMD unsolicited packets)
- Add alarm polling fallback (5-10s interval) if push is unavailable
- Add alarm configuration entities (sensitivity, zone, schedule)
- **Why second:** Highest user value. Requires channel router but no streaming. Alarm configuration is CGI-only (simpler).

**Phase 3: SD Card Management**
- Implement `media_source.py` with BrowseMediaSource
- Add SD card status sensor (capacity, used, available)
- Add format/unmount buttons
- Add recording settings (mode, schedule)
- Requires DRW reassembly for large file listings
- **Why third:** Requires packet reassembly from Phase 1. Pure CGI commands, no streaming complexity.

**Phase 4: Audio Streaming**
- Implement audio receive on CH_AUDIO (ADPCM decode)
- Implement audio send on CH_TALK (PCM -> ADPCM encode)
- Integrate with go2rtc or expose as stream
- **Why last:** Highest complexity. Needs channel router, reassembly, streaming buffer management, codec handling. Can be cut from MVP if needed without losing other features.

**Phase 5 (optional): WiFi Configuration**
- WiFi scan and setup via CGI
- Network settings
- **Why optional:** Pure CGI, no protocol changes needed. Can be done any time after Phase 1.

## Protocol Constraints (PPPP-Specific)

| Constraint | Impact | Mitigation |
|------------|--------|------------|
| DRW packets max 1024 bytes payload | Large responses split across packets | Implement reassembly buffer |
| Single UDP socket per connection | All channels share bandwidth | Priority: keepalive > commands > audio |
| No built-in flow control | Camera can flood audio packets | Client-side buffer with drop-oldest |
| ADPCM codec at 11.025 kHz | Low quality audio, but low bandwidth | Acceptable for surveillance |
| Keepalive every 3s required | Connection drops without it | Keepalive must survive during audio streaming |
| No TLS/encryption | All data in plaintext on LAN | Acceptable for LAN-only; document security posture |
| Camera may not push alarm events | Primary event detection method uncertain | Must test with real hardware; prepare polling fallback |

## Sources

- [PPPP Protocol Overview (Palant, Nov 2025)](https://palant.info/2025/11/05/an-overview-of-the-pppp-protocol-for-iot-cameras/) - HIGH confidence, protocol spec details
- [PPPP Dissector Protocol Doc](https://github.com/magicus/pppp-dissector/blob/main/PPPP.md) - HIGH confidence, channel IDs and frame format
- [Reolink HA Integration Docs](https://www.home-assistant.io/integrations/reolink/) - HIGH confidence, event detection hierarchy (TCP push > ONVIF > polling)
- [ONVIF HA Integration](https://www.home-assistant.io/integrations/onvif/) - HIGH confidence, pullpoint subscription pattern
- [HA Camera Entity Developer Docs](https://developers.home-assistant.io/docs/core/entity/camera/) - HIGH confidence, CameraEntityFeature, WebRTC methods
- [Tapo Control Media Management (DeepWiki)](https://deepwiki.com/JurajNyiri/HomeAssistant-Tapo-Control/5.1-media-management) - MEDIUM confidence, MediaSource implementation pattern
- [Tapo Control media_source.py](https://github.com/JurajNyiri/HomeAssistant-Tapo-Control/blob/main/custom_components/tapo_control/media_source.py) - HIGH confidence, reference implementation
- [go2rtc built into HA](https://www.home-assistant.io/integrations/go2rtc/) - HIGH confidence, audio streaming via go2rtc
- [HA Media Source Integration](https://www.home-assistant.io/integrations/media_source/) - HIGH confidence, media browsing framework
- [HA WebRTC Architecture Discussion](https://github.com/home-assistant/architecture/discussions/1040) - MEDIUM confidence, WebRTC stream configuration
- [lib32100 (PPPP reference implementation)](https://github.com/fbertone/lib32100) - MEDIUM confidence, port 32100 protocol reference
- Codebase: `const.py` lines 78-81 (CH_CMD=0, CH_VIDEO=1, CH_AUDIO=2, CH_TALK=3) - HIGH confidence, already in codebase

---

*Architecture research: 2026-04-02*
