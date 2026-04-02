# Architecture

**Analysis Date:** 2026-04-02

## Pattern Overview

**Overall:** Home Assistant custom component with layered async architecture. Uses Home Assistant's platform/coordinator pattern for entity management, coupled with a proprietary PPPP P2P protocol implementation for camera control.

**Key Characteristics:**
- **Dual-path streaming:** RTSP over local TCP for video (handled by HA built-in), PPPP UDP for control commands
- **Cloud-minimal design:** Cloud queries only for port discovery (1 UDP), all data stays LAN-bound
- **Async-first:** Full asyncio with no blocking I/O; proper task lifecycle management
- **Coordinator-based state:** Single `PNZEOCoordinator` updates every 60 seconds; if PPPP drops, RTSP video keeps working
- **Protocol layering:** Three independent layers (F1xx signaling → DRW data → CGI commands)

## Layers

**Protocol Layer (`pppp_client.py`, `pppp_packets.py`):**
- Purpose: Implement PPPP P2P handshake and DRW CGI command protocol
- Location: `pppp_client.py`, `pppp_packets.py`
- Contains: UDP transport management, socket handling, packet encoding/decoding, F1xx signaling, DRW command/response parsing
- Depends on: Python stdlib (`asyncio`, `socket`, `struct`), no external deps
- Used by: `PNZEODevice`, `PNZEOCoordinator`

**Device Layer (`device.py`):**
- Purpose: Wrap camera credentials and RTSP URLs; thin facade
- Location: `device.py`
- Contains: RTSP stream URL generation, device metadata (name, unique_id)
- Depends on: `PNZEOClient` from protocol layer
- Used by: `PNZEOCoordinator`, all platform entities

**Coordination Layer (`coordinator.py`):**
- Purpose: Poll camera state (get_status, get_camera_params) every 60s; handle PPPP connection lifecycle
- Location: `coordinator.py`
- Contains: Home Assistant `DataUpdateCoordinator` subclass; graceful degradation (video still works if PPPP fails)
- Depends on: HA's `update_coordinator`, `PNZEODevice`
- Used by: All platform entities (camera, switch, button, number, select)

**Entity Platforms (`camera.py`, `switch.py`, `button.py`, `number.py`, `select.py`, `entity.py`):**
- Purpose: HA entity types for UI exposure and user interaction
- Location: Platform-specific modules + base class in `entity.py`
- Contains: Entity property state, async_turn_on/off/set_value handlers, UI metadata (icons, names, ranges)
- Depends on: HA platform classes, `PNZEOCoordinator`
- Used by: Home Assistant UI/automation engine

**Integration Entry Point (`__init__.py`):**
- Purpose: Setup/unload hook; service registration for PTZ and custom commands
- Location: `__init__.py`
- Contains: Entry lifecycle, platform forwarding, service handlers for ptz_control, goto_preset, set_preset, send_command, change_password
- Depends on: All layers above, HA config_entries API
- Used by: Home Assistant only (entry point)

**Configuration (`config_flow.py`, `pppp_discovery.py`):**
- Purpose: Discovery and credential collection
- Location: `config_flow.py` (HA config flow), `pppp_discovery.py` (LAN discovery logic)
- Contains: DH/PPPP UDP broadcast discovery, RTSP port check, manual IP entry
- Depends on: HA config_entries, `PNZEOClient` for login test
- Used by: HA setup wizard only

## Data Flow

**Connection Sequence:**

1. **Port Discovery Phase:**
   - `PNZEOClient._do_connect()` calls `_cloud_discover_port()` (1 UDP query to P2P server at 54.186.48.247:32100 or 54.191.3.239:32100)
   - Cloud responds with camera's DRW port (LAN-side)
   - Fallback: `_lan_discover_port()` sends F130 to camera, gets port from response

2. **P2P Handshake Phase:**
   - Create UDP socket
   - Send F141 punch packets (12x @ 150ms intervals) to DRW port
   - Each 3rd punch includes keepalive F1E0
   - Wait for F142 P2P_RDY or F141 response from camera
   - Send keepalive burst (8x @ 150ms) to establish session

3. **CGI Authentication Phase:**
   - Build CGI URL: `"check_user.cgi?username=...&password=...&json=1"`
   - Wrap in DRW packet (D0 type), send with seq number
   - Parse JSON response, populate `_capabilities`

4. **Operational Phase:**
   - Every 60s: `coordinator.async_update_data()` → calls `get_status()`, `get_camera_params()`
   - Each CGI call: build DRW, retry up to 25 times (0.3s interval) until response or timeout
   - Keepalive task: send F1E0 every 3s to prevent session drop
   - Commands (switch, button, PTZ): direct `client.set_*()` calls, independent of coordinator cycle

