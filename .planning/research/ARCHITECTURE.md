# Architecture Patterns

**Domain:** IP camera HA custom component (proprietary PPPP protocol)
**Researched:** 2026-04-02

## Recommended Architecture

Extend the existing 5-layer architecture. No new layers needed. The existing pattern (protocol -> device -> coordinator -> entity) scales to 20+ entities without structural changes.

```
                    Home Assistant UI / Automations
                              |
            +------ Entity Platforms (camera, switch, button, ...)
            |         |            |           |          |
            |    binary_sensor  event      sensor      text
            |    (motion,conn)  (alarm)   (SD,fw)    (FTP,email)
            |
      PNZEOCoordinator (polls every 60s)
            |
      PNZEODevice (credentials + RTSP URLs)
            |
      PNZEOClient (PPPP protocol)
            |
      +-----+-----+-----+-----+
      | CH0 | CH1 | CH2 | CH3 |     DRW Channels
      | CMD | VID | AUD | TLK |
      +-----+-----+-----+-----+
            |
      asyncio DatagramProtocol (UDP)
            |
      Camera (LAN UDP / Cloud Relay)
```

### Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| `pppp_packets.py` | Packet encoding/decoding, CGI URL building, G.711 codec (new) | PNZEOClient only |
| `pppp_client.py` | PPPP connection, DRW command/response, multi-channel dispatch (extend) | PNZEODevice, _PNZEOProtocol |
| `device.py` | Credentials, RTSP URLs, device metadata | PNZEOClient, PNZEOCoordinator |
| `coordinator.py` | 60s polling, alarm status tracking, state aggregation | PNZEODevice, all entities |
| `entity.py` | Base entity class (CoordinatorEntity mixin) | PNZEOCoordinator |
| `camera.py` | RTSP stream, motion detection enable/disable (extend) | PNZEOCoordinator |
| `switch.py` | Toggle entities: motion armed, recording, LEDs, etc. (extend) | PNZEOCoordinator |
| `button.py` | One-shot actions: reboot, format SD, unmount SD, WiFi scan (extend) | PNZEOCoordinator |
| `number.py` | Numeric settings: brightness, contrast, upload intervals (extend) | PNZEOCoordinator |
| `select.py` | Choice settings: resolution, mirror, IR mode, sensitivity (extend) | PNZEOCoordinator |
| `binary_sensor.py` (new) | Motion detected, SD card present, connection status | PNZEOCoordinator |
| `sensor.py` (new) | SD card capacity, firmware version, device name, WiFi signal | PNZEOCoordinator |
| `event.py` (new) | Alarm event notifications (motion, sound, GPIO) | PNZEOCoordinator |
| `text.py` (new) | FTP/email/WiFi string settings | PNZEOCoordinator |
| `media_source.py` (new) | SD card recording browser | PNZEOClient (direct for file list queries) |
| `diagnostics.py` (new) | Config entry diagnostics dump | PNZEOCoordinator, config entry |

### Data Flow

**Command Flow (existing pattern, all new CGI commands follow this):**
```
Entity.async_turn_on() 
  -> coordinator.device.client.set_alarm(motion_armed=1)
    -> build_cgi_url("set_alarm.cgi", ..., motion_armed=1)
      -> build_drw_cgi(seq, cgi_text)
        -> transport.sendto(drw_packet, target)
          -> camera processes CGI
        <- camera sends DRW response
      <- parse_drw_cgi_response(data)
    <- {"success": True, "result": 0}
  <- coordinator triggers refresh
```

**Alarm Event Flow (new):**
```
coordinator._async_update_data() [every 60s]
  -> client.get_alarm_status()
    -> build_cgi_url("get_alarm.cgi", ...)
    <- {"motion_detected": 1, "sound_detected": 0, ...}
  -> compare with previous state
  -> if motion_detected changed 0->1:
    -> binary_sensor.motion updates state to ON
    -> event_entity._trigger_event("motion", {"sensitivity": "high"})
  -> if motion_detected changed 1->0:
    -> binary_sensor.motion updates state to OFF
```

**Audio Flow (new, future):**
```
service call: pnzeo_camera.start_listen
  -> client.start_audio(mode=0)
    -> send DRW command on CH_CMD to start audio
    <- camera starts streaming audio on CH_AUDIO (2)
  -> _PNZEOProtocol.datagram_received() routes CH_AUDIO
    -> decode G.711 A-law to PCM
    -> buffer audio frames
    -> expose via media_player or custom service

service call: pnzeo_camera.talk
  -> client.start_talk()
    -> send DRW command on CH_CMD to start talk
  -> encode PCM to G.711 A-law
  -> send audio frames as DRW on CH_TALK (3)
  -> client.stop_talk()
```

## Patterns to Follow

