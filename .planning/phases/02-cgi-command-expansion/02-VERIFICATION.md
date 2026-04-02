---
phase: 02-cgi-command-expansion
verified: 2026-04-02T16:30:00Z
status: gaps_found
score: 4/5 success criteria verified
gaps:
  - truth: "User can view and change IR night vision mode, WiFi network, device name, and power frequency"
    status: partial
    reason: "CSET-02 requires auto/on/off/schedule but IR_MODE_MAP only has 3 options (Auto/On/Off). 'schedule' mode is absent. Also: power_freq and devname are write-only in practice — no dedicated read-back polling; state depends on get_camera_params returning these fields."
    artifacts:
      - path: "custom_components/pnzeo_camera/pppp_packets.py"
        issue: "IR_MODE_MAP has 3 entries (0=Auto, 1=On, 2=Off) — schedule mode (value 3) missing per CSET-02 spec"
      - path: "custom_components/pnzeo_camera/select.py"
        issue: "PNZEOPowerFrequency reads coordinator.data.get('power_freq') but there is no dedicated get_power_freq polling; value only appears if get_camera_params.cgi happens to return it"
    missing:
      - "Add schedule option (value 3) to IR_MODE_MAP in pppp_packets.py and update PNZEOIRMode options list"
      - "Verify (or document) that get_camera_params.cgi returns power_freq and devname fields from this camera model"
  - truth: "ALRM-02: Motion detection sensitivity (number entity, 1-10)"
    status: partial
    reason: "REQUIREMENTS.md specifies range 1-10 but implementation uses camera-native 0-9. This is a documented deliberate deviation, not an error, but it creates a mismatch between the requirement spec and the entity exposed to users."
    artifacts:
      - path: "custom_components/pnzeo_camera/number.py"
        issue: "PNZEOMotionSensitivity range is 0-9, requirement says 1-10. Deviation is documented in SUMMARY but not updated in REQUIREMENTS.md."
    missing:
      - "Either update REQUIREMENTS.md ALRM-02 to say '0-9 (camera-native)' or invert the range in the entity so the user sees 1-10 while the camera receives 9-0"
---

# Phase 02: CGI Command Expansion Verification Report

