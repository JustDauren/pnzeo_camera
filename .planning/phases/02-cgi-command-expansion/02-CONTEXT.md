# Phase 2: CGI Command Expansion - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase — discuss skipped)

<domain>
## Phase Boundary

Every camera setting available in the MTCam HD app is readable and writable from HA. This covers 27 requirements: alarm settings (ALRM-01..04,07..09), camera settings (CSET-01..04), WiFi (WIFI-01..03), network (NETW-01..02), user management (USER-01..03), notifications (NOTF-01..03), system (SYST-01,03,04), and snapshot (SNAP-01..02).

All new commands follow the existing proven pattern: `build_cgi_url(endpoint, params)` → `_send_cgi(url)` → parse response.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — CGI command expansion phase. Every new CGI endpoint follows the identical `_send_cgi()` pattern already proven in the codebase.

Key patterns from existing code:
- `pppp_packets.py:build_cgi_url()` constructs CGI URL with auth params
- `pppp_client.py:_send_cgi()` wraps URL in DRW packet and sends via PPPP
- Response parsing: `result=0` for success, key=value pairs or JSON
- Entity types: switch (on/off), number (range), select (options), button (action), text (string)

CGI endpoints from decompiled app (PNZEO_W8_REVERSE.md):
- Alarm: set_alarm.cgi, get_alarm_param.cgi, set_alarm_ex.cgi, get_alarm_ex.cgi
- IR: camera_control.cgi (param=14), get_ircut_params.cgi (if exists)
- WiFi: wifi_scan.cgi, set_wifi.cgi, get_wifi_params.cgi
- Network: get_network.cgi, set_network.cgi, set_ddns.cgi
- User: set_user.cgi, get_user_info.cgi
- FTP: set_ftp.cgi, get_ftp_params.cgi
- Email: set_mail.cgi, get_mail_params.cgi
- Time: set_datetime.cgi, get_datetime_params.cgi, synch_mobile_time.cgi
- System: reboot.cgi, factory_reset.cgi, get_factory_param.cgi
- Snapshot: snapshot.cgi
- Recording: set_record_mode.cgi, get_record_mode.cgi, set_record_sch.cgi

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `pppp_client.py:_send_cgi()` — proven CGI command sender
- `pppp_packets.py:build_cgi_url()` — CGI URL builder with auth
- `pppp_packets.py:parse_cgi_response()` — response parser
- `entity.py:PNZEOEntity` — base entity class
- `switch.py`, `number.py`, `select.py`, `button.py` — existing entity platforms

### Established Patterns
- Entity registration in `__init__.py:PLATFORMS` list
- Coordinator data dict stores camera state
- Entity reads state from `coordinator.data`
- Entity writes via `client.method()` then `coordinator.async_request_refresh()`

### Integration Points
- New CGI methods → add to `pppp_client.py`
- New entities → add platform files or extend existing ones
- New data → add to `coordinator.py:_build_data()` or `_async_update_data()`
- New strings → add to `strings.json` and `translations/`

</code_context>

<specifics>
## Specific Ideas

No specific requirements — infrastructure phase. All CGI endpoints documented in decompiled app docs.

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped.

</deferred>
