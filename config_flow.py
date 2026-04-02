"""Config flow for PNZEO Camera."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_CAPABILITIES, CONF_DEVICE_ID, CONF_RTSP_PORT,
    DEFAULT_PASSWORD, DEFAULT_RTSP_PORT, DEFAULT_USERNAME, DOMAIN,
)
from .pppp_client import PNZEOClient
from .pppp_discovery import check_rtsp, discover_cameras

_LOGGER = logging.getLogger(__name__)


class PNZEOConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for PNZEO Camera."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: list[dict] = []
        self._host: str = ""
        self._device_id: str = ""
        self._capabilities: dict = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PNZEOOptionsFlow:
        """Get the options flow handler."""
        return PNZEOOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle initial step -- choose discovery or manual."""
        if user_input is not None:
            if user_input.get("method") == "discover":
                return await self.async_step_discover()
            return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("method", default="discover"): vol.In({
                    "discover": "Auto-discover on LAN",
                    "manual": "Enter UID manually",
                }),
            }),
        )

    async def async_step_discover(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Discover cameras on LAN."""
        self._discovered = await discover_cameras()

        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        if len(self._discovered) == 1:
            d = self._discovered[0]
            self._host = d["ip"]
            self._device_id = d.get("device_id", "")
            return await self.async_step_credentials()

        # Multiple cameras found -- show pick list
        cameras = {d["ip"]: f"{d.get('device_id', 'unknown')} ({d['ip']})" for d in self._discovered}
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
            # Find device_id from discovered list
            for d in self._discovered:
                if d["ip"] == self._host:
                    self._device_id = d.get("device_id", "")
                    break
            return await self.async_step_credentials()
        return await self.async_step_discover()

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manual UID + optional IP entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._device_id = user_input.get(CONF_DEVICE_ID, "")
            self._host = user_input.get(CONF_HOST, "")

            if self._host:
                # Validate IP reachability via RTSP port check
                if not await check_rtsp(self._host):
                    errors["base"] = "cannot_connect"
                else:
                    return await self.async_step_credentials()
            else:
                # UID-only (cloud relay), proceed directly
                return await self.async_step_credentials()

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({
                vol.Required(CONF_DEVICE_ID): str,
                vol.Optional(CONF_HOST, default=""): str,
            }),
            errors=errors,
        )

    async def async_step_credentials(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Enter password and RTSP port. Validates via PPPP check_user.cgi."""
        errors: dict[str, str] = {}
        if user_input is not None and CONF_PASSWORD in user_input:
            password = user_input[CONF_PASSWORD]
            rtsp_port = user_input.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT)

            # Verify password via PPPP (15s max)
            pppp_ok = await self._verify_pppp_login(
                self._host, password, self._device_id
            )

            if pppp_ok is False:
                errors["base"] = "invalid_auth"
            else:
                # True = verified, None = can't check (allow anyway)
                unique_id = self._device_id or self._host.replace(".", "_")
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"PNZEO {self._device_id or self._host}",
                    data={
                        CONF_HOST: self._host,
                        CONF_USERNAME: DEFAULT_USERNAME,
                        CONF_PASSWORD: password,
                        CONF_DEVICE_ID: self._device_id,
                        CONF_RTSP_PORT: rtsp_port,
                        CONF_CAPABILITIES: self._capabilities,
                    },
                )

        return self.async_show_form(
            step_id="credentials",
            data_schema=vol.Schema({
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_RTSP_PORT, default=DEFAULT_RTSP_PORT): int,
            }),
            errors=errors,
        )

    async def _verify_pppp_login(
        self, host: str, password: str, device_id: str
    ) -> bool | None:
        """Fast password verification via PPPP CGI (max 15 seconds).

        Returns: True (accepted), False (wrong password), None (can't check)
        Also populates self._capabilities from check_user.cgi response.
        """
        client = PNZEOClient(host, DEFAULT_USERNAME, password, device_id)
        try:
            return await asyncio.wait_for(
                self._do_pppp_check(client),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            _LOGGER.debug("PPPP check timed out for %s, allowing anyway", host)
            self._capabilities = {}
            return None
        except Exception as ex:
            _LOGGER.debug("PPPP check error: %s", ex)
            self._capabilities = {}
            return None
        finally:
            await client.disconnect()

    async def _do_pppp_check(self, client: PNZEOClient) -> bool | None:
        """Actual PPPP login check. Captures capabilities on success."""
        connected = await client.connect()
        if not connected:
            self._capabilities = {}
            return None  # Can't connect -- allow anyway, will retry later
        # connect() already does CGI login -- if we're here, password was accepted
        if client.connected:
            self._capabilities = client.capabilities
            return True
        # Transport connected but CGI login failed
        self._capabilities = {}
        return None


class PNZEOOptionsFlow(OptionsFlow):
    """Options flow for PNZEO Camera -- change password, settings."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Main options page."""
        errors = {}

        if user_input is not None:
            new_password = user_input.get("new_password", "").strip()

            if new_password:
                # User wants to change camera password
                success = await self._change_camera_password(new_password)
                if success:
                    # Update config entry with new password
                    new_data = dict(self._entry.data)
                    new_data[CONF_PASSWORD] = new_password
                    self.hass.config_entries.async_update_entry(
                        self._entry, data=new_data
                    )
                    return self.async_create_entry(title="", data={})
                else:
                    errors["base"] = "password_change_failed"
            else:
                # No changes
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional("new_password", default=""): str,
            }),
            errors=errors,
        )

    async def _change_camera_password(self, new_password: str) -> bool:
        """Change password on the camera via PPPP."""
        data = self._entry.data
        client = PNZEOClient(
            host=data[CONF_HOST],
            username=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
            device_id=data.get(CONF_DEVICE_ID, ""),
        )
        try:
            if not await client.connect():
                _LOGGER.error("Cannot connect to camera for password change")
                return False

            result = await client.change_password(new_password)
            return result
        except Exception as ex:
            _LOGGER.error("Password change error: %s", ex)
            return False
        finally:
            await client.disconnect()
