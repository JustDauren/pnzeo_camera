"""Config flow for PNZEO Camera."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_DEVICE_ID, CONF_RTSP_PORT, DEFAULT_PASSWORD, DEFAULT_RTSP_PORT, DEFAULT_USERNAME, DOMAIN
from .pppp_discovery import check_rtsp, discover_cameras

_LOGGER = logging.getLogger(__name__)


class PNZEOConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for PNZEO Camera."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: list[dict] = []
        self._host: str = ""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle initial step — choose discovery or manual."""
        if user_input is not None:
            if user_input.get("method") == "discover":
                return await self.async_step_discover()
            return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("method", default="manual"): vol.In({
                    "manual": "Вручную (ввести IP)",
                    "discover": "Автопоиск в сети",
                }),
            }),
        )

    async def async_step_discover(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Discover cameras on LAN."""
        self._discovered = await discover_cameras()

        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        if len(self._discovered) == 1:
            self._host = self._discovered[0]["ip"]
            return await self.async_step_credentials()

        # Multiple cameras found
        cameras = {d["ip"]: f"{d['device_id']} ({d['ip']})" for d in self._discovered}
        return self.async_show_form(
            step_id="pick",
            data_schema=vol.Schema({
                vol.Required("ip"): vol.In(cameras),
            }),
        )

    async def async_step_pick(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Pick discovered camera."""
        if user_input:
            self._host = user_input["ip"]
            return await self.async_step_credentials()
        return await self.async_step_discover()

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manual entry."""
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            # Check RTSP
            if await check_rtsp(host):
                self._host = host
                return await self.async_step_credentials(user_input)
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
            }),
            errors=errors,
        )

    async def async_step_credentials(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Enter credentials."""
        errors = {}
        if user_input is not None and CONF_USERNAME in user_input:
            host = self._host
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            device_id = user_input.get(CONF_DEVICE_ID, "")
            rtsp_port = user_input.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT)

            # Verify RTSP works with credentials
            if await check_rtsp(host, rtsp_port):
                unique_id = device_id or host.replace(".", "_")
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"PNZEO {device_id or host}",
                    data={
                        CONF_HOST: host,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_DEVICE_ID: device_id,
                        CONF_RTSP_PORT: rtsp_port,
                    },
                )
            errors["base"] = "cannot_connect"

        # Pre-fill device_id if discovered
        device_id = ""
        for d in self._discovered:
            if d.get("ip") == self._host:
                device_id = d.get("device_id", "")
                break

        return self.async_show_form(
            step_id="credentials",
            data_schema=vol.Schema({
                vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
                vol.Required(CONF_PASSWORD, default=DEFAULT_PASSWORD): str,
                vol.Optional(CONF_DEVICE_ID, default=device_id): str,
                vol.Optional(CONF_RTSP_PORT, default=DEFAULT_RTSP_PORT): int,
            }),
            errors=errors,
        )
