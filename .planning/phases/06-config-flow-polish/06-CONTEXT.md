# Phase 6: Config Flow & Polish - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped)

<domain>
## Phase Boundary

New users can set up the integration in under 2 minutes with auto-discovery and validation. Requirements: CONF-01 (auto-discovery via LAN scan), CONF-02 (manual UID fallback), CONF-03 (password validation), CONF-04 (capability detection at setup).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion.

Key requirements:
- Auto-discovery uses existing pppp_discovery.py (UDP 8600 + 32108)
- User selects from discovered camera list
- Manual UID entry as fallback when discovery fails
- Password validated during setup via check_user.cgi
- RTGetCapability at setup → store capabilities in config_entry.data
- Entities created conditionally based on capabilities

Current config_flow.py already has basic flow — needs enhancement:
- Add discovery step before credential entry
- Add validation step after password entry
- Add capability detection step
- Store capabilities for entity creation

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- config_flow.py — existing ConfigFlow with user step
- pppp_discovery.py — discover_cameras() function
- pppp_client.py — check_user CGI, get_capability CGI

</code_context>

<specifics>
## Specific Ideas

None — standard HA config flow patterns.

</specifics>

<deferred>
## Deferred Ideas

None.

</deferred>
