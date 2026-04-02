# Requirements: PNZEO Camera Full HA Integration

**Defined:** 2026-04-02
**Core Value:** Full camera control from HA — install via HACS, enter password, everything works autonomously on Pi5

## v1 Requirements

### Connection Reliability

- [ ] **CONN-01**: Camera auto-reconnects on disconnect with exponential backoff
- [ ] **CONN-02**: Keepalive task never dies silently — watchdog and logging
- [ ] **CONN-03**: Socket lifecycle managed with context managers / try-finally
- [ ] **CONN-04**: Connection status exposed as binary_sensor (connected/disconnected)
- [ ] **CONN-05**: Protocol state machine uses explicit ConnectionState enum

### Config Flow

- [ ] **CONF-01**: Auto-discovery via LAN scan (UDP 8600 + 32108) — user picks camera from list
- [ ] **CONF-02**: Manual UID entry as fallback option
- [ ] **CONF-03**: Password validation during setup (check_user.cgi)
- [ ] **CONF-04**: Device capabilities detected at setup (RTGetCapability) — adapt available entities

### Alarm & Motion Detection

- [ ] **ALRM-01**: Motion detection on/off switch
- [ ] **ALRM-02**: Motion detection sensitivity setting (number entity, 1-10)
- [ ] **ALRM-03**: Full alarm settings via CGI (alarm schedule, zones)
- [ ] **ALRM-04**: Extended alarm settings (RTAlarmEXSetting — 11 params)
- [ ] **ALRM-05**: Motion detection binary_sensor (polling-based state)
- [ ] **ALRM-06**: Alarm event entity (HA EventEntity for motion/GPIO/sound events)
- [ ] **ALRM-07**: Sound detection alarm settings
- [ ] **ALRM-08**: GPIO alarm settings
- [ ] **ALRM-09**: Alarm log retrieval

### SD Card Management

- [ ] **SDCD-01**: SD card status sensor (total/used/free space)
- [ ] **SDCD-02**: Format SD card button
- [ ] **SDCD-03**: Safely unmount SD card button
- [ ] **SDCD-04**: Recording mode setting (continuous/motion/schedule/off)
- [ ] **SDCD-05**: Recording schedule configuration (25 params)
- [ ] **SDCD-06**: SD card recording list (by date/type)
- [ ] **SDCD-07**: SD card recording calendar (RTGetSDRecordCalendar)
- [ ] **SDCD-08**: SD card file download/playback via MediaSource

### Audio

- [ ] **AUDI-01**: Listen to camera audio stream (DRW channel 2, G.711 A-law decode)
- [ ] **AUDI-02**: Two-way talk (DRW channel 3, G.711 A-law encode + send)
- [ ] **AUDI-03**: Microphone on/off switch (RTSetVoiceEnable)
- [ ] **AUDI-04**: Pure Python G.711 A-law codec (no external deps)
- [ ] **AUDI-05**: Audio format auto-detection from DRW packet headers

### Camera Settings (Extended)

- [ ] **CSET-01**: Extended IR/night vision settings (RTSetIrcutAttr — 5 params: mode, sensitivity, timing)
- [ ] **CSET-02**: IR mode select entity (auto/on/off/schedule)
- [ ] **CSET-03**: Power frequency setting (50Hz/60Hz)
- [ ] **CSET-04**: Device name setting (text entity)

### WiFi Configuration

- [ ] **WIFI-01**: WiFi scan from HA (list available networks)
- [ ] **WIFI-02**: WiFi connect to selected network (SSID + password)
- [ ] **WIFI-03**: Current WiFi status sensor (SSID, signal strength)

### Network Settings

- [ ] **NETW-01**: LAN network settings view (IP, mask, gateway, DNS)
- [ ] **NETW-02**: DDNS settings

### User Management

- [ ] **USER-01**: View current users (3 slots)
- [ ] **USER-02**: Change password service (RTUserSetting)
- [ ] **USER-03**: Add/remove secondary users

### Notifications & Alerts

- [ ] **NOTF-01**: FTP upload settings (server, port, user, password, path)
- [ ] **NOTF-02**: Email notification settings (SMTP server, recipients)
- [ ] **NOTF-03**: Push notification registration (FCM token for MSG_SET_FCM_PUSH)

### Time & System

- [ ] **SYST-01**: Time/timezone sync from HA (RTSynchMobileTime)
- [ ] **SYST-02**: Device info sensor (firmware version, model, capabilities)
- [ ] **SYST-03**: Factory reset button (with confirmation)
- [ ] **SYST-04**: Reboot button (verify existing implementation)

### Snapshot & Recording

- [ ] **SNAP-01**: Snapshot via PPPP (RTSnapJpeg — not just RTSP)
- [ ] **SNAP-02**: Manual recording trigger service

### Diagnostics

- [ ] **DIAG-01**: Integration diagnostics (connection stats, protocol state, last errors)
- [ ] **DIAG-02**: Camera capability dump in diagnostics

## v2 Requirements

### Advanced Features

- **ADV-01**: WebRTC integration for low-latency video (go2rtc)
- **ADV-02**: ONVIF compatibility layer
- **ADV-03**: Multiple camera support optimization (shared cloud connection)
- **ADV-04**: Firmware update notification
- **ADV-05**: AP mode camera setup (initial WiFi config)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Cloud account system | Camera has no cloud accounts — all P2P |
| Android/iOS app | HA-only integration |
| QR code sharing | HA has its own device sharing model |
| Local video playback in HA | HA doesn't support custom media players |
| Direct firmware update | Too risky without manufacturer support |
| Multi-brand P2P support | Only PNZEO/MTCam (CS2 Network), not TUTK |
| Video recording in HA | Use SD card recording or HA's native recording |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| (To be filled during roadmap creation) | | |

**Coverage:**
- v1 requirements: 47 total
- Mapped to phases: 0
- Unmapped: 47

---
*Requirements defined: 2026-04-02*
*Last updated: 2026-04-02 after initial definition*
