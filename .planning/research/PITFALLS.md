# Domain Pitfalls

**Domain:** PPPP P2P camera integration for Home Assistant (audio, alarms, SD card, multi-channel)
**Researched:** 2026-04-02
**Overall confidence:** HIGH (verified against codebase, decompiled APK, protocol research, HA developer docs)

---

## Critical Pitfalls

Mistakes that cause rewrites, data loss, or HA instability.

### Pitfall 1: DRW Packet Reassembly Absent -- Large Responses Silently Truncated

**What goes wrong:** The current `_handle_drw_response()` stores only the FIRST DRW packet received (`self._drw_data = data`). SD card file listings (`RTGetSDCardRecordFileList`), alarm parameter queries (33+ params), and recording schedule responses (25+ params) return payloads larger than a single UDP packet (~1400 bytes MTU). The camera splits these into multiple DRW packets with sequential index numbers. Only the first fragment is captured; the rest are silently dropped.

**Why it happens:** The existing CGI command layer was built for small request/response pairs (check_user, camera_control). Each response fit in one DRW packet. The protocol's DRW layer uses `channel` + `index` fields (bytes 3-6 of F1D0 header) for ordered delivery across fragments, but the current code ignores these fields entirely.

**Consequences:**
- SD card file list returns truncated/empty results
- Alarm settings with 33 parameters return partial data
- Recording schedule (25 params + SD status) corrupted
- `parse_drw_cgi_response()` fails to find valid JSON in truncated payload

**Prevention:**
1. Implement a per-channel reassembly buffer keyed by `(channel, starting_index)`
2. Track expected sequence via DRW index field (2-byte BE at offset 4-5)
3. Set a reassembly timeout (500ms after last fragment) and max buffer size (64KB)
4. Only call `parse_drw_cgi_response()` after all fragments assembled
5. Send DRW_ACK (F1D1) for each fragment received -- camera may retransmit without ACKs

**Detection:** Any CGI response with `len(data) > 1200` bytes at the DRW level, or responses that `parse_drw_cgi_response()` returns `None` for despite camera being connected.

**Warning signs:** `get_alarm.cgi` returns partial parameter sets, SD card file count mismatches `fileTotalCount`, `get_record_param.cgi` returns fewer than 25 fields.

**Phase mapping:** Must be implemented BEFORE SD card file listing and alarm settings phases. This is a prerequisite.

**Confidence:** HIGH -- verified from codebase (`pppp_client.py:401`, `pppp_packets.py:546-554` show channel/index parsed but unused), CONCERNS.md documents this gap, and PPPP protocol spec confirms multi-fragment DRW delivery.

---

### Pitfall 2: DRW Channel Multiplexing Collision -- Commands Corrupt Audio Stream

**What goes wrong:** The current implementation uses a single `_drw_response` event and `_drw_data` buffer for ALL incoming DRW packets regardless of channel. When audio streaming is active on CH_AUDIO (channel 2), audio data packets (F1D0 with channel=2) trigger `_handle_drw_response()`, overwriting the pending CGI command response (channel 0). A CGI command sent during active audio streaming has its response replaced by an audio frame.

**Why it happens:** The `datagram_received()` handler treats ALL F1D0 packets identically:
```python
elif pkt_type == PktType.DRW:
    self.client._handle_drw_response(data)
```
It does not check the channel byte. With only CGI commands on CH_CMD, this worked. With audio on CH_AUDIO arriving 25+ times per second, CGI responses get stomped constantly.

**Consequences:**
- Camera control commands (PTZ, settings) silently fail during audio playback
- `_send_cgi()` retry loop burns all 25 retries because each "response" is actually audio data
- 25 retries x 300ms = 7.5 seconds of blocked command execution per attempt
- User sees camera controls become unresponsive when audio is enabled

**Prevention:**
1. Parse channel byte from DRW header BEFORE dispatching: `channel = data[2]`
2. Route to separate handlers: CH_CMD -> command response, CH_AUDIO -> audio buffer, CH_TALK -> talk feedback
3. Each channel gets its own asyncio.Event and buffer:
   ```python
   self._channel_events: dict[int, asyncio.Event] = {}
   self._channel_buffers: dict[int, bytearray] = {}
   ```
