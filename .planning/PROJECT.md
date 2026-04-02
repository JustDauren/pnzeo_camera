# PNZEO Camera — Full HA Integration

## What This Is

Home Assistant custom component for PNZEO IP cameras (and compatible MTCam-based cameras) using the proprietary PPPP P2P protocol. Provides complete local control of the camera from HA — full feature parity with the MTCam HD Android app, including hidden/undocumented features. One-click HACS install, auto-discovery on LAN, user enters password and everything works.

## Core Value

**Any PNZEO camera owner installs via HACS, enters their password, and gets full camera control — video, audio, PTZ, alarms, SD card, settings — working autonomously on their local network without the Chinese app.**

## Requirements

### Validated

- ✓ P2P/Cloud relay connection (PPPP protocol) — existing
- ✓ RTSP video stream in HA dashboard — existing
- ✓ PTZ control (pan/tilt/zoom, patrol, presets) — existing
- ✓ Basic camera settings (resolution, brightness, contrast, mirror, LED) — existing
- ✓ Config flow with device ID input — existing
- ✓ LAN discovery (UDP 8600 DH + UDP 32108 PPPP) — existing
- ✓ Cloud port discovery with LAN fallback — existing
- ✓ Coordinator-based polling (60s) — existing
- ✓ HACS compatibility — existing

### Active

- [ ] Auto-discovery in config flow (LAN scan finds cameras, user picks and enters password)
- [ ] Two-way audio (listen from camera + talk to camera via PPPP)
- [ ] Motion detection alarm settings (full 33-param RTAlarmSetting)
- [ ] Extended alarm settings (11-param RTAlarmEXSetting)
- [ ] Alarm event notifications → HA events/binary_sensor
- [ ] SD card management (format, unmount, capacity status)
- [ ] SD card recording settings (mode, schedule — 25 params)
- [ ] SD card playback (list recordings, calendar, file access)
- [ ] WiFi scan and configuration from HA
- [ ] Extended IR/night vision settings (RTSetIrcutAttr — 5 params)
- [ ] Time/timezone sync (RTSynchMobileTime)
- [ ] User management (3 user slots — RTUserSetting)
- [ ] FTP upload settings
- [ ] Email notification settings
- [ ] Device info sensor (firmware version, device name, capabilities)
- [ ] Factory reset button
- [ ] Reboot button (already exists, verify working)
- [ ] Camera capability detection (RTGetCapability → adapt UI)
- [ ] Stable reconnection (auto-reconnect on disconnect, exponential backoff)
- [ ] Connection status binary_sensor
- [ ] Push notification integration (FCM token registration)
- [ ] Sound detection alarm settings
- [ ] GPIO alarm settings
- [ ] Power management settings (PowSet)
- [ ] Snapshot via PPPP (not just RTSP)

### Out of Scope

- Cloud account system — camera has no cloud accounts, all P2P
- Multi-brand support — only PNZEO/MTCam protocol, not TUTK or other P2P
- Android/iOS app — this is HA-only
- QR code camera sharing — HA has its own sharing model
- Local video playback in HA UI — HA doesn't support custom media players
- Direct firmware update from HA — too risky without manufacturer support

## Context

- **Hardware**: PNZEO W8, DC 5V/1A, UID format `MTC888-XXXXXX-XXXXX`
- **Protocol**: PPPP (CS2 Network), NOT TUTK. Native library `libRtMain.so`
- **App**: MTCam HD (`com.rt.mtcamhd`) — decompiled with JADX at `../pnzeo-camera apk/apk-audit/jadx-out/`
- **Protocol docs**: `../pnzeo-camera apk/docs/PPPP_PROTOCOL.md`, `PNZEO_W8_REVERSE.md`
- **Deployment**: Raspberry Pi 5 running Home Assistant
- **Camera count**: 1 camera (PNZEO W8)
- **Connection**: LAN preferred (UDP direct), cloud relay as fallback
- **Video**: RTSP on TCP 554 (independent of PPPP), any password works
- **Control**: CGI commands wrapped in DRW packets over PPPP UDP
- **Default credentials**: admin / 8888

## Constraints

- **Platform**: Home Assistant custom component (Python, asyncio)
- **No external deps**: Pure Python (no C extensions, no libRtMain.so)
- **Network**: UDP only for PPPP (no TCP fallback for control)
- **Pi5 resources**: Must be lightweight, single camera, ~60s polling
- **Security**: Never commit real Device IDs, passwords, or IP addresses
- **Deployment**: Git push → HACS install, no manual file copying
- **Compatibility**: Must work with any PNZEO/MTCam camera, not just W8

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Pure Python PPPP implementation (no libRtMain.so) | Cross-platform, no ARM binary dependency, full control | ✓ Good |
| RTSP for video, PPPP for control | Separation of concerns, RTSP works even if PPPP fails | ✓ Good |
| CGI-over-DRW for commands | Matches original app protocol exactly | ✓ Good |
| Cloud relay as fallback only | LAN is faster and more reliable | — Pending |
| Auto-discovery + manual UID | Maximum ease of use with fallback | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-02 after initialization*
