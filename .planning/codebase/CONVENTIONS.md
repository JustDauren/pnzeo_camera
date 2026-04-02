# Coding Conventions

**Analysis Date:** 2026-04-02

## Naming Patterns

**Files:**
- Module files use snake_case: `pppp_client.py`, `pppp_packets.py`, `pppp_discovery.py`
- Entity platform files match platform names: `camera.py`, `switch.py`, `button.py`, `number.py`, `select.py`
- Configuration and utilities use descriptive names: `config_flow.py`, `coordinator.py`, `device.py`, `entity.py`, `const.py`

**Functions:**
- Async public methods use `async def` prefix with verb-noun pattern: `async def connect()`, `async def get_camera_params()`, `async def set_brightness()`
- Private async methods use leading underscore: `async def _do_connect()`, `async def _cgi_login()`, `async def _keepalive_loop()`
- Properties use descriptive names without leading underscore: `@property def connected()`, `@property def state()`, `@property def connection_method()`

**Variables:**
- Instance variables use leading underscore: `self._transport`, `self._protocol`, `self._connected`, `self._authenticated`, `self._cmd_seq`
- Constants use UPPER_CASE: `KEEPALIVE_INTERVAL`, `PUNCH_COUNT`, `PUNCH_INTERVAL`, `DRW_RETRY_MAX`
- Dictionary keys match protocol specs: `msg_type`, `device_id`, `ip`, `port`, `firmware`

**Types:**
- PEP 484 type hints used throughout: `async def connect(self) -> bool:`, `dict[str, Any]`, `int | None`
- Union syntax uses pipe operator: `int | None`, `bytes | None` (requires `from __future__ import annotations`)
- Generic types are explicit: `dict[str, Any]`, `list[dict]`, `list[tuple[str, int]]`

## Code Style

**Formatting:**
- 4-space indentation throughout (Python standard)
- Maximum line length approximately 100 characters (no explicit formatter configured)
- Double quotes for strings: `"Connect to camera"`, `"P2P handshake failed"`
- No trailing commas except in multiline structures

**Linting:**
- No `.pylintrc` or `.flake8` configuration present
- No pre-commit hooks detected
- Code follows Home Assistant component standards

**Docstring Style:**
- Module-level docstrings describe protocol flow and connection architecture:
  ```python
  """Async PPPP client for PNZEO/MTC cameras.

  Connection flow:
  1. LAN Search (F130 → 32108) → camera responds with P2P signaling port
  2. Cloud query (1 UDP to P2P server) → get camera's DRW data port
  3. F141 PUNCH to DRW port → P2P handshake
  4. CGI commands via DRW → full camera control on LAN
  """
  ```
- Class docstrings are concise: `"""Async PPPP client for camera control."""`
- Method docstrings describe purpose and return type when non-obvious:
  ```python
  async def _cgi_login(self) -> bool:
      """Login via CGI check_user endpoint."""
  ```
- No parameter-level documentation (type hints are sufficient)

## Import Organization

**Order:**
1. `from __future__ import annotations` — Always first for PEP 563 compatibility
2. Standard library imports: `asyncio`, `logging`, `socket`, `struct`, `json`
3. Third-party framework imports: `homeassistant.*`, `voluptuous`
4. Relative imports from same package: `from .const import`, `from .device import`

**Example from `pppp_client.py`:**
```python
from __future__ import annotations

import asyncio
import logging
import socket
import struct
from typing import Any

from .pppp_packets import (
    PktType,
    build_alive, build_alive_ack, build_close,
    ...
)
```

**Path Aliases:**
- Relative imports use current package: `from .const import CONF_HOST`
- No absolute path aliases configured
- Multi-line imports use parentheses: `from .pppp_packets import (\n    PktType,\n    build_alive,\n    ...`

## Error Handling

**Patterns:**
- Broad exception catching for network operations:
  ```python
  except Exception as ex:
      _LOGGER.debug("Connection failed: %s", ex)
      await self._cleanup()
      return False
  ```
- Specific exception handling for async timeouts:
  ```python
  except asyncio.TimeoutError:
      pass
  except asyncio.CancelledError:
      pass
  ```