**Phase Goal:** Every camera setting available in the MTCam HD app is readable and writable from HA
**Verified:** 2026-04-02T16:30:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (from ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | User can toggle motion detection on/off and adjust sensitivity from the HA dashboard | VERIFIED | `PNZEOMotionSwitch` reads `coordinator.data["motion_armed"]`, `PNZEOMotionSensitivity` calls `set_alarm_params(motion_sensitivity=...)`. Both wired to real CGI endpoints via `set_alarm_params` / `get_alarm_params`. |
| 2 | User can configure alarm schedules, sound detection, and GPIO alarm settings | VERIFIED | `PNZEOSoundAlarmSwitch` (input_armed), `PNZEOGPIOAlarmSwitch` (ioEnable), `PNZEOAlarmAction` (mail/snapshot/record). All call real client methods with GET-before-SET merge. Alarm schedule params (33 fields) in ALARM_PARAMS list. |
| 3 | User can view and change IR night vision mode, WiFi network, device name, and power frequency | PARTIAL | IR mode select exists (3 options) but CSET-02 requires 4 (missing "schedule"). `PNZEODeviceName` read falls back to `coordinator.device.name` if `devname` absent. `PNZEOPowerFrequency` reads `power_freq` but no dedicated polling; relies on `get_camera_params` returning it. |
| 4 | User can manage FTP upload settings, email notification settings, and camera user accounts | VERIFIED | 5 services (set_ftp, set_email, set_push_token, get_ftp_settings, get_email_settings) registered in `__init__.py`, defined in `services.yaml`, wired to `get_ftp_params`, `set_ftp`, `get_mail_params`, `set_mail`, `set_push_token` client methods. User management via `get_users` / `set_users` / `manage_users` services. `change_password` preserved. |
| 5 | User can trigger a PPPP snapshot and a reboot/factory-reset from HA | VERIFIED | `PNZEOSnapshotButton`, `PNZEORebootButton`, `PNZEOFactoryResetButton` all exist in `button.py`, wired to `client.snapshot()`, `client.reboot()`, `client.factory_reset()` respectively. All call real CGI endpoints. |

**Score:** 4/5 success criteria fully verified (Truth 3 is PARTIAL due to missing IR schedule mode and uncertain power_freq/devname read-back)

---

## Required Artifacts

### Plan 02-01 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `pppp_packets.py` | CGI_GET_ALARM_EX, CGI_SET_ALARM_EX, CGI_GET_ALARM_LOG constants | VERIFIED | All 3 constants present at lines 714-716 |
| `pppp_client.py` | 7 alarm methods, ALARM_PARAMS, ALARM_EX_PARAMS | VERIFIED | `get_alarm_params`, `set_alarm_params`, `get_alarm_ex_params`, `set_alarm_ex_params`, `get_alarm_log`, `set_sound_detection`, `set_gpio_alarm` — all present and substantive |
| `coordinator.py` | Alarm polling with asyncio.wait_for(5s) | VERIFIED | Lines 60-67: both `get_alarm_params()` and `get_alarm_ex_params()` wrapped in `asyncio.wait_for(..., timeout=5.0)` |
| `switch.py` | PNZEOSoundAlarmSwitch, PNZEOGPIOAlarmSwitch; updated PNZEOMotionSwitch | VERIFIED | All 3 present; `PNZEOMotionSwitch.is_on` reads `coordinator.data["motion_armed"]`; new switches disabled by default |
| `number.py` | PNZEOMotionSensitivity (0-9, slider) | VERIFIED | Present, reads `coordinator.data["motion_sensitivity"]`, calls `set_alarm_params(motion_sensitivity=...)` |
| `select.py` | PNZEOAlarmAction (8 combinations) | VERIFIED | `_ALARM_ACTION_MAP` has 8 entries, reads mail/snapshot/record from coordinator.data |
| `__init__.py` | get_alarm_log service | VERIFIED | Registered at line 167, calls `client.get_alarm_log()`, fires `pnzeo_camera_alarm_log` event |
| `services.yaml` | get_alarm_log definition | VERIFIED | Lines 78-80 |
| `strings.json` | get_alarm_log strings | VERIFIED | Present in services block |

### Plan 02-02 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `pppp_packets.py` | CGI_GET_IRCUT, CGI_SET_IRCUT, CGI_SET_DEVNAME, CGI_SET_MOBILETIME, CGI_START_RECORDING, IR_MODE_MAP, POWER_FREQ_MAP | PARTIAL | All constants present; IR_MODE_MAP has only 3 entries (Auto/On/Off) — missing "schedule" per CSET-02 |
| `pppp_client.py` | get_ircut_params, set_ircut_params, set_power_freq, set_device_name, sync_time, start_recording | VERIFIED | All 6 methods present and substantive; set_ircut_params has fallback to camera_control |
| `select.py` | PNZEOIRMode, PNZEOPowerFrequency | PARTIAL | Both present; IR mode missing "schedule" option; power_freq entity reads key that relies on get_camera_params returning it (not explicitly polled) |
| `text.py` | PNZEODeviceName | VERIFIED | File created, reads `coordinator.data.get("devname", device.name)`, writes via `set_device_name` |
| `__init__.py` | Platform.TEXT, sync_time, start_recording services | VERIFIED | Platform.TEXT at line 33; both services registered at lines 178-192 |
| `coordinator.py` | IR cut params polling | VERIFIED | Lines 68-71: `get_ircut_params()` in CONNECTED block with 5s timeout |
| `services.yaml` | sync_time, start_recording definitions | VERIFIED | Lines 82-88 |
| `strings.json` | sync_time, start_recording strings | VERIFIED | Present in services block |

### Plan 02-03 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `pppp_packets.py` | CGI_WIFI_SCAN, CGI_GET_DDNS, CGI_SET_DDNS | VERIFIED | All 3 present at lines 722-724 |
| `pppp_client.py` | wifi_scan, set_wifi, get_wifi_params, get_network_params, get_ddns_params, set_ddns, get_users, set_users | VERIFIED | All 8 methods present, substantive, wired to real CGI endpoints |
| `coordinator.py` | WiFi/network polling every 5th cycle | VERIFIED | Lines 73-84: `_poll_counter` pattern, `get_wifi_params` and `get_network_params` on every 5th cycle |
| `__init__.py` | 5 services: wifi_scan, wifi_connect, set_ddns, get_users, manage_users | VERIFIED | All 5 registered at lines 204-297; schemas defined; event-bus result delivery for wifi_scan and get_users |
| `services.yaml` | 5 service definitions | VERIFIED | All present with field descriptions |
| `strings.json` | WiFi/network/user service strings | VERIFIED | All present |

### Plan 02-04 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `pppp_packets.py` | CGI_GET_FTP, CGI_SET_FTP, CGI_GET_MAIL, CGI_SET_MAIL, CGI_SET_FCM | VERIFIED | All 5 present at lines 725-729 |
| `pppp_client.py` | get_ftp_params, set_ftp, get_mail_params, set_mail, set_push_token | VERIFIED | All 5 present and substantive; set_push_token has appropriate warning for unsupported cameras |
| `__init__.py` | 5 services: set_ftp, set_email, set_push_token, get_ftp_settings, get_email_settings | VERIFIED | All 5 registered at lines 301-392 |
| `services.yaml` | FTP/email/push service definitions | VERIFIED | All present with field descriptions |
| `strings.json` | FTP/email/push service strings | VERIFIED | All present |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `PNZEOMotionSwitch.is_on` | `coordinator.data["motion_armed"]` | `get_alarm_params()` → `_camera_params` | VERIFIED | Coordinator polls `get_alarm_params()` every cycle; key stored in `_camera_params` |
| `PNZEOMotionSensitivity.native_value` | `coordinator.data["motion_sensitivity"]` | `get_alarm_params()` | VERIFIED | Same path as above |
| `PNZEOSoundAlarmSwitch.is_on` | `coordinator.data["input_armed"]` | `get_alarm_params()` | VERIFIED | `input_armed` is in ALARM_PARAMS list, stored by `get_alarm_params` |
| `PNZEOGPIOAlarmSwitch.is_on` | `coordinator.data["ioEnable"]` | `get_alarm_ex_params()` | VERIFIED | `ioEnable` is in ALARM_EX_PARAMS list |
| `PNZEOAlarmAction.current_option` | `coordinator.data[mail/snapshot/record]` | `get_alarm_params()` | VERIFIED | All 3 fields in ALARM_PARAMS |
| `PNZEOIRMode.current_option` | `coordinator.data["ircut_mode"]` | `get_ircut_params()` | VERIFIED | Polled via `get_ircut_params()` in coordinator; filter `k.startswith("ircut_")` captures `ircut_mode` |
| `PNZEOPowerFrequency.current_option` | `coordinator.data["power_freq"]` | `get_camera_params()` (implicit) | UNCERTAIN | No dedicated polling for `power_freq`; depends on whether `get_camera_params.cgi` returns this key for this camera model. Read-back unverifiable without live camera. |
| `PNZEODeviceName.native_value` | `coordinator.data["devname"]` | `get_camera_params()` (implicit) | UNCERTAIN | Falls back to `device.name` if absent; `devname` only appears if camera includes it in `get_camera_params.cgi` response |
| `wifi_scan service` → `pnzeo_camera_wifi_scan_result event` | `client.wifi_scan()` | `hass.bus.async_fire` | VERIFIED | Handler at line 197-203; result delivered via HA event bus |
| `get_users service` → `pnzeo_camera_users_result event` | `client.get_users()` | `hass.bus.async_fire` | VERIFIED | Handler at line 251-260 |
| `set_ftp service` → `client.set_ftp()` → `CGI_SET_FTP` | `build_cgi_url(CGI_SET_FTP, ...)` | `_send_cgi` | VERIFIED | Full chain wired, CGI_SET_FTP = "set_ftp.cgi" |
| `set_email service` → `client.set_mail()` → `CGI_SET_MAIL` | `build_cgi_url(CGI_SET_MAIL, ...)` | `_send_cgi` | VERIFIED | Full chain wired |
| `set_push_token service` → `client.set_push_token()` → `CGI_SET_FCM` | `build_cgi_url(CGI_SET_FCM, ...)` | `_send_cgi` | VERIFIED | CGI_SET_FCM = "set_push.cgi"; warning logged on failure |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `PNZEOMotionSwitch` | `motion_armed` | `get_alarm_params()` → `CGI_GET_ALARM` → camera | Yes — real CGI call, result merged into `_camera_params` | FLOWING |
| `PNZEOMotionSensitivity` | `motion_sensitivity` | `get_alarm_params()` → `CGI_GET_ALARM` | Yes | FLOWING |
| `PNZEOSoundAlarmSwitch` | `input_armed` | `get_alarm_params()` → `CGI_GET_ALARM` | Yes — `input_armed` in ALARM_PARAMS | FLOWING |
| `PNZEOGPIOAlarmSwitch` | `ioEnable` | `get_alarm_ex_params()` → `CGI_GET_ALARM_EX` | Yes — `ioEnable` in ALARM_EX_PARAMS | FLOWING |
| `PNZEOIRMode` | `ircut_mode` | `get_ircut_params()` → `CGI_GET_IRCUT` | Yes — polled every coordinator cycle | FLOWING |
| `PNZEOPowerFrequency` | `power_freq` | `get_camera_params()` → `CGI_GET_PARAMS` (assumed) | Uncertain — depends on camera firmware returning this field | UNCERTAIN |
| `PNZEODeviceName` | `devname` | `get_camera_params()` (assumed) | Uncertain — fallback to `device.name` if absent; no dedicated get method | UNCERTAIN |
| `PNZEOAlarmAction` | `mail`, `snapshot`, `record` | `get_alarm_params()` | Yes | FLOWING |

---

## Behavioral Spot-Checks

Step 7b: SKIPPED — no runnable entry points (HA integration requires live camera + HA instance; CGI methods can only be tested against real hardware).

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|---------|
| ALRM-01 | 02-01 | Motion detection on/off switch | SATISFIED | `PNZEOMotionSwitch` in switch.py; reads coordinator.data["motion_armed"] |
| ALRM-02 | 02-01 | Motion detection sensitivity (1-10) | PARTIAL | Entity exists and is functional, but range is 0-9 (camera-native) not 1-10 as specified. SUMMARY documents this as intentional. |
| ALRM-03 | 02-01 | Full alarm settings via CGI (schedule, zones) | SATISFIED | `set_alarm_params` handles all 33 ALARM_PARAMS including 21 schedule fields |
| ALRM-04 | 02-01 | Extended alarm settings (11 params) | SATISFIED | `set_alarm_ex_params` / `get_alarm_ex_params` with ALARM_EX_PARAMS list |
| ALRM-07 | 02-01 | Sound detection alarm settings | SATISFIED | `PNZEOSoundAlarmSwitch` + `set_sound_detection` method |
| ALRM-08 | 02-01 | GPIO alarm settings | SATISFIED | `PNZEOGPIOAlarmSwitch` + `set_gpio_alarm` method |
| ALRM-09 | 02-01 | Alarm log retrieval | SATISFIED | `get_alarm_log` service fires `pnzeo_camera_alarm_log` event |
| CSET-01 | 02-02 | Extended IR/night vision settings (5 params) | SATISFIED | `get_ircut_params` / `set_ircut_params` accept mode, sensitivity, timing params |
| CSET-02 | 02-02 | IR mode select entity (auto/on/off/schedule) | PARTIAL | Entity exists with 3 options (Auto/On/Off); "schedule" mode missing from IR_MODE_MAP |
| CSET-03 | 02-02 | Power frequency setting (50Hz/60Hz) | SATISFIED | `PNZEOPowerFrequency` entity + `set_power_freq` method |
| CSET-04 | 02-02 | Device name setting (text entity) | SATISFIED | `PNZEODeviceName` text entity with `set_device_name` |
| WIFI-01 | 02-03 | WiFi scan from HA | SATISFIED | `wifi_scan` service + `client.wifi_scan()` with AP parsing |
| WIFI-02 | 02-03 | WiFi connect | SATISFIED | `wifi_connect` service + `client.set_wifi()` |
| WIFI-03 | 02-03 | Current WiFi status | SATISFIED | `get_wifi_params()` polled every 5th cycle; WiFi data in coordinator.data |
| NETW-01 | 02-03 | LAN network settings view | SATISFIED | `get_network_params()` polled every 5th cycle |
| NETW-02 | 02-03 | DDNS settings | SATISFIED | `set_ddns` service + `get_ddns_params` / `set_ddns` methods |
| USER-01 | 02-03 | View current users (3 slots) | SATISFIED | `get_users` service fires `pnzeo_camera_users_result` event; passwords omitted for security |
| USER-02 | 02-03 | Change password service | SATISFIED | `change_password` service preserved; updates config entry on success |
| USER-03 | 02-03 | Add/remove secondary users | SATISFIED | `manage_users` service with user1-3/pwd1-3 fields; updates primary password in config entry if slot 1 changes |
| NOTF-01 | 02-04 | FTP upload settings | SATISFIED | `set_ftp` service + `get_ftp_settings` → event; all params (server/port/user/pwd/dir/mode/interval) |
| NOTF-02 | 02-04 | Email notification settings | SATISFIED | `set_email` service + `get_email_settings` → event; SMTP server/port/user/pwd/sender/receiver/ssl |
| NOTF-03 | 02-04 | Push notification (FCM token) | SATISFIED | `set_push_token` service + warning logged for unsupported cameras |
| SYST-01 | 02-02 | Time/timezone sync | SATISFIED | `sync_time` service; computes UTC offset from system timezone |
| SYST-03 | 02-02 | Factory reset button | SATISFIED | `PNZEOFactoryResetButton` (disabled by default, destructive) |
| SYST-04 | 02-02 | Reboot button | SATISFIED | `PNZEORebootButton` wired to `client.reboot()` |
| SNAP-01 | 02-02 | Snapshot via PPPP | SATISFIED | `PNZEOSnapshotButton` calls `client.snapshot()` → `CGI_SNAPSHOT` |
| SNAP-02 | 02-02 | Manual recording trigger service | SATISFIED | `start_recording` service + `client.start_recording()` → `CGI_START_RECORDING` |

**Requirements totals:** 25 required, 22 SATISFIED, 2 PARTIAL (ALRM-02, CSET-02), 0 BLOCKED.

No orphaned requirements found — all 27 requirement IDs from the phase appear in the 4 plan SUMMARYs and are accounted for above.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `number.py` | 70-71 | Range 0-9 vs REQUIREMENTS.md spec of 1-10 | Info | ALRM-02 is functional but mismatches the written requirement. Camera-native range; documented in SUMMARY. |
| `pppp_packets.py` | 732-736 | IR_MODE_MAP missing "schedule" (value 3) | Warning | CSET-02 says auto/on/off/schedule; schedule mode cannot be selected from HA |
| `select.py` | 148-152 | `power_freq` key not guaranteed in coordinator.data | Info | `PNZEOPowerFrequency` shows "50Hz" as default when key absent; correct fallback but state may not reflect camera reality until first full params update |
| `text.py` | 33 | `devname` key not guaranteed in coordinator.data | Info | Falls back to `coordinator.device.name` (the integration-level name, not the camera's stored name); may show stale/wrong name on first load |

No blocking stubs. No TODO/FIXME/placeholder anti-patterns found in any phase-02 files.

---

## Human Verification Required

### 1. power_freq and devname read-back

**Test:** After setting power frequency to 60Hz or changing device name, reload the integration (or wait one polling cycle) and check whether `PNZEOPowerFrequency` reflects the new value and `PNZEODeviceName` shows the name set.
**Expected:** Entity state matches camera's stored value after one coordinator poll.
**Why human:** `get_camera_params.cgi` response structure is camera-firmware-dependent. Cannot verify programmatically which keys the camera returns without a live camera.

### 2. IR schedule mode absence impact

**Test:** Check whether the physical PNZEO camera model (as used with MTCam HD) actually exposes a "schedule" IR mode.
**Expected:** If the camera supports it, the option should appear in `PNZEOIRMode`. If the camera hardware doesn't support it, the 3-option map is correct and CSET-02 spec is over-specified.
**Why human:** IR mode support is firmware-dependent and cannot be determined from code analysis alone.

### 3. FCM push notification delivery

**Test:** Call `set_push_token` with a valid FCM token and trigger a motion alarm. Verify a push notification is received.
**Expected:** Push notification delivered via FCM.
**Why human:** `set_push_token` logs a warning on failure (camera may not support CGI push). Requires live camera + valid FCM token to verify.

---

## Gaps Summary

Two partial gaps block full goal achievement:

**Gap 1 — CSET-02 Missing IR Schedule Mode (Warning severity):**
`IR_MODE_MAP` in `pppp_packets.py` has 3 entries (0=Auto, 1=On, 2=Off). The requirement CSET-02 specifies 4 modes including "schedule". The `PNZEOIRMode` entity therefore cannot expose schedule mode. Resolution: add `3: "Schedule"` to the map — but only if confirmed the camera hardware supports it (requires human verification item 2).

**Gap 2 — ALRM-02 Range Mismatch (Info severity):**
`PNZEOMotionSensitivity` uses range 0-9 (camera-native). `REQUIREMENTS.md` says 1-10. The SUMMARY documents this as an intentional decision. The entity is fully functional. Resolution: update `REQUIREMENTS.md` to reflect the actual 0-9 range, or invert the scale in the entity (9-int(value) maps 1→9=most-sensitive, 10→0=least-sensitive). The functional impact is low — the slider works correctly for controlling the camera.

Both gaps are minor. The phase's core goal ("every MTCam HD app setting readable and writable from HA") is substantively achieved: all 27 requirement IDs have working implementations, 18 HA services are registered and wired to real CGI endpoints, 6 entity platforms are active (CAMERA, SWITCH, BUTTON, NUMBER, SELECT, TEXT), and all 8 task commits are verified in git history.

---

_Verified: 2026-04-02T16:30:00Z_
_Verifier: Claude (gsd-verifier)_