4. Audio packets should be routed to an `asyncio.Queue` not an Event (continuous stream vs one-shot response)
5. Send DRW_ACK for each channel independently

**Detection:** During audio streaming, if CGI commands start timing out (25 retries exhausted) that previously worked.

**Warning signs:** PTZ commands work when audio is off but fail when audio is on. `_send_cgi()` returns None frequently during audio streaming.

**Phase mapping:** CRITICAL prerequisite for audio phase. Must be implemented before any streaming feature.

**Confidence:** HIGH -- verified from codebase (`pppp_client.py:426-427` shows no channel filtering, `const.py:78-81` defines CH_CMD=0, CH_AUDIO=2, CH_TALK=3 but they are unused in packet routing).

---

### Pitfall 3: Audio Streaming Without Jitter Buffer -- Unusable Real-Time Audio

**What goes wrong:** Raw UDP audio arrives with variable jitter (5-50ms variation on WiFi). Playing audio samples in `datagram_received()` arrival order without buffering produces garbled, stuttering audio. Implementing talk-back (sending audio TO camera) without proper framing causes camera firmware to drop audio or play it at wrong speed.

**Why it happens:** PPPP audio uses channel 2 (CH_AUDIO) for listen and channel 3 (CH_TALK) for talk-back. The camera sends 8KHz PCM (A-law or ADPCM, depending on firmware -- the decompiled APK loads `fdk-aac` and references both formats). Unlike CGI commands which are request/response, audio is a continuous stream with strict timing requirements. Treating it like CGI responses (wait for one packet, process, repeat) fails.

**Consequences:**
- Listen: audio crackles, gaps, or plays at wrong speed
- Talk-back: camera ignores malformed audio, plays silence, or echoes
- `RTTalkAudioData(did, data, len, type)` requires specific PCM format; wrong format = silence
- Both directions: memory grows unbounded if audio buffers accumulate without consumer

**Prevention:**
1. Implement a jitter buffer (ring buffer, 100-200ms depth) for incoming audio on CH_AUDIO
2. Reorder packets by DRW index before playback
3. For missing packets, use silence insertion (zero-fill) not PLC (too complex for first pass)
4. For talk-back, capture audio at 8KHz, encode to camera's expected format, chunk into ~320-byte frames (40ms at 8KHz 8-bit), wrap in DRW on CH_TALK
5. Use `asyncio.Queue` with maxsize for backpressure -- drop oldest if queue full
6. Cap total audio buffer memory at 1MB; if exceeded, drop connection and restart audio

**Detection:** Audio latency > 500ms, audio buffer queue size growing monotonically, `datagram_received()` call rate on CH_AUDIO > 50/sec.

**Warning signs:** Audio works in testing on wired network but breaks on WiFi. Audio works for 10 seconds then degrades.

**Phase mapping:** Audio listen/talk phase. Research the exact codec via packet capture before implementation -- the APK loads fdk-aac but the callback `CallBack_AudioStream` receives raw PCM bytes, suggesting libRtMain.so decodes internally.

**Confidence:** MEDIUM -- audio format confirmed as "8KHz A-law PCM" or "ADPCM" by multiple PPPP implementations (cam-reverse, A9_PPPP), but the EXACT format for this camera's firmware needs packet capture verification. The RTNativeCaller shows `RTTalkAudioData(did, data, len, type)` where `type` parameter selects codec, but the valid type values are in libRtMain.so (not decompilable).

---

### Pitfall 4: Blocking the HA Event Loop with Synchronous Socket Operations

**What goes wrong:** The current `_cloud_discover_port()` and `_lan_discover_port()` methods use synchronous `socket.socket()` with blocking `sendto()`/`recvfrom()` calls. These block the HA event loop for up to 3 seconds per cloud server (6 seconds total worst case). HA 2025+ actively detects and warns about blocking calls. Adding more synchronous operations (SD card file transfers, audio streaming setup) compounds this.

**Why it happens:** The original implementation used blocking sockets because `asyncio.DatagramProtocol` was only used for the main P2P connection. Quick discovery operations used plain sockets for simplicity. But as features grow, each new synchronous socket blocks the entire HA event loop.

