"""Config flow for NetPRO UPS USB."""

from __future__ import annotations

from dataclasses import dataclass
from glob import glob
from os import path
from collections import OrderedDict
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_PORT
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from serial.tools import list_ports

from .const import CONF_DEBUG_LOG, CONF_POLL_INTERVAL, CONF_PROTOCOL, DEFAULT_NAME, DEFAULT_POLL_INTERVAL, DOMAIN, PROTOCOL_MODBUS_ASCII
from .hub import NetproUpsUsbError, NetproUpsUsbHub

_LOGGER = logging.getLogger(__name__)

CONF_SKIP_CONNECTION_CHECK = "skip_connection_check"


@dataclass(slots=True)
class NetproDetectedPort:
    """Represent a detected serial port option."""

    value: str
    label: str


def _normalize_port_value(raw_port: Any) -> str:
    """Normalize selector payloads to a plain serial port string."""
    if isinstance(raw_port, str):
        return raw_port

    if isinstance(raw_port, dict):
        value = raw_port.get("value")
        if isinstance(value, str):
            return value

    if isinstance(raw_port, list) and len(raw_port) == 1:
        return _normalize_port_value(raw_port[0])

    raise ValueError(f"Unsupported serial port value: {raw_port!r}")


def _detect_serial_ports() -> list[NetproDetectedPort]:
    """Return detected serial ports, preferring stable /dev/serial/by-id paths."""
    by_id_map: dict[str, str] = {}
    for symlink in glob("/dev/serial/by-id/*"):
        try:
            by_id_map[path.realpath(symlink)] = symlink
        except OSError:
            continue

    detected: list[NetproDetectedPort] = []
    seen_values: set[str] = set()

    for port_info in sorted(list_ports.comports(), key=lambda item: item.device):
        hwid = port_info.hwid or ""
        if port_info.device.startswith("/dev/ttyS") and "USB" not in hwid and "VID" not in hwid:
            continue

        preferred_value = by_id_map.get(port_info.device, port_info.device)
        if preferred_value in seen_values:
            continue

        details: list[str] = []
        if port_info.description and port_info.description != "n/a":
            details.append(port_info.description)
        if port_info.hwid and port_info.hwid != "n/a":
            details.append(port_info.hwid)

        label = preferred_value
        if details:
            label = f"{preferred_value} | {' | '.join(details)}"

        detected.append(NetproDetectedPort(value=preferred_value, label=label))
        seen_values.add(preferred_value)

    return detected


def _port_schema_field(detected_ports: list[NetproDetectedPort], default_port: str) -> Any:
    """Return the appropriate schema field for the port selector."""
    if detected_ports:
        return SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict({"value": p.value, "label": p.label})
                    for p in detected_ports
                ],
                mode=SelectSelectorMode.DROPDOWN,
                custom_value=True,
            )
        )
    return str


class NetproUpsUsbConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NetPRO UPS USB."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Return the options flow."""
        return NetproUpsUsbOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        detected_ports = await self.hass.async_add_executor_job(_detect_serial_ports)
        _LOGGER.debug("Config flow opened. Detected %s serial ports.", len(detected_ports))

        if user_input is not None:
            try:
                entry_data = {
                    **user_input,
                    CONF_PORT: _normalize_port_value(user_input[CONF_PORT]),
                    CONF_PROTOCOL: PROTOCOL_MODBUS_ASCII,
                }

                skip_check = bool(entry_data.pop(CONF_SKIP_CONNECTION_CHECK, False))
                _LOGGER.info(
                    "Config flow submit for port %s, skip_check=%s",
                    entry_data[CONF_PORT],
                    skip_check,
                )

                hub = NetproUpsUsbHub(
                    name=entry_data[CONF_NAME],
                    port=entry_data[CONF_PORT],
                    protocol=entry_data[CONF_PROTOCOL],
                )

                if not skip_check:
                    try:
                        await hub.async_probe(self.hass)
                    except NetproUpsUsbError as err:
                        _LOGGER.warning(
                            "Initial probe failed for %s. Protocol hint: %s, serial profile: %s, diagnostics: %s",
                            entry_data[CONF_PORT],
                            hub.protocol_hint,
                            hub.serial_profile_name,
                            hub.diagnostic_summary or str(err),
                        )
                        errors["base"] = "cannot_connect"
                    else:
                        await self.async_set_unique_id(entry_data[CONF_PORT])
                        self._abort_if_unique_id_configured()
                        return self.async_create_entry(
                            title=entry_data[CONF_NAME],
                            data=entry_data,
                        )

                if skip_check:
                    await self.async_set_unique_id(entry_data[CONF_PORT])
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=entry_data[CONF_NAME],
                        data=entry_data,
                    )
            except ValueError as err:
                _LOGGER.warning("Invalid serial port value received in config flow: %s", err)
                errors[CONF_PORT] = "invalid_port"
            except Exception:
                _LOGGER.exception("Unexpected error while creating NetPRO UPS USB config entry")
                errors["base"] = "cannot_connect"

        default_port = (user_input.get(CONF_PORT) if user_input else None) or (detected_ports[0].value if detected_ports else "/dev/ttyUSB0")

        schema_fields: OrderedDict[vol.Marker, Any] = OrderedDict()
        schema_fields[vol.Required(CONF_NAME, default=DEFAULT_NAME)] = str
        schema_fields[vol.Required(CONF_PORT, default=default_port)] = _port_schema_field(detected_ports, default_port)
        schema_fields[vol.Required(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL)] = vol.All(vol.Coerce(int), vol.Range(min=5, max=300))
        schema_fields[vol.Optional(CONF_SKIP_CONNECTION_CHECK, default=False)] = bool

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema_fields),
            errors=errors,
        )


class NetproUpsUsbOptionsFlow(config_entries.OptionsFlow):
    """Handle options for NetPRO UPS USB."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        detected_ports = await self.hass.async_add_executor_job(_detect_serial_ports)

        current_port = self._entry.options.get(CONF_PORT, self._entry.data.get(CONF_PORT, ""))
        current_interval = self._entry.options.get(CONF_POLL_INTERVAL, self._entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
        current_debug = self._entry.options.get(CONF_DEBUG_LOG, False)

        if user_input is not None:
            try:
                new_port = _normalize_port_value(user_input[CONF_PORT])
            except ValueError as err:
                _LOGGER.warning("Invalid port in options: %s", err)
                errors[CONF_PORT] = "invalid_port"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_PORT: new_port,
                        CONF_POLL_INTERVAL: user_input[CONF_POLL_INTERVAL],
                        CONF_DEBUG_LOG: user_input[CONF_DEBUG_LOG],
                    },
                )

        schema_fields: OrderedDict[vol.Marker, Any] = OrderedDict()
        schema_fields[vol.Required(CONF_PORT, default=current_port)] = _port_schema_field(detected_ports, current_port)
        schema_fields[vol.Required(CONF_POLL_INTERVAL, default=current_interval)] = vol.All(vol.Coerce(int), vol.Range(min=5, max=300))
        schema_fields[vol.Optional(CONF_DEBUG_LOG, default=current_debug)] = bool

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_fields),
            errors=errors,
        )
