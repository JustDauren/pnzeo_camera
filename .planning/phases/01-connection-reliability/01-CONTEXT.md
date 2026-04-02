# Phase 1: Connection Reliability - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase — discuss skipped)

<domain>
## Phase Boundary

The PPPP connection never silently dies and always recovers on its own. Requirements: CONN-01 (auto-reconnect with exponential backoff), CONN-02 (keepalive watchdog + logging), CONN-03 (socket lifecycle with context managers), CONN-05 (ConnectionState enum).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — pure infrastructure phase. Use ROADMAP phase goal, success criteria, and codebase conventions to guide decisions.

Key constraints from codebase analysis:
- Current code uses raw UDP sockets without context managers (CONCERNS.md)
- Keepalive loop swallows all exceptions silently (pppp_client.py line 398)
- No explicit state machine — boolean flags `_connected`, `_authenticated` (pppp_client.py lines 60-66)
- Cloud relay IPs hardcoded (pppp_client.py lines 43-46)
- Exponential backoff must not block the HA event loop

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `pppp_client.py` — PNZEOClient class with connect/disconnect/keepalive methods
- `coordinator.py` — PNZEOCoordinator with _async_update_data() polling
- `const.py` — PPPP_STATUS_* constants already defined for state machine

### Established Patterns
- asyncio-based with `asyncio.create_task()` for background tasks
- Coordinator polls every 60s via `DataUpdateCoordinator`
- Connection recovery is partially implemented but fragile

### Integration Points
- `coordinator.py:_async_update_data()` — must handle reconnection gracefully
- `__init__.py:async_setup_entry()` — initial connection setup
- `__init__.py:async_unload_entry()` — cleanup on unload

</code_context>

<specifics>
## Specific Ideas

No specific requirements — infrastructure phase. Refer to ROADMAP phase description and success criteria.

</specifics>

<deferred>
## Deferred Ideas

None — infrastructure phase.

</deferred>
