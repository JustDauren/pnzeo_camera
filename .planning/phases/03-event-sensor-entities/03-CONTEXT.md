# Phase 3: Event & Sensor Entities - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase — discuss skipped)

<domain>
## Phase Boundary

Camera state is visible in HA as real-time sensors, binary sensors, and event entities. Requirements: CONN-04 (connection binary_sensor), ALRM-05 (motion binary_sensor), ALRM-06 (alarm EventEntity), SDCD-01 (SD card status sensor), SYST-02 (device info sensor), DIAG-01 (diagnostics), DIAG-02 (capability dump).

These entities CONSUME data already available from Phase 1 (connection state) and Phase 2 (alarm params, SD status from get_status CGI). No new CGI commands needed — this is pure entity creation.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — entity creation phase.

Key HA platform patterns:
- binary_sensor.py — BinarySensorEntity for motion/connection state
- sensor.py — SensorEntity for SD card capacity, device info
- event.py — EventEntity for alarm events (HA 2023.8+)
- diagnostics.py — async_get_config_entry_diagnostics() for integration diagnostics

Data sources from coordinator.data (populated by Phase 1 & 2):
- connection_state — from Phase 1 ConnectionState enum
- alarm_params — from Phase 2 get_alarm_params polling
- status — from existing get_status polling (includes SD card info)
- camera_params — from existing get_camera_params polling

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- entity.py:PNZEOEntity — base entity with coordinator integration
- coordinator.py — polls camera_params and alarm_params every 60s
- const.py — ConnectionState enum, alarm type constants

### Integration Points
- __init__.py:PLATFORMS — add Platform.BINARY_SENSOR, Platform.SENSOR, Platform.EVENT
- coordinator.data — already contains connection_state, alarm_params, status

</code_context>

<specifics>
## Specific Ideas

No specific requirements — standard HA entity patterns.

</specifics>

<deferred>
## Deferred Ideas

None.

</deferred>
