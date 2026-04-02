# Requirements: PNZEO Camera Full HA Integration

**Defined:** 2026-04-02
**Core Value:** Full camera control from HA -- install via HACS, enter password, everything works autonomously on Pi5

## v1 Requirements

### Connection Reliability

- [x] **CONN-01**: Camera auto-reconnects on disconnect with exponential backoff
- [x] **CONN-02**: Keepalive task never dies silently -- watchdog and logging
- [x] **CONN-03**: Socket lifecycle managed with context managers / try-finally
- [x] **CONN-04**: Connection status exposed as binary_sensor (connected/disconnected)
- [x] **CONN-05**: Protocol state machine uses explicit ConnectionState enum

### Config Flow

- [ ] **CONF-01**: Auto-discovery via LAN scan (UDP 8600 + 32108) -- user picks camera from list
- [ ] **CONF-02**: Manual UID entry as fallback option
- [ ] **CONF-03**: Password validation during setup (check_user.cgi)
- [ ] **CONF-04**: Device capabilities detected at setup (RTGetCapability) -- adapt available entities

### Alarm & Motion Detection

- [x] **ALRM-01**: Motion detection on/off switch
- [x] **ALRM-02**: Motion detection sensitivity setting (number entity, 1-10)
- [x] **ALRM-03**: Full alarm settings via CGI (alarm schedule, zones)
- [x] **ALRM-04**: Extended alarm settings (RTAlarmEXSetting -- 11 params)
- [x] **ALRM-05**: Motion detection binary_sensor (polling-based state)
- [x] **ALRM-06**: Alarm event entity (HA EventEntity for motion/GPIO/sound events)
- [x] **ALRM-07**: Sound detection alarm settings
- [x] **ALRM-08**: GPIO alarm settings
- [x] **ALRM-09**: Alarm log retrieval

### SD Card Management

- [x] **SDCD-01**: SD card status sensor (total/used/free space)
- [x] **SDCD-02**: Format SD card button
- [x] **SDCD-03**: Safely unmount SD card button
- [x] **SDCD-04**: Recording mode setting (continuous/motion/schedule/off)
- [x] **SDCD-05**: Recording schedule configuration (25 params)
- [x] **SDCD-06**: SD card recording list (by date/type)
- [x] **SDCD-07**: SD card recording calendar (RTGetSDRecordCalendar)
- [x] **SDCD-08**: SD card file download/playback via MediaSource

### Audio

- [ ] **AUDI-01**: Listen to camera audio stream (DRW channel 2, G.711 A-law decode)
- [ ] **AUDI-02**: Two-way talk (DRW channel 3, G.711 A-law encode + send)
- [ ] **AUDI-03**: Microphone on/off switch (RTSetVoiceEnable)
- [x] **AUDI-04**: Pure Python G.711 A-law codec (no external deps)
- [x] **AUDI-05**: Audio format auto-detection from DRW packet headers

### Camera Settings (Extended)

- [x] **CSET-01**: Extended IR/night vision settings (RTSetIrcutAttr -- 5 params: mode, sensitivity, timing)
- [x] **CSET-02**: IR mode select entity (auto/on/off/schedule)
- [x] **CSET-03**: Power frequency setting (50Hz/60Hz)
- [x] **CSET-04**: Device name setting (text entity)

### WiFi Configuration

- [x] **WIFI-01**: WiFi scan from HA (list available networks)
- [x] **WIFI-02**: WiFi connect to selected network (SSID + password)
- [x] **WIFI-03**: Current WiFi status sensor (SSID, signal strength)

### Network Settings

- [x] **NETW-01**: LAN network settings view (IP, mask, gateway, DNS)
- [x] **NETW-02**: DDNS settings

### User Management

- [x] **USER-01**: View current users (3 slots)
- [x] **USER-02**: Change password service (RTUserSetting)
- [x] **USER-03**: Add/remove secondary users

### Notifications & Alerts

- [x] **NOTF-01**: FTP upload settings (server, port, user, password, path)
- [x] **NOTF-02**: Email notification settings (SMTP server, recipients)
- [x] **NOTF-03**: Push notification registration (FCM token for MSG_SET_FCM_PUSH)

