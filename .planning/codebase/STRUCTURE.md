# Codebase Structure

**Analysis Date:** 2026-04-02

## Directory Layout

```
pnzeo_camera/
├── __init__.py              # Entry point: setup_entry, unload_entry, service registration
├── coordinator.py           # DataUpdateCoordinator: polls state every 60s
├── device.py                # Device wrapper: credentials + RTSP URLs
├── entity.py                # Base entity class: common UI metadata, availability logic
│
├── camera.py                # Camera platform: RTSP stream + snapshot via ffmpeg
├── switch.py                # Switch platform: IR LED, motion, recording, LED indicator
├── button.py                # Button platform: reboot, snapshot, format SD, factory reset
├── number.py                # Number platform: brightness, contrast (0-255 sliders)
├── select.py                # Select platform: resolution, mirror mode
│
├── pppp_client.py           # Core PPPP protocol: UDP transport, P2P handshake, CGI commands
├── pppp_packets.py          # Packet encoding/decoding: F1xx builders, DRW wrappers, parsers
├── pppp_discovery.py        # LAN discovery: DH + PPPP broadcast, RTSP port check
├── config_flow.py           # HA config flow: manual/auto discovery, credential entry
│
├── const.py                 # Constants: PPPP ports, message types, PTZ commands, defaults
├── manifest.json            # HA integration metadata
├── hacs.json                # HACS metadata
├── services.yaml            # Service definitions (ptz_control, goto_preset, etc.)
├── strings.json             # UI strings and i18n
│
├── translations/            # Translation files (currently empty)
├── README.md                # User documentation
└── .planning/codebase/      # GSD analysis docs (this directory)
    ├── ARCHITECTURE.md
    └── STRUCTURE.md
```

## Directory Purposes

**Root (`pnzeo_camera/`):**
- Purpose: Single Home Assistant custom component directory; all code lives here (no subdirs)
- Contains: Python modules, HA metadata, translations
- Key files: `__init__.py` (entry), `pppp_client.py` (protocol), platform modules

## Key File Locations

**Entry Points:**

- `__init__.py` (line 43): `async_setup_entry()` — called when user adds config entry
- `__init__.py` (line 65): `async_unload_entry()` — cleanup on integration removal
- `config_flow.py` (line 38): `PNZEOConfigFlow.async_step_user()` — first step of setup wizard

**Configuration:**

- `const.py`: All constants (PPPP ports, message types, defaults, camera params)
- `manifest.json`: Domain name, HA version requirement, dependencies (voluptuous, ffmpeg for snapshots)
- `services.yaml`: YAML definitions for `ptz_control`, `goto_preset`, `set_preset`, `send_command`, `change_password` services
- `strings.json`: Translatable UI text (entity names, descriptions)

**Core Logic:**

- `pppp_client.py` (400+ lines): `PNZEOClient` class — connection, authentication, CGI commands, keepalive
- `pppp_packets.py` (600+ lines): Packet builders/parsers — F1xx signaling, DRW wrapping, UID encoding
- `pppp_discovery.py` (150+ lines): LAN discovery via DH/PPPP broadcast + RTSP port check
- `coordinator.py` (70 lines): `PNZEOCoordinator` — polls every 60s, handles PPPP failures gracefully
- `device.py` (50 lines): `PNZEODevice` — simple facade for credentials + RTSP URL generation

**Entities (HA Platforms):**

- `entity.py` (33 lines): `PNZEOEntity` base class — shared init, device_info, availability
- `camera.py` (60 lines): RTSP streaming + snapshot via ffmpeg
- `switch.py` (114 lines): 4 switches (IR LED, motion detection, SD recording, indicator LED)
- `button.py` (66 lines): 4 buttons (reboot, snapshot, format SD, factory reset)
- `number.py` (64 lines): 2 sliders (brightness, contrast)
- `select.py` (62 lines): 2 dropdowns (resolution, mirror mode)

**Setup & Configuration:**

- `config_flow.py` (200+ lines): `PNZEOConfigFlow` — auto-discover or manual entry; `PNZEOOptionsFlow` for editing

## Naming Conventions

**Files:**

- Platform modules: lowercase + `_` (e.g., `camera.py`, `switch.py`, `select.py`)
- Core logic: lowercase + underscore (e.g., `pppp_client.py`, `pppp_packets.py`, `pppp_discovery.py`)
- Constants: UPPERCASE in `const.py`
- Entry point: `__init__.py`

**Classes:**

- Entity/Component classes: PascalCase (e.g., `PNZEOCamera`, `PNZEOCoordinator`, `PNZEODevice`, `PNZEOEntity`)
- Platform entities: `PNZEO` prefix + entity type (e.g., `PNZEOIRSwitch`, `PNZEOBrightness`, `PNZEORebootButton`)
- Protocol classes: `PNZEOClient`, `_PNZEOProtocol` (internal UDP protocol handler)
- Config flow: `PNZEOConfigFlow`, `PNZEOOptionsFlow`

**Functions/Methods:**

- Public async: `async_setup_entry`, `async_press`, `async_turn_on`
- Private async: `_async_update_data`, `_async_send_cgi`, `_keepalive_loop`
- Public sync: `connect`, `disconnect`, `set_brightness`
- Private sync: `_do_connect`, `_cgi_login`, `_cleanup`
- Packet builders: `build_lan_search`, `build_drw_cgi`, `build_cgi_url`
- Parsers: `parse_drw_cgi_response`, `encode_uid`, `decode_uid`

