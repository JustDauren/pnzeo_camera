# Pitfalls: PNZEO Camera Full Integration

**Researched:** 2026-04-02

## Critical Pitfalls

### 1. Audio DRW Packet Format Is Inferred, Not Verified
- **Risk:** CRITICAL — DRW channels 2/3 (audio/talk) packet format is inferred from JNI signatures. The actual start/stop commands may use binary protocol messages, not CGI commands
- **Warning signs:** Audio start command sent but camera doesn't respond; unexpected bytes in DRW responses
- **Prevention:** Wireshark-capture RTStartAudio/RTStartTalk from Android emulator BEFORE implementation. Do not guess packet format
- **Phase:** Audio phase — must be preceded by protocol capture

### 2. Keepalive Timing Is Relay-Critical
- **Risk:** HIGH — Cloud relay drops connection without frequent heartbeat (1s interval). Current keepalive implementation has silent exception swallowing
- **Warning signs:** Connection drops after ~30-60 seconds of inactivity; reconnect loops
- **Prevention:** Ensure keepalive task never dies silently. Add watchdog for keepalive task. Log all keepalive failures at WARNING level
- **Phase:** Connection reliability phase

### 3. Socket Resource Leaks on Error Paths
- **Risk:** HIGH — Raw UDP socket management without context managers. Multiple close() calls scattered without try-finally protection
- **Warning signs:** Pi5 gradually running out of file descriptors; "Too many open files" errors after days of operation
- **Prevention:** Wrap all socket lifecycle in context managers or try-finally. Use asyncio.DatagramProtocol instead of raw sockets where possible
- **Phase:** Connection reliability phase

### 4. Blocking Event Loop With Synchronous DNS/Socket Operations
- **Risk:** HIGH — Some socket operations (DNS resolution, sendto on blocking socket) can freeze HA event loop on Pi5
- **Warning signs:** HA dashboard becomes unresponsive during camera reconnection; "WARNING: Detected I/O inside the event loop" in HA logs
- **Prevention:** Use asyncio.get_event_loop().run_in_executor() for blocking socket ops. Use asyncio.DatagramProtocol for UDP
- **Phase:** Connection reliability phase

### 5. CGI Response Parsing Brittleness
- **Risk:** MEDIUM — Current CGI response parsing assumes specific format. Different firmware versions may return different response formats
- **Warning signs:** KeyError when parsing camera params; unexpected response format from new firmware
- **Prevention:** Defensive parsing with fallbacks. Log raw responses at DEBUG for troubleshooting. Never crash on malformed response — degrade gracefully
- **Phase:** CGI command expansion phase

### 6. SD Card File List Pagination
- **Risk:** MEDIUM — SD card may contain thousands of recordings. Fetching full list in single CGI call may timeout or OOM on Pi5
- **Warning signs:** get_record_param.cgi timeout; large memory spike during SD card browsing
- **Prevention:** Implement pagination. Cache file list with TTL. Don't fetch entire list on coordinator update — only fetch on explicit user action
- **Phase:** SD card phase

### 7. G.711 A-Law Without audioop (Python 3.13+)
- **Risk:** MEDIUM — Python 3.13 removed `audioop` stdlib module. Must use pure Python lookup tables for audio codec
- **Warning signs:** ImportError on audioop; audio playback sounds distorted
- **Prevention:** Implement G.711 as 256-entry lookup table (well-known algorithm). Test with known audio samples
- **Phase:** Audio phase

### 8. Multiple Concurrent DRW Channels
- **Risk:** MEDIUM — Current implementation only uses channel 0 (command). Adding audio channels 2/3 requires multiplexing DRW responses by channel
- **Warning signs:** Audio packets incorrectly parsed as CGI responses; command responses mixed with audio data
- **Prevention:** Add channel routing to DRW receive handler. Separate response queues per channel
- **Phase:** Audio phase (must be designed in architecture)

### 9. Config Flow Credential Security
- **Risk:** MEDIUM — Default password "8888" hardcoded. Credentials in RTSP URL visible in logs
- **Warning signs:** Security audit flagging password in URLs; user complaint about credential exposure
- **Prevention:** Force explicit password entry. Use HA's built-in credential storage. Never log RTSP URLs with credentials
- **Phase:** Config flow improvement phase

### 10. Cloud Relay IP Addresses Hardcoded
- **Risk:** LOW (but catastrophic if triggered) — P2P server IPs hardcoded. If AWS IPs change, all cloud connections break
- **Warning signs:** Cloud discovery timeout; all cameras show offline but LAN still works
- **Prevention:** Add configurable server list. Implement DNS-based discovery if available. Document LAN-only operation as fallback
- **Phase:** Connection reliability phase

## HA-Specific Pitfalls

### 11. Entity Count Explosion
- **Risk:** MEDIUM — Adding all features may create 30+ entities per camera. HA UI becomes cluttered
- **Warning signs:** User complaints about too many entities; dashboard unusable
- **Prevention:** Use entity_registry defaults (enable only essential entities). Group related entities. Use device info to organize
- **Phase:** Entity creation phases

### 12. Coordinator Polling Overhead
- **Risk:** LOW — Adding 15+ CGI commands to polling cycle may slow down 60s update interval
- **Warning signs:** Coordinator update taking >10 seconds; missed polling cycles
- **Prevention:** Only poll essential params (status, alarms). Fetch detailed params on-demand, not every cycle. Group CGI commands efficiently
- **Phase:** CGI command expansion phase

### 13. EventEntity Version Requirement
- **Risk:** LOW — EventEntity was introduced in HA 2023.8. Integration should specify minimum HA version
- **Warning signs:** ImportError on older HA installations
- **Prevention:** Set minimum HA version in manifest.json. Add compatibility check in __init__.py
- **Phase:** Requirements phase