**Consequences:**
- HA logs `WARNING: Detected blocking call to ... inside the event loop`
- Other integrations freeze during camera discovery/reconnection
- Coordinator update stalls when camera reconnects (up to 12+ seconds: 6s cloud + 1.8s punch + 7.5s DRW retry)
- On Pi5 with multiple integrations, this causes cascading timeouts

**Prevention:**
1. Move ALL socket operations to `hass.async_add_executor_job()` or rewrite using `asyncio.DatagramProtocol`
2. For cloud discovery: `await hass.async_add_executor_job(self._sync_cloud_discover)`
3. For LAN discovery: same pattern, or better: reuse the existing DatagramProtocol endpoint
4. Set hard timeout caps: cloud discovery 2s total (not per-server), LAN discovery 2s
5. Never use `socket.socket()` directly in async code paths
6. Enable HA debug mode during development to catch blocking calls early

**Detection:** HA log grep for `Detected blocking call`, event loop lag > 1s measured via `asyncio.get_event_loop().time()` delta.

**Warning signs:** Other automations become sluggish when camera integration is loaded. HA dashboard shows "Updating" spinner for long periods.

**Phase mapping:** Should be fixed as infrastructure improvement BEFORE adding audio/SD card features. Each new feature adds more async operations that compound the problem.

**Confidence:** HIGH -- verified from codebase (`pppp_client.py:217-248` uses blocking socket), HA developer docs explicitly list `socket.sendto()` and `socket.recvfrom()` as blocking operations that must run in executor.

---

### Pitfall 5: asyncio.Task Leaks on Config Entry Reload/Unload

**What goes wrong:** The keepalive task (`self._keepalive_task`) is created with `asyncio.create_task()` but cleanup depends on `disconnect()` being called. If HA reloads the integration (config change, HA restart, entry unload), the keepalive task may not be cancelled. Adding audio streaming tasks and alarm polling tasks multiplies this: each leaked task holds a reference to the transport, socket, and client object.

**Why it happens:** `async_unload_entry()` calls `coordinator.device.async_teardown()` but if teardown raises an exception partway through, some tasks survive. The keepalive loop catches `CancelledError` (correct) but also catches all `Exception` silently (line 398), so a malfunctioning keepalive may never terminate.

**Consequences:**
- File descriptor leak: each leaked transport holds an open UDP socket
- Memory leak: client object + protocol object + buffer data retained
- Ghost keepalives: old connection sends keepalives to camera while new connection tries to handshake
- Pi5 eventually runs out of file descriptors (ulimit default 1024)

**Prevention:**
1. Track ALL created tasks in a list: `self._tasks: list[asyncio.Task] = []`
2. In `_cleanup()`, cancel ALL tasks and await them with timeout:
   ```python
   for task in self._tasks:
       task.cancel()
   await asyncio.gather(*self._tasks, return_exceptions=True)
   self._tasks.clear()
   ```
3. Use `entry.async_on_unload()` to register cleanup callbacks for each async resource
4. Verify transport is truly closed after `transport.close()` by checking `transport.is_closing()`
5. Add task naming for debug: `asyncio.create_task(coro, name="pnzeo_keepalive")`
6. Log warning (not silently pass) on unexpected exceptions in keepalive loop

**Detection:** After reload, check `asyncio.all_tasks()` for tasks with "pnzeo" in name. Monitor open file descriptors: `ls /proc/$(pidof python3)/fd | wc -l`.

**Warning signs:** Each config reload increases memory usage. Camera works after reload but stops after several reloads.

**Phase mapping:** Infrastructure fix. Must be addressed BEFORE adding audio tasks and alarm polling tasks which would create additional long-running tasks.

**Confidence:** HIGH -- verified from codebase (`pppp_client.py:169`, `pppp_client.py:398`), HA developer docs on config entry lifecycle, and HA core issues on file descriptor leaks.

---

### Pitfall 6: Audio Start/Stop Uses Binary Protocol, Not CGI