### Time & System

- [x] **SYST-01**: Time/timezone sync from HA (RTSynchMobileTime)
- [x] **SYST-02**: Device info sensor (firmware version, model, capabilities)
- [x] **SYST-03**: Factory reset button (with confirmation)
- [x] **SYST-04**: Reboot button (verify existing implementation)

### Snapshot & Recording

- [x] **SNAP-01**: Snapshot via PPPP (RTSnapJpeg -- not just RTSP)
- [x] **SNAP-02**: Manual recording trigger service

### Diagnostics

- [x] **DIAG-01**: Integration diagnostics (connection stats, protocol state, last errors)
- [x] **DIAG-02**: Camera capability dump in diagnostics

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
| Cloud account system | Camera has no cloud accounts -- all P2P |
| Android/iOS app | HA-only integration |
| QR code sharing | HA has its own device sharing model |
| Local video playback in HA | HA doesn't support custom media players |
| Direct firmware update | Too risky without manufacturer support |
| Multi-brand P2P support | Only PNZEO/MTCam (CS2 Network), not TUTK |
| Video recording in HA | Use SD card recording or HA's native recording |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CONN-01 | Phase 1 | Complete |
| CONN-02 | Phase 1 | Complete |
| CONN-03 | Phase 1 | Complete |
| CONN-04 | Phase 3 | Complete |
| CONN-05 | Phase 1 | Complete |
| CONF-01 | Phase 6 | Pending |
| CONF-02 | Phase 6 | Pending |
| CONF-03 | Phase 6 | Pending |
| CONF-04 | Phase 6 | Pending |
| ALRM-01 | Phase 2 | Complete |
| ALRM-02 | Phase 2 | Complete |
| ALRM-03 | Phase 2 | Complete |
| ALRM-04 | Phase 2 | Complete |
| ALRM-05 | Phase 3 | Complete |
| ALRM-06 | Phase 3 | Complete |
| ALRM-07 | Phase 2 | Complete |
| ALRM-08 | Phase 2 | Complete |
| ALRM-09 | Phase 2 | Complete |
| SDCD-01 | Phase 3 | Complete |
| SDCD-02 | Phase 4 | Complete |
| SDCD-03 | Phase 4 | Complete |
| SDCD-04 | Phase 4 | Complete |
| SDCD-05 | Phase 4 | Complete |
| SDCD-06 | Phase 4 | Complete |
| SDCD-07 | Phase 4 | Complete |
| SDCD-08 | Phase 4 | Complete |
| AUDI-01 | Phase 5 | Pending |
| AUDI-02 | Phase 5 | Pending |
| AUDI-03 | Phase 5 | Pending |
| AUDI-04 | Phase 5 | Complete |
| AUDI-05 | Phase 5 | Complete |
| CSET-01 | Phase 2 | Complete |
| CSET-02 | Phase 2 | Complete |
| CSET-03 | Phase 2 | Complete |
| CSET-04 | Phase 2 | Complete |
| WIFI-01 | Phase 2 | Complete |
| WIFI-02 | Phase 2 | Complete |
| WIFI-03 | Phase 2 | Complete |
| NETW-01 | Phase 2 | Complete |
| NETW-02 | Phase 2 | Complete |
| USER-01 | Phase 2 | Complete |
| USER-02 | Phase 2 | Complete |
| USER-03 | Phase 2 | Complete |
| NOTF-01 | Phase 2 | Complete |
| NOTF-02 | Phase 2 | Complete |
| NOTF-03 | Phase 2 | Complete |
| SYST-01 | Phase 2 | Complete |
| SYST-02 | Phase 3 | Complete |
| SYST-03 | Phase 2 | Complete |
| SYST-04 | Phase 2 | Complete |
| SNAP-01 | Phase 2 | Complete |
| SNAP-02 | Phase 2 | Complete |
| DIAG-01 | Phase 3 | Complete |
| DIAG-02 | Phase 3 | Complete |

**Coverage:**
- v1 requirements: 54 total
- Mapped to phases: 54
- Unmapped: 0

---
*Requirements defined: 2026-04-02*
*Last updated: 2026-04-02 after roadmap creation*
