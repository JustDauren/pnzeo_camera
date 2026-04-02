"""Diagnostics support for PNZEO Camera integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import PNZEOCoordinator

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME, "loginuse", "loginpas", "pwd1", "pwd2", "pwd3"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: PNZEOCoordinator = hass.data[DOMAIN][entry.entry_id]
    client = coordinator.device.client

    return {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "connection": {
            "state": client.connection_state.name,
            "method": client.connection_method,
            "pppp_available": coordinator.pppp_available,
            "host": coordinator.device.host,
            "device_id": coordinator.device.device_id,
        },
        "capabilities": client.capabilities,
        "camera_state": async_redact_data(
            dict(coordinator.data) if coordinator.data else {},
            TO_REDACT,
        ),
    }
