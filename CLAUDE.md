<!-- GSD:project-start source:PROJECT.md -->
## Project

**PNZEO Camera — Full HA Integration**

Home Assistant custom component for PNZEO IP cameras (and compatible MTCam-based cameras) using the proprietary PPPP P2P protocol. Provides complete local control of the camera from HA — full feature parity with the MTCam HD Android app, including hidden/undocumented features. One-click HACS install, auto-discovery on LAN, user enters password and everything works.

**Core Value:** **Any PNZEO camera owner installs via HACS, enters their password, and gets full camera control — video, audio, PTZ, alarms, SD card, settings — working autonomously on their local network without the Chinese app.**

### Constraints

- **Platform**: Home Assistant custom component (Python, asyncio)
- **No external deps**: Pure Python (no C extensions, no libRtMain.so)
- **Network**: UDP only for PPPP (no TCP fallback for control)
- **Pi5 resources**: Must be lightweight, single camera, ~60s polling
- **Security**: Never commit real Device IDs, passwords, or IP addresses
- **Deployment**: Git push → HACS install, no manual file copying
- **Compatibility**: Must work with any PNZEO/MTCam camera, not just W8
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Python 3.9+ - Integration logic, PPPP protocol implementation, Home Assistant component
## Runtime
- Home Assistant (custom component)
- Minimum HA version: 2024.1.0 (per `hacs.json`)
- No package manager needed beyond Home Assistant's built-in module loading
- No lockfile (manifest.json lists empty `"requirements": []`)
## Frameworks
- Home Assistant Framework - Config flows, entity management, coordination
- Custom PPPP (P2P Protocol) implementation - In-house async UDP protocol
- `voluptuous` - Config schema validation
## Key Dependencies
- `homeassistant` - Home Assistant core (implicit via component framework)
- `voluptuous` - Configuration and service schema validation
## Configuration
- Configuration via Home Assistant UI (config flow)
- No environment variables or .env files
- Settings stored in Home Assistant's config entry system
- `host` - Camera IP address (LAN)
- `username` - Camera login (default: "admin")
- `password` - Camera password (default: "8888")
- `device_id` - Optional camera identifier for cloud port discovery
- `rtsp_port` - RTSP stream port (default: 554)
- `integration_type: "device"` - Local IoT device
- `iot_class: "local_polling"` - Cloud used ONLY for initial port discovery (1 UDP query, 3 seconds)
## Platform Requirements
- Python 3.9+ (Home Assistant standard)
- Home Assistant installation with custom component support
- Home Assistant 2024.1.0 or later
- Local network access to PNZEO/MTC IP camera
- Network access to cloud relay servers for port discovery (optional — LAN fallback available)
- UDP port 32108 (PPPP LAN search)
- UDP port 8600 (DH protocol LAN discovery, PNZEO W8)
- UDP port 32100 (Cloud P2P relay for port discovery only)
- RTSP port 554 (video stream, configurable)
## Protocol Stack
- DH protocol (port 8600) - Primary for PNZEO W8
- Standard PPPP (port 32108) - LAN fallback
- Cloud P2P (port 32100) - Port discovery fallback to 54.186.48.247:32100 and 54.191.3.239:32100
- F1xx signaling packets - P2P punch and connection establishment
- UID encoding (PPRT format) - Device identification in protocol
- DRW packets (0xD0) - Command/response channel
- CGI commands - Camera control (brightness, resolution, PTZ, etc.)
- RTSP - Video streaming (via ffmpeg in Home Assistant)
## External Services
- AWS EC2 relay nodes (port discovery only)
- Servers: 54.186.48.247:32100, 54.191.3.239:32100
- Purpose: Single UDP query to discover camera's DRW data port
- Fallback: LAN-only discovery if cloud unreachable
- Camera data: Never goes through cloud — stays 100% on LAN
## Build & Execution
- Home Assistant custom component package (directory layout)
- Loaded by Home Assistant at startup from `custom_components/pnzeo_camera/`
- No build step required
- Configuration via Home Assistant web UI or YAML
- `__init__.py` - `async_setup_entry()` initializes PNZEODevice and coordinator
- Platform setup: camera, switch, button, number, select entities
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Naming Patterns
- Module files use snake_case: `pppp_client.py`, `pppp_packets.py`, `pppp_discovery.py`
- Entity platform files match platform names: `camera.py`, `switch.py`, `button.py`, `number.py`, `select.py`
- Configuration and utilities use descriptive names: `config_flow.py`, `coordinator.py`, `device.py`, `entity.py`, `const.py`
- Async public methods use `async def` prefix with verb-noun pattern: `async def connect()`, `async def get_camera_params()`, `async def set_brightness()`
- Private async methods use leading underscore: `async def _do_connect()`, `async def _cgi_login()`, `async def _keepalive_loop()`
- Properties use descriptive names without leading underscore: `@property def connected()`, `@property def state()`, `@property def connection_method()`
- Instance variables use leading underscore: `self._transport`, `self._protocol`, `self._connected`, `self._authenticated`, `self._cmd_seq`
- Constants use UPPER_CASE: `KEEPALIVE_INTERVAL`, `PUNCH_COUNT`, `PUNCH_INTERVAL`, `DRW_RETRY_MAX`
- Dictionary keys match protocol specs: `msg_type`, `device_id`, `ip`, `port`, `firmware`
- PEP 484 type hints used throughout: `async def connect(self) -> bool:`, `dict[str, Any]`, `int | None`
- Union syntax uses pipe operator: `int | None`, `bytes | None` (requires `from __future__ import annotations`)
- Generic types are explicit: `dict[str, Any]`, `list[dict]`, `list[tuple[str, int]]`
## Code Style
- 4-space indentation throughout (Python standard)
- Maximum line length approximately 100 characters (no explicit formatter configured)
- Double quotes for strings: `"Connect to camera"`, `"P2P handshake failed"`
- No trailing commas except in multiline structures
- No `.pylintrc` or `.flake8` configuration present
- No pre-commit hooks detected
- Code follows Home Assistant component standards
- Module-level docstrings describe protocol flow and connection architecture:
- Class docstrings are concise: `"""Async PPPP client for camera control."""`
- Method docstrings describe purpose and return type when non-obvious:
- No parameter-level documentation (type hints are sufficient)
## Import Organization
- Relative imports use current package: `from .const import CONF_HOST`
- No absolute path aliases configured
- Multi-line imports use parentheses: `from .pppp_packets import (\n    PktType,\n    build_alive,\n    ...`
## Error Handling
- Broad exception catching for network operations:
- Specific exception handling for async timeouts:
- Try/except wrapping for socket operations (sendto, recvfrom):
- Graceful degradation: Never raise UpdateFailed for protocol failures, return empty state instead:
## Logging
- `_LOGGER.debug()` — detailed diagnostic info: `"Cloud port discovery failed, trying LAN only"`
- `_LOGGER.info()` — normal operational events: `"Connected to camera 192.168.1.100 (port 32108)"`
- `_LOGGER.warning()` — recoverable issues: `"P2P handshake failed with 192.168.1.100:32108"`
- `_LOGGER.error()` — serious issues requiring intervention: `"Cannot connect to camera for password change"`
## Comments
- Protocol-specific details: `# F167 Relay/List Request. Client → P2P Server.`
- Binary structure documentation: `# Format: "PPRT" + 4x00 + prefix(2) + transformed_suffix(10)`
- Complex algorithm steps marked with horizontal dividers:
- Single `#` for inline comments
- Section comments use divider lines (see above)
- No commented-out code blocks
- Comments precede the code they describe
## Function Design
- Keyword arguments used in Home Assistant config flows: `vol.Required()`, `vol.Optional()`
- Positional args for essential parameters: `def __init__(self, host, username, password)`
- Optional kwargs with defaults for utility methods: `async def ptz_control(self, direction: int, step: int = 1)`
- Boolean for success/failure operations: `async def connect() -> bool:`
- Dict for state queries: `async def get_camera_params() -> dict[str, Any]:`
- None for fire-and-forget operations: `async def disconnect() -> None:`
- Optional types for nullable results: `async def _cloud_discover_port() -> int | None:`
- All I/O operations are async: network socket calls, Home Assistant service registration
- Proper cleanup with try/finally patterns:
## Module Design
- Explicit exports via direct imports: `from .pppp_client import PNZEOClient`
- No `__all__` declarations
- Classes, functions, and constants imported as needed by consumers
- No barrel files (`__init__.py` only for package registration)
- Integration entry point in `__init__.py` only exposes: `async_setup_entry()`, `async_unload_entry()`, service registration functions
- `const.py` — All PPPP protocol constants and default values
- `pppp_packets.py` — Protocol packet builders and parsers (enum, binary functions)
- `pppp_client.py` — Main async PPPP client state machine and CGI command interface
- `pppp_discovery.py` — LAN discovery and RTSP connectivity checks
- `device.py` — Device wrapper (thin wrapper around PNZEOClient)
- `coordinator.py` — Home Assistant DataUpdateCoordinator for polling
- `entity.py` — Base PNZEOEntity with common HA entity setup
- `camera.py`, `switch.py`, etc. — Platform-specific entity implementations
- `config_flow.py` — Home Assistant config entry flow and options
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Pattern Overview
- **Dual-path streaming:** RTSP over local TCP for video (handled by HA built-in), PPPP UDP for control commands
- **Cloud-minimal design:** Cloud queries only for port discovery (1 UDP), all data stays LAN-bound
- **Async-first:** Full asyncio with no blocking I/O; proper task lifecycle management
- **Coordinator-based state:** Single `PNZEOCoordinator` updates every 60 seconds; if PPPP drops, RTSP video keeps working
- **Protocol layering:** Three independent layers (F1xx signaling → DRW data → CGI commands)
## Layers
- Purpose: Implement PPPP P2P handshake and DRW CGI command protocol
- Location: `pppp_client.py`, `pppp_packets.py`
- Contains: UDP transport management, socket handling, packet encoding/decoding, F1xx signaling, DRW command/response parsing
- Depends on: Python stdlib (`asyncio`, `socket`, `struct`), no external deps
- Used by: `PNZEODevice`, `PNZEOCoordinator`
- Purpose: Wrap camera credentials and RTSP URLs; thin facade
- Location: `device.py`
- Contains: RTSP stream URL generation, device metadata (name, unique_id)
- Depends on: `PNZEOClient` from protocol layer
- Used by: `PNZEOCoordinator`, all platform entities
- Purpose: Poll camera state (get_status, get_camera_params) every 60s; handle PPPP connection lifecycle
- Location: `coordinator.py`
- Contains: Home Assistant `DataUpdateCoordinator` subclass; graceful degradation (video still works if PPPP fails)
- Depends on: HA's `update_coordinator`, `PNZEODevice`
- Used by: All platform entities (camera, switch, button, number, select)
- Purpose: HA entity types for UI exposure and user interaction
- Location: Platform-specific modules + base class in `entity.py`
- Contains: Entity property state, async_turn_on/off/set_value handlers, UI metadata (icons, names, ranges)
- Depends on: HA platform classes, `PNZEOCoordinator`
- Used by: Home Assistant UI/automation engine
- Purpose: Setup/unload hook; service registration for PTZ and custom commands
- Location: `__init__.py`
- Contains: Entry lifecycle, platform forwarding, service handlers for ptz_control, goto_preset, set_preset, send_command, change_password
- Depends on: All layers above, HA config_entries API
- Used by: Home Assistant only (entry point)
- Purpose: Discovery and credential collection
- Location: `config_flow.py` (HA config flow), `pppp_discovery.py` (LAN discovery logic)
- Contains: DH/PPPP UDP broadcast discovery, RTSP port check, manual IP entry
- Depends on: HA config_entries, `PNZEOClient` for login test
- Used by: HA setup wizard only
## Data Flow
- `PNZEOClient._camera_params` dict: authoritative state (brightness, resolution, motion enabled, etc.)
- `coordinator._pppp_available` flag: tracks PPPP connection health; entities use `available` property
- `PNZEOClient._connected`, `_authenticated`: separate flags; true only if both set
- `coordinator.last_update_success`: Home Assistant's standard coordinator flag; entities become unavailable if False
## Key Abstractions
- Purpose: PPPP protocol implementation; complete camera control
- Examples: `pppp_client.py` (400+ lines)
- Pattern: Async UDP protocol with internal event/response tracking via `asyncio.Event`; manual socket handling for P2P punch; retry loops for CGI operations
- Purpose: Holds credentials + device metadata; simplifies coordinator init
- Examples: `device.py` (51 lines)
- Pattern: Simple data holder with computed properties (RTSP URLs); delegates protocol to embedded `PNZEOClient`
- Purpose: Base class for all platform entities; DRY coordinator reference, device_info, availability logic
- Examples: `entity.py` (33 lines)
- Pattern: Mixin-style inheritance; subclassed by `PNZEOCamera(PNZEOEntity, Camera)`, `PNZEOSwitch(PNZEOEntity, SwitchEntity)`, etc.
- Purpose: Encode protocol messages to bytes
- Examples: `build_lan_search()`, `build_drw_cgi()`, `build_cgi_url()`
- Pattern: Pure functions returning bytes; no state; decode counterparts for parsing responses
## Entry Points
- Location: `__init__.py`, `async_setup_entry(hass, entry)` (line 43)
- Triggers: User adds config entry via Setup Wizard or YAML
- Responsibilities: Instantiate `PNZEODevice`, create `PNZEOCoordinator`, await first refresh, forward platforms, register services
- Location: `pppp_discovery.py`, `discover_cameras()` (line 25)
- Triggers: User selects "Auto-discover" in config flow
- Responsibilities: Broadcast DH/PPPP packets to ports 8600/32108, collect responses, deduplicate
- Location: Each platform module (e.g., `camera.py` line 19, `switch.py` line 16)
- Triggers: HA calls `async_setup_entry(hass, entry, async_add_entities)` for each platform
- Responsibilities: Fetch coordinator from `hass.data[DOMAIN][entry.entry_id]`, instantiate entities, add to HA
## Error Handling
- Connection failures: Logged as `debug`, coordinator retries next cycle (60s)
- CGI command timeouts: Retry up to 25 times with exponential backoff (0.3s base)
- Discovery failures: Cloud → LAN fallback; if both fail, return False and block config entry
- PPPP unavailable: Entities become `available=False` but don't disable HA; RTSP video continues
- Keepalive drops: Automatically reconnect on next coordinator cycle
- `coordinator._async_update_data()` never raises `UpdateFailed` — returns empty dict or last state on exception
- `_send_cgi()` silently retries; only logs after exhausting retries
- Socket cleanup is defensive: try/except/pass in `_cleanup()` to handle half-closed sockets
## Cross-Cutting Concerns
- Module-level `_LOGGER = logging.getLogger(__name__)` in each file
- Levels: DEBUG for protocol details (punch, handshake, DRW tx/rx), INFO for successful connection, WARNING for connection loss
- No sensitive data logged (passwords stripped from CGI URLs)
- PTZ preset range check (0-15) in service handlers
- CGI URL builder escapes special chars via `urllib.parse.quote()`
- Device ID format validation in UID encoding
- RTSP port default 554; device_id optional
- Username/password required in config; stored in HA's encrypted config_entries
- CGI login is mandatory before commands (checked in `_cgi_login()`)
- No token-based auth; credentials passed in every CGI URL (camera design, not security best practice)
- Keepalive task created on successful auth, stored in `_keepalive_task`
- On disconnect: cancel keepalive, await CancelledError, set to None
- Coordinator awaits first refresh before returning True from `async_setup_entry()`
- Unload explicitly calls `coordinator.device.async_teardown()`
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
