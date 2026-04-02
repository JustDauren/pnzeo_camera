"""PNZEO Camera integration for Home Assistant.

Full local control of PNZEO/MTC cameras via PPPP protocol.
Cloud is used ONLY for port discovery (one UDP query), all data stays on LAN.
"""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall

from .const import (
    CONF_DEVICE_ID, CONF_RTSP_PORT, DEFAULT_RTSP_PORT, DOMAIN,
    PTZ_UP, PTZ_DOWN, PTZ_LEFT, PTZ_RIGHT, PTZ_CENTER,
    PTZ_ZOOM_IN, PTZ_ZOOM_OUT, PTZ_PATROL_LR, PTZ_PATROL_LR_STOP,
    PTZ_PATROL_UD, PTZ_PATROL_UD_STOP,
    PTZ_PRESET_SET_BASE, PTZ_PRESET_RUN_BASE,
)
from .coordinator import PNZEOCoordinator
from .device import PNZEODevice

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.CAMERA,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.TEXT,
]

PTZ_DIRECTIONS = {
    "up": PTZ_UP, "down": PTZ_DOWN, "left": PTZ_LEFT, "right": PTZ_RIGHT,
    "center": PTZ_CENTER, "home": PTZ_CENTER,
    "zoom_in": PTZ_ZOOM_IN, "zoom_out": PTZ_ZOOM_OUT,
    "patrol_lr": PTZ_PATROL_LR, "patrol_lr_stop": PTZ_PATROL_LR_STOP,
    "patrol_ud": PTZ_PATROL_UD, "patrol_ud_stop": PTZ_PATROL_UD_STOP,
}

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PNZEO Camera from config entry."""
    device = PNZEODevice(
        host=entry.data[CONF_HOST],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        device_id=entry.data.get(CONF_DEVICE_ID, ""),
        rtsp_port=entry.data.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT),
    )

    coordinator = PNZEOCoordinator(hass, device)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: PNZEOCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.device.async_teardown()

    return unload_ok


def _register_services(hass: HomeAssistant) -> None:
    """Register PNZEO services."""
    if hass.services.has_service(DOMAIN, "ptz_control"):
        return

    async def handle_ptz(call: ServiceCall) -> None:
        direction = call.data["direction"]
        step = call.data.get("step", 1)
        ptz_cmd = PTZ_DIRECTIONS.get(direction)
        if ptz_cmd is None:
            return
        for coordinator in hass.data[DOMAIN].values():
            if isinstance(coordinator, PNZEOCoordinator):
                await coordinator.device.client.ptz_control(ptz_cmd, step)
                break

    async def handle_goto_preset(call: ServiceCall) -> None:
        preset = call.data["preset"]
        if 0 <= preset <= 15:
            cmd = PTZ_PRESET_RUN_BASE + (preset * 2)
            for coordinator in hass.data[DOMAIN].values():
                if isinstance(coordinator, PNZEOCoordinator):
                    await coordinator.device.client.ptz_control(cmd)
                    break

    async def handle_set_preset(call: ServiceCall) -> None:
        preset = call.data["preset"]
        if 0 <= preset <= 15:
            cmd = PTZ_PRESET_SET_BASE + (preset * 2)
            for coordinator in hass.data[DOMAIN].values():
                if isinstance(coordinator, PNZEOCoordinator):
                    await coordinator.device.client.ptz_control(cmd)
                    break

    async def handle_send_command(call: ServiceCall) -> None:
        msg_type = call.data["msg_type"]
        if not 0 <= msg_type <= 255:
            return
        for coordinator in hass.data[DOMAIN].values():
            if isinstance(coordinator, PNZEOCoordinator):
                await coordinator.device.client.camera_control(msg_type, 0)
                break

    async def handle_change_password(call: ServiceCall) -> None:
        new_password = call.data["new_password"]
        for entry_id, coordinator in hass.data[DOMAIN].items():
            if isinstance(coordinator, PNZEOCoordinator):
                client = coordinator.device.client
                success = await client.change_password(new_password)
                if success:
                    entry = hass.config_entries.async_get_entry(entry_id)
                    if entry:
                        new_data = dict(entry.data)
                        new_data[CONF_PASSWORD] = new_password
                        hass.config_entries.async_update_entry(entry, data=new_data)
                break

    hass.services.async_register(
        DOMAIN, "ptz_control", handle_ptz,
        schema=vol.Schema({
            vol.Required("direction"): vol.In(list(PTZ_DIRECTIONS.keys())),
            vol.Optional("step", default=1): vol.In([0, 1]),
        }),
    )
    hass.services.async_register(
        DOMAIN, "goto_preset", handle_goto_preset,
        schema=vol.Schema({vol.Required("preset"): vol.All(int, vol.Range(0, 15))}),
    )
    hass.services.async_register(
        DOMAIN, "set_preset", handle_set_preset,
        schema=vol.Schema({vol.Required("preset"): vol.All(int, vol.Range(0, 15))}),
    )
    hass.services.async_register(
        DOMAIN, "send_command", handle_send_command,
        schema=vol.Schema({vol.Required("msg_type"): int}),
    )
    hass.services.async_register(
        DOMAIN, "change_password", handle_change_password,
        schema=vol.Schema({vol.Required("new_password"): str}),
    )

    async def handle_get_alarm_log(call: ServiceCall) -> None:
        for coordinator in hass.data[DOMAIN].values():
            if isinstance(coordinator, PNZEOCoordinator):
                log_entries = await coordinator.device.client.get_alarm_log()
                hass.bus.async_fire(
                    f"{DOMAIN}_alarm_log",
                    {"entries": log_entries},
                )
                break

    hass.services.async_register(
        DOMAIN, "get_alarm_log", handle_get_alarm_log,
        schema=vol.Schema({}),
    )

    async def handle_sync_time(call: ServiceCall) -> None:
        for coordinator in hass.data[DOMAIN].values():
            if isinstance(coordinator, PNZEOCoordinator):
                await coordinator.device.client.sync_time()
                break

    hass.services.async_register(
        DOMAIN, "sync_time", handle_sync_time,
        schema=vol.Schema({}),
    )

    async def handle_start_recording(call: ServiceCall) -> None:
        for coordinator in hass.data[DOMAIN].values():
            if isinstance(coordinator, PNZEOCoordinator):
                await coordinator.device.client.start_recording()
                break

    hass.services.async_register(
        DOMAIN, "start_recording", handle_start_recording,
        schema=vol.Schema({}),
    )
