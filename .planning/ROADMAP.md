# Roadmap: PNZEO Camera Full HA Integration

## Overview

This roadmap takes the PNZEO Camera integration from its current working state (RTSP video, PTZ, basic settings) to full feature parity with the MTCam HD Android app. The path follows a strict dependency chain: connection reliability first (foundation for all PPPP communication), then CGI command expansion (every new feature reuses the proven `_send_cgi()` pattern), then HA entity creation (consuming CGI data), then SD card browsing (complex MediaSource), then two-way audio (highest protocol uncertainty), and finally config flow polish (user-facing quality gate).

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Connection Reliability** - Bulletproof P2P connection with auto-reconnect, watchdog, and state machine
- [ ] **Phase 2: CGI Command Expansion** - All camera settings/controls via CGI commands (alarm, IR, WiFi, users, FTP, email, time, snapshot)
- [ ] **Phase 3: Event & Sensor Entities** - HA entities exposing camera state (motion binary_sensor, alarm events, device info, connection status, diagnostics)
- [ ] **Phase 4: SD Card Features** - Full SD card management with recording browsing via MediaSource
- [ ] **Phase 5: Two-Way Audio** - Listen from camera and talk to camera over DRW channels with pure Python G.711 codec
- [ ] **Phase 6: Config Flow & Polish** - Auto-discovery, password validation, capability detection, and setup UX

## Phase Details

### Phase 1: Connection Reliability
**Goal**: The PPPP connection never silently dies and always recovers on its own
**Depends on**: Nothing (first phase)
**Requirements**: CONN-01, CONN-02, CONN-03, CONN-05
**Success Criteria** (what must be TRUE):
  1. Camera reconnects automatically after network interruption without user action (within 30s for LAN, 60s for cloud)
  2. Keepalive failures are logged with timestamps and the watchdog restarts the connection task
  3. Disconnecting the camera's ethernet and reconnecting results in automatic recovery with no zombie sockets
  4. Protocol state transitions are logged and state is queryable via coordinator data
**Plans**: TBD

### Phase 2: CGI Command Expansion
**Goal**: Every camera setting available in the MTCam HD app is readable and writable from HA
**Depends on**: Phase 1
**Requirements**: ALRM-01, ALRM-02, ALRM-03, ALRM-04, ALRM-07, ALRM-08, ALRM-09, CSET-01, CSET-02, CSET-03, CSET-04, WIFI-01, WIFI-02, WIFI-03, NETW-01, NETW-02, USER-01, USER-02, USER-03, NOTF-01, NOTF-02, NOTF-03, SYST-01, SYST-03, SYST-04, SNAP-01, SNAP-02
**Success Criteria** (what must be TRUE):
  1. User can toggle motion detection on/off and adjust sensitivity from the HA dashboard
  2. User can configure alarm schedules, sound detection, and GPIO alarm settings
  3. User can view and change IR night vision mode, WiFi network, device name, and power frequency
  4. User can manage FTP upload settings, email notification settings, and camera user accounts
  5. User can trigger a PPPP snapshot and a reboot/factory-reset from HA
**Plans**: TBD

### Phase 3: Event & Sensor Entities
**Goal**: Camera state is visible in HA as real-time sensors, binary sensors, and event entities
**Depends on**: Phase 2
**Requirements**: CONN-04, ALRM-05, ALRM-06, SDCD-01, SYST-02, DIAG-01, DIAG-02
**Success Criteria** (what must be TRUE):
  1. A binary_sensor shows whether the camera is currently connected (updates within one polling cycle)
  2. A binary_sensor shows active motion detection state (on when motion detected)
  3. An EventEntity fires HA events on motion/GPIO/sound alarm triggers that can be used in automations
  4. Sensors display SD card capacity (total/used/free) and device info (firmware, model)
  5. Integration diagnostics page shows connection stats, protocol state, last errors, and full capability dump
**Plans**: TBD

### Phase 4: SD Card Features
**Goal**: Users can manage SD card recordings and browse/download files from HA
**Depends on**: Phase 2, Phase 3
**Requirements**: SDCD-02, SDCD-03, SDCD-04, SDCD-05, SDCD-06, SDCD-07, SDCD-08
**Success Criteria** (what must be TRUE):
  1. User can format or safely unmount the SD card via button entities in HA
  2. User can set recording mode (continuous/motion/schedule/off) and configure the recording schedule
  3. User can browse SD card recordings by date in the HA Media Browser (MediaSource integration)
  4. User can download individual recording files from the camera through HA
**Plans**: TBD

### Phase 5: Two-Way Audio
**Goal**: Users can listen to camera audio and talk through the camera from HA
**Depends on**: Phase 1
**Requirements**: AUDI-01, AUDI-02, AUDI-03, AUDI-04, AUDI-05
**Success Criteria** (what must be TRUE):
  1. User can listen to live camera audio from the HA dashboard (DRW channel 2 decoded to playable audio)
  2. User can send audio to the camera speaker via a service call (DRW channel 3)
  3. User can toggle the camera microphone on/off via a switch entity
  4. Audio works without any external Python dependencies (pure Python G.711 A-law codec)
**Plans**: TBD

### Phase 6: Config Flow & Polish
**Goal**: New users can set up the integration in under 2 minutes with auto-discovery and validation
**Depends on**: Phase 2
**Requirements**: CONF-01, CONF-02, CONF-03, CONF-04
**Success Criteria** (what must be TRUE):
  1. Config flow auto-discovers cameras on LAN and presents a list for selection
  2. User can manually enter a UID as fallback when auto-discovery does not find the camera
  3. Config flow validates the password during setup and shows a clear error if wrong
  4. Detected capabilities determine which entities are created (no dead entities for unsupported features)
**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Connection Reliability | 0/0 | Not started | - |
| 2. CGI Command Expansion | 0/0 | Not started | - |
| 3. Event & Sensor Entities | 0/0 | Not started | - |
| 4. SD Card Features | 0/0 | Not started | - |
| 5. Two-Way Audio | 0/0 | Not started | - |
| 6. Config Flow & Polish | 0/0 | Not started | - |