### Pattern 1: Entity Description Dataclass
**What:** Use dataclass-based entity descriptions for all new entities to reduce boilerplate.
**When:** Adding multiple entities of the same platform type.
**Example:**
```python
@dataclass(frozen=True, kw_only=True)
class PNZEOBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a PNZEO binary sensor."""
    value_fn: Callable[[dict], bool | None]

BINARY_SENSORS: tuple[PNZEOBinarySensorDescription, ...] = (
    PNZEOBinarySensorDescription(
        key="motion_detected",
        name="Motion detected",
        device_class=BinarySensorDeviceClass.MOTION,
        value_fn=lambda data: data.get("alarm_motion_detected") == 1,
    ),
    PNZEOBinarySensorDescription(
        key="sd_card_present",
        name="SD card",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("sd_status") == 1,
    ),
)
```

### Pattern 2: Coordinator State Expansion
**What:** Expand coordinator's _async_update_data to fetch alarm status alongside existing get_status/get_camera_params.
**When:** Adding alarm monitoring.
**Example:**
```python
async def _async_update_data(self):
    # Existing
    await self.device.client.get_status()
    await self.device.client.get_camera_params()
    # New: alarm status (only if motion detection is enabled)
    if self.device.client.state.get("motion_armed"):
        await self.device.client.get_alarm_status()
    return self.device.client.state
```

### Pattern 3: Progressive Entity Registration
**What:** Only create advanced entities (FTP, email, WiFi config) when user enables them via options flow.
**When:** Features that most users don't need.
**Example:**
```python
# In options flow
ADVANCED_FEATURES = {
    "ftp_config": ["text.ftp_server", "number.ftp_port", ...],
    "email_config": ["text.smtp_server", ...],
    "wifi_config": ["text.wifi_ssid", ...],
}

# In __init__.py
enabled = entry.options.get("advanced_features", [])
if "ftp_config" in enabled:
    platforms.append(Platform.TEXT)  # only load text platform if needed
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: Polling Too Frequently for Audio
**What:** Setting coordinator update_interval to 1s for real-time audio monitoring.
**Why bad:** Coordinator polling is for state, not streaming. 1s interval would hammer the camera with CGI requests and consume Pi5 CPU.
**Instead:** Audio streaming uses DRW channel callbacks (datagram_received), not coordinator polling. Keep coordinator at 60s. Audio is event-driven, not polled.

### Anti-Pattern 2: Storing Audio State in Coordinator
**What:** Putting audio stream data in coordinator.data dict.
**Why bad:** Audio is real-time streaming data (8KB/s). Coordinator.data is for periodic state snapshots. Mixing them causes entity refresh storms.
**Instead:** Audio stream has its own callback/buffer system independent of coordinator. Only audio ON/OFF state goes in coordinator.data.

### Anti-Pattern 3: One Giant PNZEOClient Class
**What:** Adding 50+ methods to PNZEOClient for every CGI command.
**Why bad:** Already at 400+ lines. Will become unmaintainable.
**Instead:** Group CGI commands by domain in the client:
```python
# Keep PNZEOClient for connection/auth/core
# Add mixin or delegate classes:
class AlarmMixin:
    async def get_alarm_status(self) -> dict: ...
    async def set_alarm(self, **params) -> bool: ...

class SDCardMixin:
    async def get_sd_status(self) -> dict: ...
    async def get_recordings(self, date, ...) -> list: ...
```

### Anti-Pattern 4: Blocking Socket in Async Context
**What:** Using `socket.socket()` with `settimeout()` for new features.
**Why bad:** Already present in `_cloud_discover_port()` and `_lan_discover_port()`. Blocks the event loop.
**Instead:** For new features, use `loop.create_datagram_endpoint()` consistently. Refactor discovery sockets to async in a future cleanup (not critical now -- only called once during setup).

## Scalability Considerations

| Concern | At 1 camera | At 3 cameras | At 10 cameras |
|---------|-------------|--------------|---------------|
| UDP sockets | 1 per camera | 3 sockets, fine | 10 sockets, fine for Pi5 |
| Coordinator polling | 60s interval, ~2 CGI/cycle | ~6 CGI/min | ~20 CGI/min, still fine |
| Audio streams | 8KB/s per camera | 24KB/s, fine | 80KB/s, may need throttling |
| Entity count | ~25 entities | ~75 entities | ~250 entities, HA handles fine |
| Memory | ~1MB per client | ~3MB | ~10MB, fine for Pi5 (8GB) |

The architecture scales to 10+ cameras without changes. The constraint is one user with one camera, so scalability is not a concern for this project.

## Sources

- [HA Fetching Data](https://developers.home-assistant.io/docs/integration_fetching_data/) -- Coordinator pattern
- [HA Entity Docs](https://developers.home-assistant.io/docs/core/entity/) -- Entity descriptions, entity_category
- [HA Event Entity](https://developers.home-assistant.io/docs/core/entity/event/) -- EventEntity, _trigger_event
- [HA Integration Diagnostics](https://developers.home-assistant.io/docs/core/integration_diagnostics/) -- diagnostics.py pattern
- Existing codebase: const.py CH_CMD/CH_VIDEO/CH_AUDIO/CH_TALK constants
- Existing codebase: pppp_client.py architecture (protocol, client, coordinator layers)