**What goes wrong:** Developer assumes audio start/stop uses CGI commands (like all other features). But `RTStartAudio`, `RTStopAudio`, `RTStartTalk`, `RTStopTalk` are JNI methods in libRtMain.so that send binary protocol messages, not CGI. Trying CGI-style audio commands gets timeout or `result=-1` with no useful error.

**Why it happens:** All existing camera control uses CGI-over-DRW with the `D1 00 00 SEQ 01 0A` inner header. The natural assumption is that audio follows the same pattern. But audio start commands likely use the binary `encode_command(msg_type, params)` format already defined in `pppp_packets.py:561-563`, with a different inner header format.

**Consequences:** Days of debugging wrong approach. No error message from camera -- just silence.

**Prevention:**
1. MUST Wireshark-capture actual packets sent by Android app during `RTStartAudio`/`RTStartTalk`
2. Compare inner header: CGI uses `D1 00 00 SEQ 01 0A` prefix; binary protocol likely uses direct `cmd_id(2 LE) + payload_len(2 LE)` encoding
3. The `encode_command()` function already exists for binary messages -- may need it here
4. Check if `RTSetVoiceEnable(did, 1)` is a prerequisite before `RTStartAudio`
5. Test audio start ONLY after confirming packet format via capture

**Detection:** If CGI-style audio start gets `result=-1` or timeout, switch to binary protocol investigation.