- Try/except wrapping for socket operations (sendto, recvfrom):
  ```python
  try:
      self._transport.sendto(build_close(), (self.host, self._cam_port))
  except Exception:
      pass
  ```
- Graceful degradation: Never raise UpdateFailed for protocol failures, return empty state instead:
  ```python
  except Exception as ex:
      _LOGGER.debug("PPPP setup failed: %s", ex)
      self._pppp_available = False
      return self.device.client.state
  ```

## Logging

**Framework:** Standard `logging` module, NOT `_LOGGER = logging.getLogger(__name__)`

**Per-File Pattern:**
```python
import logging
_LOGGER = logging.getLogger(__name__)
```

**Log Levels:**
- `_LOGGER.debug()` — detailed diagnostic info: `"Cloud port discovery failed, trying LAN only"`
- `_LOGGER.info()` — normal operational events: `"Connected to camera 192.168.1.100 (port 32108)"`
- `_LOGGER.warning()` — recoverable issues: `"P2P handshake failed with 192.168.1.100:32108"`
- `_LOGGER.error()` — serious issues requiring intervention: `"Cannot connect to camera for password change"`

**Logging Examples from Codebase:**
```python
_LOGGER.debug("P2P handshake OK with %s:%d", self.host, self._cam_port)
_LOGGER.warning("Cannot discover camera port for %s", self.host)
_LOGGER.info("Discovered PNZEO camera: %s at %s:%d (protocol: %s)",
             result.get("device_id", "unknown"), addr[0], addr[1], result.get("protocol"))
```

## Comments

**When to Comment:**
- Protocol-specific details: `# F167 Relay/List Request. Client → P2P Server.`
- Binary structure documentation: `# Format: "PPRT" + 4x00 + prefix(2) + transformed_suffix(10)`
- Complex algorithm steps marked with horizontal dividers:
  ```python
  # =====================================================================
  # Connection
  # =====================================================================
  ```

**Comment Style:**
- Single `#` for inline comments
- Section comments use divider lines (see above)
- No commented-out code blocks
- Comments precede the code they describe

## Function Design

**Size:** 20-60 lines typical (up to 100 for complex connection flows)

**Parameters:**
- Keyword arguments used in Home Assistant config flows: `vol.Required()`, `vol.Optional()`
- Positional args for essential parameters: `def __init__(self, host, username, password)`
- Optional kwargs with defaults for utility methods: `async def ptz_control(self, direction: int, step: int = 1)`

**Return Values:**
- Boolean for success/failure operations: `async def connect() -> bool:`
- Dict for state queries: `async def get_camera_params() -> dict[str, Any]:`
- None for fire-and-forget operations: `async def disconnect() -> None:`
- Optional types for nullable results: `async def _cloud_discover_port() -> int | None:`

**Async Functions:**
- All I/O operations are async: network socket calls, Home Assistant service registration
- Proper cleanup with try/finally patterns:
  ```python
  try:
      sock = socket.socket(...)
      sock.sendto(...)
      data, _ = sock.recvfrom(4096)
  finally:
      sock.close()
  ```

## Module Design

**Exports:**
- Explicit exports via direct imports: `from .pppp_client import PNZEOClient`
- No `__all__` declarations
- Classes, functions, and constants imported as needed by consumers

**Barrel Files:**
- No barrel files (`__init__.py` only for package registration)
- Integration entry point in `__init__.py` only exposes: `async_setup_entry()`, `async_unload_entry()`, service registration functions

**File Responsibilities:**
- `const.py` — All PPPP protocol constants and default values
- `pppp_packets.py` — Protocol packet builders and parsers (enum, binary functions)
- `pppp_client.py` — Main async PPPP client state machine and CGI command interface
- `pppp_discovery.py` — LAN discovery and RTSP connectivity checks
- `device.py` — Device wrapper (thin wrapper around PNZEOClient)
- `coordinator.py` — Home Assistant DataUpdateCoordinator for polling
- `entity.py` — Base PNZEOEntity with common HA entity setup
- `camera.py`, `switch.py`, etc. — Platform-specific entity implementations
- `config_flow.py` — Home Assistant config entry flow and options

---

*Convention analysis: 2026-04-02*
