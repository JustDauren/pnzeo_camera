# Technology Stack

**Analysis Date:** 2026-04-02

## Languages

**Primary:**
- Python 3.9+ - Integration logic, PPPP protocol implementation, Home Assistant component

## Runtime

**Environment:**
- Home Assistant (custom component)
- Minimum HA version: 2024.1.0 (per `hacs.json`)

**No external runtime requirements:**
- No package manager needed beyond Home Assistant's built-in module loading
- No lockfile (manifest.json lists empty `"requirements": []`)

## Frameworks

**Core:**
- Home Assistant Framework - Config flows, entity management, coordination
  - `homeassistant.config_entries` - Integration setup and options
  - `homeassistant.helpers.update_coordinator` - Data polling (60-second interval)
  - `homeassistant.components.{camera,switch,button,number,select}` - Entity types
  - `homeassistant.const` - Standard constants (CONF_HOST, CONF_PASSWORD, CONF_USERNAME)

**Protocol:**
- Custom PPPP (P2P Protocol) implementation - In-house async UDP protocol
  - 3-layer architecture: F1xx signaling → Relay bridging → DRW data packets
  - No external PPPP library — fully custom implementation in `pppp_client.py` and `pppp_packets.py`

**Validation:**
- `voluptuous` - Config schema validation
  - Used in `config_flow.py` for user input validation
  - Used in `__init__.py` for service registration schemas

## Key Dependencies

**Framework:**
- `homeassistant` - Home Assistant core (implicit via component framework)
  - Provides all entity platforms, config entry system, coordinator pattern
  - Specific modules: `ConfigEntry`, `ConfigFlow`, `DataUpdateCoordinator`, `CoordinatorEntity`

**Validation:**
- `voluptuous` - Configuration and service schema validation
  - Validates user input in config flow
  - Validates service call parameters for ptz_control, goto_preset, set_preset, send_command, change_password

## Configuration

**Environment:**
- Configuration via Home Assistant UI (config flow)
- No environment variables or .env files
- Settings stored in Home Assistant's config entry system

**Required Config:**
- `host` - Camera IP address (LAN)
- `username` - Camera login (default: "admin")
- `password` - Camera password (default: "8888")
- `device_id` - Optional camera identifier for cloud port discovery
- `rtsp_port` - RTSP stream port (default: 554)

**Integration Type:**
- `integration_type: "device"` - Local IoT device
- `iot_class: "local_polling"` - Cloud used ONLY for initial port discovery (1 UDP query, 3 seconds)

## Platform Requirements

**Development:**
- Python 3.9+ (Home Assistant standard)
- Home Assistant installation with custom component support

**Production:**
- Home Assistant 2024.1.0 or later
- Local network access to PNZEO/MTC IP camera
- Network access to cloud relay servers for port discovery (optional — LAN fallback available)

**Network:**
- UDP port 32108 (PPPP LAN search)
- UDP port 8600 (DH protocol LAN discovery, PNZEO W8)
- UDP port 32100 (Cloud P2P relay for port discovery only)
- RTSP port 554 (video stream, configurable)

## Protocol Stack

**Layer 1 - Discovery:**
- DH protocol (port 8600) - Primary for PNZEO W8
- Standard PPPP (port 32108) - LAN fallback
- Cloud P2P (port 32100) - Port discovery fallback to 54.186.48.247:32100 and 54.191.3.239:32100

**Layer 2 - P2P Handshake:**
- F1xx signaling packets - P2P punch and connection establishment
- UID encoding (PPRT format) - Device identification in protocol

**Layer 3 - Data/Control:**
- DRW packets (0xD0) - Command/response channel
- CGI commands - Camera control (brightness, resolution, PTZ, etc.)
- RTSP - Video streaming (via ffmpeg in Home Assistant)

## External Services

**Cloud P2P Relay:**
- AWS EC2 relay nodes (port discovery only)
- Servers: 54.186.48.247:32100, 54.191.3.239:32100
- Purpose: Single UDP query to discover camera's DRW data port
- Fallback: LAN-only discovery if cloud unreachable
- Camera data: Never goes through cloud — stays 100% on LAN

## Build & Execution

**Deployment:**
- Home Assistant custom component package (directory layout)
- Loaded by Home Assistant at startup from `custom_components/pnzeo_camera/`
- No build step required
- Configuration via Home Assistant web UI or YAML

**Entry Point:**
- `__init__.py` - `async_setup_entry()` initializes PNZEODevice and coordinator
- Platform setup: camera, switch, button, number, select entities

---

*Stack analysis: 2026-04-02*
