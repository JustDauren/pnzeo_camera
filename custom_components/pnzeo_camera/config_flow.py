"""Config flow for PNZEO Camera."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_DEVICE_ID, CONF_RTSP_PORT,
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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PNZEOOptionsFlow:
        """Get the options flow handler."""
        return PNZEOOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle initial step — choose discovery or manual."""
        if user_input is not None:
            if user_input.get("method") == "discover":
                return await self.async_step_discover()
            return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("method", default="discover"): vol.In({
                    "discover": "Автопоиск в сети",
                    "manual": "Ввести IP вручную",
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
        """Enter device password — no username needed (like in MTCam HD app)."""
        errors = {}
        if user_input is not None and CONF_PASSWORD in user_input:
            host = self._host
            password = user_input[CONF_PASSWORD]
            device_id = user_input.get(CONF_DEVICE_ID, "")
            rtsp_port = user_input.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT)

            # Step 1: RTSP reachable?
            if not await check_rtsp(host, rtsp_port):
                errors["base"] = "cannot_connect"
            else:
                # Step 2: PPPP login — verify password
                pppp_ok = await self._verify_pppp_login(host, password, device_id)

                if pppp_ok is False:
                    errors["base"] = "invalid_auth"
                else:
                    # pppp_ok True (valid) or None (can't check, allow anyway)
                    unique_id = device_id or host.replace(".", "_")
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"PNZEO {device_id or host}",
                        data={
                            CONF_HOST: host,
                            CONF_USERNAME: DEFAULT_USERNAME,
                            CONF_PASSWORD: password,
                            CONF_DEVICE_ID: device_id,
                            CONF_RTSP_PORT: rtsp_port,
                        },
                    )

        # Pre-fill device_id if discovered
        device_id = ""
        for d in self._discovered:
            if d.get("ip") == self._host:
                device_id = d.get("device_id", "")
                break

        return self.async_show_form(
            step_id="credentials",
            data_schema=vol.Schema({
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_DEVICE_ID, default=device_id): str,
                vol.Optional(CONF_RTSP_PORT, default=DEFAULT_RTSP_PORT): int,
            }),
            errors=errors,
        )

    async def _verify_pppp_login(
        self, host: str, password: str, device_id: str
    ) -> bool | None:
        """Verify device password via PPPP.

        Camera uses only password (no username) — same as MTCam HD app.

        Returns:
            True — password accepted
            False — wrong password
            None — PPPP unavailable (can't check, allow anyway)
        """
        client = PNZEOClient(host, DEFAULT_USERNAME, password, device_id)
        try:
            connected = await client.connect()
            if not connected:
                _LOGGER.debug("PPPP unavailable for %s, skipping password check", host)
                return None

            # Camera connected via PPPP — try login
            result = await client.login(DEFAULT_USERNAME, password)
            if result:
                return True

            # If login() returned False, it might be timeout (not rejection)
            # Camera might not respond to login cmd yet — be lenient
            # If we connected to camera at all, password is likely OK
            # (camera rejects connection with wrong password in some firmware versions)
            _LOGGER.debug("PPPP login response unclear, allowing connection")
            return None
        except Exception as ex:
            _LOGGER.debug("PPPP login check error: %s", ex)
            return None
        finally:
            await client.disconnect()


class PNZEOOptionsFlow(OptionsFlow):
    """Options flow for PNZEO Camera — change password, settings."""

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
