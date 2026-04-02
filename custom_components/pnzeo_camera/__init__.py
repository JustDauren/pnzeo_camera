"""PNZEO Camera integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICE_ID, CONF_RTSP_PORT, DEFAULT_RTSP_PORT, DOMAIN
from .coordinator import PNZEOCoordinator
from .device import PNZEODevice

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CAMERA, Platform.SWITCH, Platform.BUTTON, Platform.NUMBER, Platform.SELECT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    device = PNZEODevice(
        host=entry.data[CONF_HOST],
        username=entry.data.get(CONF_USERNAME, "admin"),
        password=entry.data.get(CONF_PASSWORD, "admin"),
        device_id=entry.data.get(CONF_DEVICE_ID, ""),
        rtsp_port=entry.data.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT),
    )
    coordinator = PNZEOCoordinator(hass, device)
    # Quick first check — no PPPP, just RTSP port probe
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
