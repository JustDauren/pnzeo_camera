# External Integrations

**Analysis Date:** 2026-04-02

## APIs & External Services

**Cloud P2P Relay (Port Discovery Only):**
- Service: AWS EC2 P2P relay nodes
- What it's used for: One-time UDP query to discover camera's LAN DRW port
  - Query timeout: 3 seconds (CLOUD_TIMEOUT)
  - Fallback: LAN-only discovery if cloud unreachable
- Servers: `54.186.48.247:32100`, `54.191.3.239:32100`
- SDK/Client: Native Python `socket` module (UDP)
- Auth: Device UID (PPRT format encoded from device_id)
- Implementation: `pppp_client.py` → `_cloud_discover_port()`
- Data: Camera stays 100% on LAN after port discovery

**Camera Web Interface:**
- Service: HTTP CGI on camera (via DRW PPPP tunnel)
- What it's used for: Camera control (brightness, resolution, PTZ, reboot, etc.)
- Implementation: `pppp_client.py` → `_send_cgi()` / `build_drw_cgi()`
- Data format: CGI URL queries wrapped in DRW packets

## Data Storage

**No databases used** - Integration is stateless except for:
- Home Assistant entity state (managed by HA core)
- Camera parameters cached in `PNZEOClient._camera_params` (dict)
- Client connection state in `PNZEOClient` instance variables

**Camera-side storage:**
- SD card recording (managed by camera firmware, not this integration)
- Camera parameters (firmware-stored)
- Presets (16 PTZ presets, 0-15)

**File Storage:**
- None - No files created or managed by this integration

**Caching:**
- Camera state cached in `self._camera_params` (dict)
- Capabilities cached in `self._capabilities` (dict from login response)
- Updated every 60 seconds via coordinator poll

## Authentication & Identity

**Auth Provider:**
- Custom camera authentication
- Credentials: `username` + `password` (plain text over LAN P2P tunnel)
- Default: username="admin", password="8888"
- Implementation: `pppp_client.py` → `_cgi_login()` / `login()`
- Session: CGI login via DRW, credentials cached in PNZEODevice

**Device Identity:**
- Device ID (optional): PPRT-format UID for cloud port discovery
  - Encoded in `pppp_packets.py` → `encode_uid()`
  - Format: "PPRT" + 4x00 + prefix(2) + suffix(10)
- Fallback: Use IP address if device_id not provided
- Storage: Home Assistant config entry

**Password Management:**
- Change password via service: `pnzeo_camera.change_password`
- New password synced to HA config entry after successful change
- Implementation: `__init__.py` → `handle_change_password()`

## Monitoring & Observability

**Error Tracking:**
- None - No external error tracking service
- Errors logged locally via Python logging module

**Logs:**
- Python logging to Home Assistant logs
- Logger: `pnzeo_camera` component
- Levels: DEBUG (detailed), INFO (connection status), WARNING (failures)
- Key events:
  - Cloud/LAN port discovery status
  - P2P handshake success/failure
  - CGI login success/failure
  - PPPP update failures (non-fatal — video continues via RTSP)

## CI/CD & Deployment

**Hosting:**
- None - Custom component for Home Assistant
- Users deploy via HACS (Home Assistant Community Store) or manual installation

**CI Pipeline:**
- None detected - No CI/CD configuration in repo

**Deployment:**
- Manual: Copy `pnzeo_camera/` to `custom_components/` directory
- HACS: Installable via HACS UI (via repository URL)

## Network Configuration

**Required Connectivity:**

**LAN (Always):**
- Camera IP:32108 (PPPP LAN search) - UDP
- Camera IP:8600 (DH protocol discovery) - UDP
- Camera IP:[dynamic DRW port] - UDP (P2P handshake and control)
- Camera IP:554 (RTSP video stream) - TCP/RTSP (via ffmpeg)

**WAN/Cloud (Optional - Port Discovery):**
- 54.186.48.247:32100 (AWS relay) - UDP, 3-second timeout
- 54.191.3.239:32100 (AWS relay) - UDP, 3-second timeout
- **Camera does NOT need internet** — only Pi5/Home Assistant makes one outbound UDP query
- Fallback: If cloud unavailable, uses LAN discovery (F130 LAN search)

**HTTP/HTTPS:**
- Camera HTTP interface (port 80, via CGI) - Accessible only through DRW P2P tunnel on LAN
- Configuration: `f"http://{device.host}"` — used for web UI link only

## Webhooks & Callbacks

**Incoming:**
- None - Integration is client-only, no webhook endpoints

**Outgoing:**
- None - Integration polls camera state, no external callbacks

## Environment Configuration

**Required env vars:**
- None - All configuration via Home Assistant UI or config entry

**Secrets location:**
- Home Assistant `secrets.yaml` (optional user choice)
- Credentials stored in Home Assistant config entry (encrypted by HA)
- Camera password stored in encrypted config entry

**Config entry fields:**
```python
{
    "host": "192.168.1.100",              # Camera IP
    "username": "admin",                  # Camera login
    "password": "8888",                   # Camera password
    "device_id": "PNZEO-XXXX-XXXXXX",    # Optional, for cloud discovery
    "rtsp_port": 554                      # Optional, RTSP stream port
}
```

## Integration Touch Points

**Home Assistant Entity Platforms:**
- Camera (RTSP stream with ffmpeg snapshot)
- Switch (IR LED, status LED indicators)
- Button (reboot, factory reset, snapshot)
- Number (brightness, contrast, RTSP port)
- Select (resolution, mirror mode)

**Home Assistant Services:**
- `pnzeo_camera.ptz_control` - Pan/tilt/zoom control
- `pnzeo_camera.goto_preset` - Move to saved preset (0-15)
- `pnzeo_camera.set_preset` - Save current position as preset
- `pnzeo_camera.send_command` - Raw PPPP command (msg_type 0-255)
- `pnzeo_camera.change_password` - Update camera password

**Data Update Coordinator:**
- Polls camera every 60 seconds (SCAN_INTERVAL in `coordinator.py`)
- Queries: `get_status()`, `get_camera_params()`
- Non-fatal failures: Returns cached state, logs debug message
- Reason: Video continues working via RTSP even if PPPP control unavailable

## Protocol Details

**PPPP (P2P Protocol):**
- Custom proprietary protocol (not HTTP-based)
- Three-layer stack:
  1. F1xx signaling - P2P handshake, UIDs, relay negotiation
  2. Relay bridging - Optional cloud relay for NAT traversal
  3. DRW packets - Command/response channel for CGI and control

**DRW (Data/Control packets):**
- Packet type 0xD0 (command), 0xD1 (response)
- Wrapped CGI command URLs (HTTP-like format)
- Responses parsed as JSON or key=value pairs
- Retry logic: Up to 25 retries, 0.3-second intervals

**CGI Commands Used:**
- `CGI_CHECK_USER` - Login verification
- `CGI_GET_PARAMS` - Fetch camera parameters
- `CGI_GET_STATUS` - Fetch camera status
- `CGI_CAMERA_CONTROL` - Set brightness, contrast, resolution, mirror
- `CGI_REBOOT` - Restart camera
- `CGI_FACTORY_RESET` - Reset to factory defaults
- `CGI_SNAPSHOT` - Capture image
- `CGI_SET_USER` - Change password
- `CGI_SET_ALARM` - Configure alarm settings

**RTSP Streaming:**
- Main stream: `/11`
- Sub stream (lower quality): `/12`
- Via ffmpeg (Home Assistant built-in stream component)

---

*Integration audit: 2026-04-02*
