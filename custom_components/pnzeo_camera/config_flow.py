"""Config flow for PNZEO Camera."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_DEVICE_ID, CONF_RTSP_PORT, DEFAULT_RTSP_PORT, DOMAIN
from .pppp_discovery import check_rtsp, discover_cameras

_LOGGER = logging.getLogger(__name__)


class PNZEOConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovered: list[dict] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            if user_input.get("method") == "discover":
                return await self.async_step_discover()
            return await self.async_step_manual()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("method", default="discover"): vol.In({
                    "discover": "Автопоиск в сети",
                    "manual": "Вручную (ввести IP)",
                }),
            }),
        )

    async def async_step_discover(self, user_input=None) -> FlowResult:
        self._discovered = await discover_cameras()
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")
        if len(self._discovered) == 1:
            return await self._create_from_discovery(self._discovered[0])
        cameras = {d["ip"]: f"Камера ({d['ip']})" for d in self._discovered}
        return self.async_show_form(
            step_id="pick",
            data_schema=vol.Schema({vol.Required("ip"): vol.In(cameras)}),
        )

    async def async_step_pick(self, user_input=None) -> FlowResult:
        if user_input:
            for d in self._discovered:
                if d["ip"] == user_input["ip"]:
                    return await self._create_from_discovery(d)
        return await self.async_step_discover()

    async def async_step_manual(self, user_input=None) -> FlowResult:
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            if await check_rtsp(host):
                unique_id = host.replace(".", "_")
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"PNZEO {host}",
                    data={CONF_HOST: host, CONF_RTSP_PORT: DEFAULT_RTSP_PORT},
                )
            errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    async def _create_from_discovery(self, device: dict) -> FlowResult:
        ip = device["ip"]
        unique_id = device.get("device_id", ip.replace(".", "_"))
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"PNZEO {ip}",
            data={CONF_HOST: ip, CONF_DEVICE_ID: unique_id, CONF_RTSP_PORT: DEFAULT_RTSP_PORT},
        )