**Constants:**

- PPPP port constants: `PPPP_PORT_STANDARD`, `PPPP_PORT_CLOUD`, `PPPP_PORT_DH_LAN`
- Message types: `MSG_GET_STATUS`, `MSG_CAMERA_CONTROL`, `MSG_REBOOT`
- Command codes: `PTZ_UP`, `PTZ_DOWN`, `CMD_SET_BRIGHTNESS`, `CMD_SET_MIRROR`
- Timeouts: `KEEPALIVE_INTERVAL`, `CLOUD_TIMEOUT`, `DRW_RETRY_INTERVAL`
- Defaults: `DEFAULT_USERNAME`, `DEFAULT_PASSWORD`, `DEFAULT_RTSP_PORT`

**Variables:**

- Connection state: `_connected`, `_authenticated`, `_pppp_available`
- Sockets/transport: `_transport`, `_protocol`, `_socket`
- Sequence numbers: `_cmd_seq`, `_sequence`
- Async events: `_drw_response` (asyncio.Event for CGI response tracking)
- State dicts: `_camera_params`, `_capabilities`, `state`

## Where to Add New Code

**New Feature (e.g., infrared blaster control):**
- Primary code: Add methods to `PNZEOClient` in `pppp_client.py` (e.g., `async def send_ir(self, code: int)`)
- CGI wrapper: Add builder in `pppp_packets.py` (e.g., `build_cgi_ir_send(code)`)
- New platform: Create `ir_blaster.py` with entity class inheriting from `PNZEOEntity` + HA's platform base
- Platform registration: Add to `PLATFORMS` list in `__init__.py` (line 27)
- Services: If user-facing, register in `_register_services()` and add to `services.yaml`

**New Platform Entity (e.g., light for LED brightness):**
- File: `light.py` (new file in root)
- Structure:
  ```python
  async def async_setup_entry(hass, entry, async_add_entities):
      coordinator = hass.data[DOMAIN][entry.entry_id]
      async_add_entities([PNZEOStatusLEDLight(coordinator)])
  
  class PNZEOStatusLEDLight(PNZEOEntity, LightEntity):
      def __init__(self, coordinator): ...
      async def async_turn_on(self, **kwargs): ...
  ```
- Add `Platform.LIGHT` to `PLATFORMS` in `__init__.py`
- Inherit from `PNZEOEntity` for automatic device_info, availability, coordinator access

**New Utility Function (e.g., IP validation helper):**
- Location: Add to `pppp_discovery.py` or `pppp_packets.py` depending on purpose
- Naming: `def _validate_ip(ip: str) -> bool:` (prefix with `_` if private to module)
- If reusable across modules: move to `const.py` as helper

**New Constant (e.g., new CGI parameter):**
- Location: `const.py`
- Naming: `CGI_PARAM_NEW_FEATURE = "new_param"` (or message type if applicable)
- Add docstring explaining what it controls

**New Platform in config_flow:**
- Location: Extend `PNZEOConfigFlow` class (around line 38 in `config_flow.py`)
- Pattern: Add `async def async_step_name(self, user_input)` method; call `self.async_show_form()` or `self.async_abort()`
- Discovery integration: Call existing `discover_cameras()` from `pppp_discovery.py`

**Test Coverage (if testing is added):**
- New test file per module: `test_pppp_client.py`, `test_coordinator.py`, etc.
- Mock `asyncio` for async tests, mock `PNZEOClient` in entity tests
- Tests live in separate `tests/` directory (not yet created)

## Special Directories

**`.planning/codebase/`:**
- Purpose: GSD codebase analysis documents
- Generated: Yes (by GSD orchestrator)
- Committed: Yes (to git)
- Contents: ARCHITECTURE.md, STRUCTURE.md, CONVENTIONS.md, TESTING.md (if created)

**`translations/`:**
- Purpose: i18n translation files per HA spec
- Generated: No (manual)
- Committed: Yes
- Contents: Currently empty; would contain `en.json`, `ru.json`, etc. with locale-specific strings
- Current approach: UI strings hardcoded in `strings.json` + code

## File Size & Complexity Overview

| File | Lines | Purpose | Complexity |
|------|-------|---------|------------|
| `pppp_client.py` | ~400 | Core protocol | HIGH (UDP, P2P, retry logic) |
| `pppp_packets.py` | ~600 | Packet encoding | HIGH (binary format, UID transforms) |
| `config_flow.py` | ~200 | Setup wizard | MEDIUM (HA API, discovery) |
| `coordinator.py` | ~70 | State polling | LOW (delegated to client) |
| `switch.py` | ~114 | 4 switches | LOW (boilerplate) |
| `button.py` | ~66 | 4 buttons | LOW (simple press handlers) |
| `number.py` | ~64 | 2 sliders | LOW (range metadata) |
| `select.py` | ~62 | 2 dropdowns | LOW (options list) |
| `camera.py` | ~60 | RTSP stream | LOW (ffmpeg subprocess) |
| `pppp_discovery.py` | ~150 | LAN discovery | MEDIUM (UDP broadcast, parsing) |
| `__init__.py` | ~155 | Entry + services | MEDIUM (setup lifecycle, service schema) |
| `entity.py` | ~33 | Base class | LOW (DRY) |
| `device.py` | ~51 | Facade | LOW (simple wrapper) |
| `const.py` | ~220 | Constants | LOW (data only) |

---

*Structure analysis: 2026-04-02*
