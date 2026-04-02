# Feature Landscape

**Domain:** IP camera Home Assistant custom component (full control)
**Researched:** 2026-04-02

## Table Stakes

Features users expect when installing a camera integration. Missing = product feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Motion detection on/off | Every camera app has this toggle | Low | `set_alarm.cgi?motion_armed=0/1`. Switch entity. |
| Motion detection notifications | Users automate on motion | Low | EventEntity with `EventDeviceClass.MOTION`. Trigger automations. |
| Motion sensitivity control | Users tune false alarms | Low | Select entity: high/medium/low/ultra-low. `set_alarm.cgi?motion_sensitivity=0-3`. |
| SD card status (capacity) | "How full is my SD card?" | Low | Sensor entity from `get_status.cgi` response. Diagnostic. |
| SD card format | Users need to clear space | Low | Already implemented (button entity). |
| Recording mode control | Continuous vs motion-triggered vs off | Low | Select entity: off/continuous/alarm/schedule. `set_record_param.cgi?rec_mode=X`. |
| Connection status indicator | "Is my camera online?" | Low | Binary sensor. Already have `coordinator._pppp_available`. |
| Device info (firmware, model) | "What version is running?" | Low | Sensor entity from `check_user.cgi` response. Already in `_capabilities`. |
| Night vision / IR mode | Auto/on/off IR control | Low | Select entity with `RTSetIrcutAttr` params. 3 modes. |
| Reboot from HA | Users expect device control | Low | Already implemented (button entity). |

## Differentiators

Features that set this integration apart from generic RTSP-only solutions. Not expected, but valued.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Two-way audio (listen) | Hear what's happening at camera | High | DRW channel 2 audio stream. Requires G.711 codec. Unique to this integration -- no other HA component can do this for PPPP cameras. |
| Two-way audio (talk) | Talk to people through camera | High | DRW channel 3. Send PCM/A-law audio. Makes this a true intercom. |
| SD card recording browser | Browse/download recordings from HA | Medium | MediaSource integration. List by date, download files. Only Reolink does this among IP cam integrations. |
| Full alarm configuration (33 params) | Fine-tune detection zones, schedules | Medium | All 33 RTAlarmSetting params as entities. No other integration exposes this level of control. |
| WiFi configuration from HA | Change camera WiFi without app | Medium | Scan networks + configure SSID/password. Useful when the Chinese app is uninstalled. |
| User management | Change passwords, manage 3 user slots | Low | Service call. Important for security-conscious users who want to change default 8888 password. |
| SD card recording calendar | Visual calendar of recorded days | Medium | `RTGetSDRecordCalendar` returns day bitmask. Calendar sensor attribute. |
| Sound detection alarm | Alert on sound, not just motion | Low | `set_alarm.cgi` sound alarm params. Switch entity. |
| FTP upload to NAS | Auto-upload snapshots to NAS | Low | `set_ftp.cgi` configuration. Text + number entities for FTP server. |
| Email notifications from camera | Camera sends email on alarm | Low | `set_mail.cgi` configuration. Not common in HA -- usually users prefer HA automations. |
| Factory reset from HA | Emergency device recovery | Low | Already implemented (button entity). |

## Anti-Features

Features to explicitly NOT build.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Cloud account system | Camera has no cloud accounts. All P2P. | Keep it local-only. |
| Video playback in HA dashboard | HA has no custom media player for proprietary protocols. RTStartPlayBack would need custom frontend. | List SD card files in MediaSource. Provide download. User plays in VLC. |
| Firmware update from HA | Too risky without manufacturer support. Could brick camera. | Show firmware version as diagnostic sensor. User updates via original app if needed. |
| QR code sharing | HA has its own sharing model (users, permissions). | Not needed. |
| DDNS configuration | Users typically handle DDNS at router level, not per-camera. | Expose as config entity if user requests, but defer. |
| Always-on audio monitoring | Continuous audio recording is a privacy concern and resource hog on Pi5. | On-demand audio via service call. User triggers listen/talk. |
| Cloud relay as primary path | Cloud relay adds latency and depends on Chinese servers. | LAN-first, cloud relay only for port discovery fallback. Already implemented correctly. |
| SmartConfig provisioning | Only needed for initial camera WiFi setup. Requires UDP broadcast of WiFi password in cleartext. Security risk. | Document how to use original app for initial setup. HA integration assumes camera is already on WiFi. |

## Feature Dependencies

```
Motion detection switch --> Motion detection binary_sensor (needs alarm status data)
Motion detection binary_sensor --> Motion EventEntity (events fire when binary_sensor changes)
SD card format button --> SD card status sensor (show capacity before/after)
Recording mode select --> SD card recording browser (need recordings to browse)
Alarm settings (33 params) --> Alarm CGI get/set (need get_alarm.cgi parser first)
FTP settings --> FTP CGI get/set (need get_ftp.cgi parser first)
Email settings --> Email CGI get/set (need get_mail.cgi parser first)
WiFi configuration --> WiFi scan results (scan first, then configure)
Two-way audio listen --> DRW channel 2 handler + G.711 decoder
Two-way audio talk --> DRW channel 3 handler + G.711 encoder
Two-way audio talk --> Two-way audio listen (need audio infrastructure first)
```

## MVP Recommendation

For the first milestone of full feature parity, prioritize:

1. **Motion detection on/off + sensitivity** (table stakes, low complexity)
2. **Motion detection binary_sensor + EventEntity** (table stakes, enables automations)
3. **SD card status sensor** (table stakes, low complexity)
4. **Recording mode control** (table stakes, low complexity)
5. **Night vision / IR mode select** (table stakes, low complexity)
6. **Connection status binary_sensor** (table stakes, already have data)
7. **Device info sensors** (table stakes, already have data)

Defer:
- **Two-way audio**: High complexity, needs Wireshark capture first
- **SD card MediaSource**: Medium complexity, can add in second pass
- **FTP/email settings**: Low value (users prefer HA automations), defer to last
- **WiFi configuration**: Medium complexity, rarely needed after initial setup

## Sources

- Decompiled MTCam HD APK: RTNativeCaller.java (70+ JNI methods)
- [HA Camera Entity Docs](https://developers.home-assistant.io/docs/core/entity/camera/)
- [HA Event Entity Docs](https://developers.home-assistant.io/docs/core/entity/event/)
- [HA Binary Sensor Docs](https://www.home-assistant.io/integrations/binary_sensor/)
- [Reolink integration](https://www.home-assistant.io/integrations/reolink/) -- reference for SD card media browsing
- [IP Camera CGI SDK v2.1](https://corz.org/windows/software/oodlecam/files/IP%20Camera%20SDK%20Commands%20v2.1.html)