**State Management:**

- `PNZEOClient._camera_params` dict: authoritative state (brightness, resolution, motion enabled, etc.)
- `coordinator._pppp_available` flag: tracks PPPP connection health; entities use `available` property
- `PNZEOClient._connected`, `_authenticated`: separate flags; true only if both set
- `coordinator.last_update_success`: Home Assistant's standard coordinator flag; entities become unavailable if False

## Key Abstractions

**PNZEOClient:**
- Purpose: PPPP protocol implementation; complete camera control
- Examples: `pppp_client.py` (400+ lines)
- Pattern: Async UDP protocol with internal event/response tracking via `asyncio.Event`; manual socket handling for P2P punch; retry loops for CGI operations

**PNZEODevice:**
- Purpose: Holds credentials + device metadata; simplifies coordinator init
- Examples: `device.py` (51 lines)
- Pattern: Simple data holder with computed properties (RTSP URLs); delegates protocol to embedded `PNZEOClient`

**PNZEOEntity:**
- Purpose: Base class for all platform entities; DRY coordinator reference, device_info, availability logic
- Examples: `entity.py` (33 lines)
- Pattern: Mixin-style inheritance; subclassed by `PNZEOCamera(PNZEOEntity, Camera)`, `PNZEOSwitch(PNZEOEntity, SwitchEntity)`, etc.

**Packet Builders (pppp_packets.py):**
- Purpose: Encode protocol messages to bytes
- Examples: `build_lan_search()`, `build_drw_cgi()`, `build_cgi_url()`
- Pattern: Pure functions returning bytes; no state; decode counterparts for parsing responses

## Entry Points

**Home Assistant Setup:**
- Location: `__init__.py`, `async_setup_entry(hass, entry)` (line 43)
- Triggers: User adds config entry via Setup Wizard or YAML
- Responsibilities: Instantiate `PNZEODevice`, create `PNZEOCoordinator`, await first refresh, forward platforms, register services

**Discovery (if used):**
- Location: `pppp_discovery.py`, `discover_cameras()` (line 25)
- Triggers: User selects "Auto-discover" in config flow
- Responsibilities: Broadcast DH/PPPP packets to ports 8600/32108, collect responses, deduplicate

**Platform Setup:**
- Location: Each platform module (e.g., `camera.py` line 19, `switch.py` line 16)
- Triggers: HA calls `async_setup_entry(hass, entry, async_add_entities)` for each platform
- Responsibilities: Fetch coordinator from `hass.data[DOMAIN][entry.entry_id]`, instantiate entities, add to HA

## Error Handling

**Strategy:** Graceful degradation. PPPP failures don't block video (RTSP is independent). Coordinator swallows exceptions and returns last-known state.

**Patterns:**

- Connection failures: Logged as `debug`, coordinator retries next cycle (60s)
- CGI command timeouts: Retry up to 25 times with exponential backoff (0.3s base)
- Discovery failures: Cloud → LAN fallback; if both fail, return False and block config entry
- PPPP unavailable: Entities become `available=False` but don't disable HA; RTSP video continues
- Keepalive drops: Automatically reconnect on next coordinator cycle

**Key points:**
- `coordinator._async_update_data()` never raises `UpdateFailed` — returns empty dict or last state on exception
- `_send_cgi()` silently retries; only logs after exhausting retries
- Socket cleanup is defensive: try/except/pass in `_cleanup()` to handle half-closed sockets

## Cross-Cutting Concerns

**Logging:** 
- Module-level `_LOGGER = logging.getLogger(__name__)` in each file
- Levels: DEBUG for protocol details (punch, handshake, DRW tx/rx), INFO for successful connection, WARNING for connection loss
- No sensitive data logged (passwords stripped from CGI URLs)

**Validation:** 
- PTZ preset range check (0-15) in service handlers
- CGI URL builder escapes special chars via `urllib.parse.quote()`
- Device ID format validation in UID encoding
- RTSP port default 554; device_id optional

**Authentication:** 
- Username/password required in config; stored in HA's encrypted config_entries
- CGI login is mandatory before commands (checked in `_cgi_login()`)
- No token-based auth; credentials passed in every CGI URL (camera design, not security best practice)

**Task Lifecycle:**
- Keepalive task created on successful auth, stored in `_keepalive_task`
- On disconnect: cancel keepalive, await CancelledError, set to None
- Coordinator awaits first refresh before returning True from `async_setup_entry()`
- Unload explicitly calls `coordinator.device.async_teardown()`

---

*Architecture analysis: 2026-04-02*