**Warning signs:** Audio CGI endpoint not found in any Foscam/IP camera CGI documentation (because it's not CGI).

**Phase mapping:** Audio phase -- protocol capture must happen BEFORE implementation begins.

**Confidence:** HIGH -- verified from APK that audio uses JNI native methods (not Java CGI helpers), and the fact that no CGI endpoint for audio exists in `pppp_packets.py` CGI constants confirms this is NOT a CGI operation.

---

## Moderate Pitfalls

### Pitfall 7: Alarm Event Polling Latency -- Motion Detection Useless at 60s Interval

**What goes wrong:** Motion alarm events have a typical duration of 2-15 seconds. The current coordinator polls every 60 seconds. By the time the poll detects `alarmstatus=1`, the motion event ended 45+ seconds ago. The binary_sensor flips on/off in the same cycle, or the event is missed entirely if the camera resets alarm status between polls.

**Why it happens:** The original camera app uses the native callback `CallBack_Alarm(did, picName, alarmType, alarmTime, fileStartTime, fileStopTime)` which is a PUSH notification from camera to client via DRW on CH_CMD. This arrives in real-time. Polling `get_status.cgi` checks the current state, not the event history.

**Prevention:**
1. Implement event-driven alarm detection: camera sends alarm notifications as unsolicited DRW packets on CH_CMD (not CGI responses)
2. Parse incoming DRW packets for alarm notification format (distinct from CGI responses -- different inner header)
3. As fallback, poll `get_alarm_log.cgi` for recent events rather than just current status
4. Set binary_sensor with `device_class=motion` and auto-off timer (configurable, default 30s)
5. Do NOT reduce polling interval below 15s -- camera firmware may crash under high CGI load

**Detection:** Motion events detected by HA automation lag > 30 seconds behind actual motion. Camera alarm LED blinks but HA binary_sensor stays off.

**Warning signs:** Alarm works in MTCam app (which uses push) but not in HA (which uses polling).

**Phase mapping:** Alarm events phase. Requires understanding whether this camera's firmware sends unsolicited DRW alarm notifications or only responds to polling.

**Confidence:** MEDIUM -- alarm push mechanism confirmed in decompiled APK (`CallBack_Alarm` with alarmType, timestamps), but whether the camera sends these without libRtMain.so actively listening is unverified. Needs packet capture.

---

### Pitfall 8: SD Card File Transfer Over DRW -- Memory Exhaustion on Large Files

**What goes wrong:** SD card recordings are AVI/MP4 files, typically 10-50MB each. `RTStartDownLoadVideo` transfers these over DRW as sequential 1028-byte payloads. Buffering an entire file in memory before writing to disk exhausts Pi5 RAM (1-4GB shared with HA and OS). Even a 20MB file = 20,000 DRW packets that must be reassembled in order.

**Why it happens:** The natural Python approach is to accumulate bytes in a `bytearray` until transfer completes, then write to disk. With DRW's reliable-delivery model (retransmissions on loss), transfers are slow: ~100-200KB/s over WiFi UDP with retransmissions. A 50MB file takes 4-8 minutes of continuous buffering.

**Consequences:**
- Pi5 OOM-kills HA process during large file download
- Multiple simultaneous downloads (user browses SD card, clicks several files) multiply memory usage
- DRW retransmissions during transfer cause duplicate data in buffer if dedup not implemented
- Camera may timeout the P2P session during long transfers if keepalives are disrupted

**Prevention:**
1. Stream to disk: write each reassembled chunk immediately, do not accumulate full file in memory
2. Limit concurrent downloads to 1 (queue additional requests)
3. Cap maximum downloadable file size (100MB) with user-facing error for larger files
4. Track transfer progress via `fileCount`/`fileTotalCount` from callback
5. Use `hass.async_add_executor_job()` for disk writes
6. Maintain keepalive during transfer -- command channel must stay alive

**Detection:** HA process RSS memory growing during SD card download. Download never completes for files > 5MB.

**Warning signs:** Small files download fine, large files cause HA restart.

**Phase mapping:** SD card playback/download phase. Consider whether direct file download is in scope at all -- listing and playback info may be sufficient for first milestone.

**Confidence:** MEDIUM -- transfer mechanism inferred from `RTStartDownLoadVideo`/`RTStopDownLoadVideo` and `CallBack_DownLoadFile(did, filename, state, type, fileSize)` in decompiled APK. Exact DRW framing for file transfer needs packet capture.

---

### Pitfall 9: Connection State Machine Race Conditions

**What goes wrong:** Adding audio streaming, alarm monitoring, and SD card operations creates multiple concurrent async operations sharing one UDP transport. Without explicit state management, race conditions occur: a reconnection attempt starts while audio is streaming, a CGI command is sent before P2P handshake completes, or a file download is interrupted by keepalive failure without proper cleanup.

**Why it happens:** The current state is tracked by two booleans: `_connected` and `_authenticated`. There is no STREAMING, DOWNLOADING, or RECONNECTING state. Multiple callers (coordinator poll, user PTZ action, audio stream, alarm handler) all access `_send_cgi()` without coordination.

**Prevention:**
1. Replace boolean flags with a `ConnectionState` enum:
   ```python
   class ConnectionState(enum.Enum):
       DISCONNECTED = "disconnected"
       CONNECTING = "connecting"
       AUTHENTICATING = "authenticating"
       CONNECTED = "connected"
       STREAMING = "streaming"
       DOWNLOADING = "downloading"
       RECONNECTING = "reconnecting"
       FAILED = "failed"
   ```
2. Use `asyncio.Lock` for state transitions to prevent concurrent connect/disconnect
3. Queue CGI commands with `asyncio.Queue` instead of direct `_send_cgi()` calls
4. Define valid state transitions (CONNECTED -> STREAMING is valid, CONNECTING -> STREAMING is not)
5. Add state change logging at INFO level for debugging

**Detection:** Exceptions during connect while already connected. Multiple `build_alive()` streams to different ports simultaneously.

**Warning signs:** Intermittent "P2P handshake failed" errors that resolve on retry. Camera works after restart but degrades over hours.

**Phase mapping:** Infrastructure improvement. Should be implemented before or alongside the first new feature phase.

**Confidence:** HIGH -- verified from CONCERNS.md ("Protocol state machine lacks explicit states") and codebase analysis showing boolean-only state tracking.

---

### Pitfall 10: Camera Firmware Crash from Command Flood

**What goes wrong:** Enabling alarm polling, audio streaming, and periodic status checks simultaneously generates a high CGI command rate. The camera firmware (HiSilicon chip, limited RAM) crashes or stops responding when receiving more than ~2-3 CGI commands per second. After crash, camera requires power cycle.

**Why it happens:** Each feature independently sends commands without global rate limiting:
- Status poll: 2 CGI commands per 60s cycle
- Alarm poll: 1-2 CGI commands per poll
- PTZ: rapid fire during pan operations
- Audio start/stop: 1 command each
- SD card listing: 1 command + potentially many page fetches

The DRW retry mechanism (25 retries x 300ms) compounds the problem: a failed command generates 25 additional packets.

**Prevention:**
1. Implement a global command queue with minimum 200ms spacing between CGI commands
2. Prioritize commands: user-initiated (PTZ, settings) > polling (status, alarm) > background (capability check)
3. Coalesce status queries: combine `get_status.cgi` and `get_camera_params.cgi` into one poll cycle with 200ms gap
4. Reduce DRW_RETRY_MAX from 25 to 5 for interactive commands
5. Implement circuit breaker: if 3 consecutive commands fail, backoff 10s before retrying
6. Keepalive is independent of command queue (F1E0, not DRW CGI)

**Detection:** Camera stops responding to all commands but keepalives still work. Camera RTSP stream freezes simultaneously.

**Warning signs:** Camera occasionally becomes unresponsive for 30-60 seconds, then recovers.

**Phase mapping:** Should be implemented as part of the command infrastructure before adding alarm polling and SD card operations.

**Confidence:** HIGH -- documented in CONCERNS.md ("No rate limiting on camera control commands"), `DRW_RETRY_MAX = 25` at `pppp_client.py:39`.

---

### Pitfall 11: Alarm Parameter Mismatch -- 33 Params in Wrong Order Brick Settings

**What goes wrong:** `RTAlarmSetting` takes exactly 33 integer parameters in a specific order. Sending parameters in wrong order, or with wrong names, either silently fails or corrupts camera's alarm configuration requiring factory reset.

**Why it happens:** The CGI interface (`set_alarm.cgi`) accepts named parameters, but the parameter names must EXACTLY match what the firmware expects. A typo in parameter name (`motion_arm` vs `motion_armed`) causes the camera to ignore the parameter but accept the request -- resulting in an alarm config that looks correct from the response but doesn't actually enable motion detection.

**Consequences:**
- Motion detection silently disabled despite HA showing it as enabled
- Schedule corruption: wrong time slots armed/disarmed
- Alarm settings survive reboot, so corrupted settings persist
- Only fix is factory reset + reconfigure from scratch

**Prevention:**
1. Define all 33 alarm parameters as a frozen dataclass with strict validation
2. Always GET current alarm settings before SET -- merge changed values with existing, do not send partial updates
3. Validate parameter names against the canonical list from `CallBack_AlarmParams`:
   `motion_armed, motion_sensitivity, input_armed, ioin_level, iolinkage, ioout_level, alarmpresetsit, mail, snapshot, record, upload_interval, schedule_enable, schedule_sun_0, schedule_sun_1, schedule_sun_2, schedule_mon_0, schedule_mon_1, schedule_mon_2, schedule_tue_0, schedule_tue_1, schedule_tue_2, schedule_wed_0, schedule_wed_1, schedule_wed_2, schedule_thu_0, schedule_thu_1, schedule_thu_2, schedule_fri_0, schedule_fri_1, schedule_fri_2, schedule_sat_0, schedule_sat_1, schedule_sat_2`
4. Same for `RTAlarmEXSetting` (11 params): `mdAlarmType, mdSensitive, mdInterval, mdEmailSnap, mdFtpSnap, mdFtpRec, ioEnable, ioInterval, ioEmailSnap, ioFtpSnap, ioFtpRec`
5. Unit test parameter encoding against known-good captures

**Detection:** After setting alarm, GET alarm params and compare with intended values. Any mismatch = bug.

**Warning signs:** Alarm "enabled" in HA but camera doesn't trigger. Alarm settings revert after camera reboot.

**Phase mapping:** Alarm settings phase. Parameter lists verified from decompiled `RTNativeCallBack.java:308-347`.

**Confidence:** HIGH -- exact parameter names verified from decompiled APK.

---

## Minor Pitfalls

### Pitfall 12: SD Card File List Pagination Not Handled

**What goes wrong:** `RTGetSDCardRecordFileList` returns results one file at a time via callbacks. The callback includes `fileCount` (current index) and `fileTotalCount` (total files). If there are 500 recordings, the camera sends 500 individual DRW responses. Without pagination handling, the client either waits indefinitely or gives up after a few responses.

**Prevention:**
- Track `fileTotalCount` from first response, accumulate until `fileCount == fileTotalCount`
- Set a per-file timeout (1s) and total timeout (30s for entire listing)
- Return partial results on timeout rather than nothing
- Cache file list for 5 minutes to avoid repeated full scans
- Use `RTGetSDCardRecordFileListNew` which adds startIdx/count for pagination

**Phase mapping:** SD card playback phase.

**Confidence:** MEDIUM -- callback signature verified from APK (`CallBack_RecordFileSearchResult`), but exact DRW framing unverified.

---

### Pitfall 13: Talk-Back Audio Format Mismatch

**What goes wrong:** `RTTalkAudioData(did, data, len, type)` has a `type` parameter that selects the audio codec. Sending audio encoded in the wrong format produces silence or noise on the camera speaker.

**Prevention:**
- Query camera capabilities first (`RTGetP2PApability`) to determine supported audio formats
- Start with 8KHz 8-bit A-law PCM (most common for PPPP cameras)
- If silence, try ADPCM (IMA ADPCM 4-bit)
- The APK loads `fdk-aac` -- AAC may be supported for higher quality
- Make codec configurable in HA options flow

**Phase mapping:** Two-way audio phase.

**Confidence:** LOW -- the `type` parameter values are inside libRtMain.so which cannot be decompiled. Must be determined via packet capture or trial-and-error.

---

### Pitfall 14: G.711 A-Law Without audioop (Python 3.13+)

**What goes wrong:** Python 3.13 removed the `audioop` stdlib module. Any code using `audioop.lin2alaw()` will break on modern HA installations.

**Prevention:**
- Implement G.711 A-law encode/decode as a 256-entry lookup table (~40 lines of code)
- Do NOT depend on `audioop` or any external audio library
- For ADPCM, implement IMA ADPCM in pure Python (~80 lines)
- Test with known reference audio samples

**Phase mapping:** Audio phase.

**Confidence:** HIGH -- Python 3.13 changelog confirms `audioop` removal.

---

### Pitfall 15: Treating Audio as Polled State (Coordinator Pattern)

**What goes wrong:** Developer adds audio data to coordinator's `_async_update_data()` return value. Audio at 8KB/s flowing through coordinator causes massive state churn: every update triggers all entity callbacks. HA database bloats.

**Prevention:**
- Audio streaming uses its own callback system via channel routing in `datagram_received()`
- Only audio ON/OFF boolean goes in coordinator.data
- Audio sample buffers live in a separate `asyncio.Queue`, not coordinator
- If coordinator.data dict exceeds a few KB, something is wrong

**Phase mapping:** Audio phase.

**Confidence:** HIGH -- standard HA pattern. Coordinator is for polled state, not streaming data.

---

### Pitfall 16: `_camera_params` Dict Grows Unbounded

**What goes wrong:** Every call to `get_camera_params()` and `get_status()` does `self._camera_params.update(resp)`. With all features, dict grows indefinitely.

**Prevention:**
- Namespace state by feature area: `self._state = {"alarm": {...}, "recording": {...}, "camera": {...}}`
- Or implement TTL-based expiry: expire keys older than 5 minutes
- Set a hard cap on dict size (1000 keys)

**Phase mapping:** Infrastructure improvement, implement during state machine refactor.

**Confidence:** HIGH -- verified from codebase (`pppp_client.py:312,319`), documented in CONCERNS.md.

---

### Pitfall 17: Entity Count Explosion Without Feature Gating

**What goes wrong:** Adding all features creates 30+ entities per camera. HA UI cluttered.

**Prevention:**
- Use `entity_registry_enabled_default=False` for non-essential entities
- Gate entity creation on capability detection
- Group related entities under HA device info

**Phase mapping:** Every entity creation phase.

**Confidence:** HIGH -- standard HA pattern.

---

### Pitfall 18: Recording Schedule Overlap with Alarm Schedule

**What goes wrong:** `RTSDRecordSetting` (25 params) includes recording schedule slots that overlap with alarm schedule slots in `RTAlarmSetting`. Changing recording schedule without accounting for alarm schedule creates conflicts.

**Prevention:**
- Present alarm and recording schedules in a unified UI
- Use GET before SET for both settings when changing either
- Prefer `CallBack_RecordParamsEX` (simpler: sdRecMode, fullRecTime, alarmRecTime, audioRecEnable) for basic configuration

**Phase mapping:** SD card recording settings phase.

**Confidence:** MEDIUM -- verified from decompiled APK, but schedule interaction is firmware-dependent.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation | Priority |
|-------------|---------------|------------|----------|
| DRW packet reassembly | #1 (truncation) | Implement fragment buffer with channel+index tracking | PREREQUISITE for all below |
| Channel multiplexing | #2 (audio stomps commands) | Per-channel dispatch in datagram_received | PREREQUISITE for audio |
| Event loop blocking | #4 (sync sockets) | Move to executor or async protocols | PREREQUISITE for reliability |
| Task lifecycle | #5 (task leaks) | Track all tasks, cancel on unload | PREREQUISITE for new tasks |
| Audio protocol capture | #6 (binary not CGI) | Wireshark capture BEFORE code | PREREQUISITE for audio |
| State machine | #9 (race conditions) | ConnectionState enum + asyncio.Lock | HIGH, before multi-feature |
| Command rate limiting | #10 (camera crash) | Global command queue, 200ms spacing | HIGH, before alarm polling |
| Audio listen | #3 (jitter/format), #14 (audioop) | Jitter buffer + pure Python codec | MEDIUM, audio phase |
| Audio talk-back | #13 (format mismatch) | Capability query + configurable codec | MEDIUM, audio phase |
| Audio state | #15 (coordinator abuse) | Separate queue, not coordinator | MEDIUM, audio phase |
| Alarm settings | #11 (33-param order) | Dataclass validation, GET-before-SET | HIGH, alarm phase |
| Alarm events | #7 (polling latency) | DRW push detection or faster polling | MEDIUM, alarm phase |
| SD card file list | #1+#12 (truncation+pagination) | Reassembly + pagination tracking | MEDIUM, SD phase |
| SD card download | #8 (memory exhaustion) | Stream-to-disk, limit concurrent | MEDIUM, SD phase |
| SD card recording | #18 (schedule overlap) | Unified schedule UI, GET-before-SET | LOW, SD phase |
| State accumulation | #16 (unbounded dict) | Namespace state, TTL expiry | LOW, infrastructure |

---

## Sources

- [PPPP Protocol Overview - Almost Secure (Wladimir Palant, 2025)](https://palant.info/2025/11/05/an-overview-of-the-pppp-protocol-for-iot-cameras/) -- DRW channels, protocol weaknesses, retransmission issues
- [cam-reverse (DavidVentura)](https://github.com/DavidVentura/cam-reverse) -- Audio format (8KHz A-law PCM), DRW framing, packet loss handling
- [A9_PPPP (datenstau)](https://github.com/datenstau/A9_PPPP) -- ADPCM audio format, DRW command structure, JSON-in-DRW protocol
- [aiopppp (devbis)](https://github.com/devbis/aiopppp) -- Async PPPP implementation reference
- [HA Developer Docs: Blocking Operations](https://developers.home-assistant.io/docs/asyncio_blocking_operations/) -- Blocking call detection, executor job pattern
- [HA Developer Docs: Working with Async](https://developers.home-assistant.io/docs/asyncio_working_with_async/) -- Task management, cleanup patterns
- [HA Core Issue #156815](https://github.com/home-assistant/core/issues/156815) -- File descriptor leak patterns in integrations
- [HA Config Entry State Transitions](https://developers.home-assistant.io/blog/2025/02/19/new-config-entry-states/) -- Unload cleanup patterns
- [UDP Jitter Buffering Guide](https://oboe.com/learn/high-performance-udp-audio-streaming-on-esp32-14jdpdf/udp-jitter-buffering-1axtvop) -- Jitter buffer architecture, packet reordering
- Decompiled APK: `RTNativeCaller.java`, `RTNativeCallBack.java` -- Exact parameter names, callback signatures, alarm types, file transfer callbacks

---

*Pitfalls audit: 2026-04-02*
