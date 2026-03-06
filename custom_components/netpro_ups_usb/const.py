"""Constants for the NetPRO UPS USB integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "netpro_ups_usb"
LOGGER_NAME = "custom_components.netpro_ups_usb"

CONF_PROTOCOL = "protocol"
CONF_POLL_INTERVAL = "poll_interval"
CONF_DEBUG_LOG = "debug_log"

DEFAULT_NAME = "NetPRO UPS USB"
DEFAULT_POLL_INTERVAL = 30

PROTOCOL_AUTO = "auto"
PROTOCOL_SNT = "snt"
PROTOCOL_MODBUS = "modbus"
PROTOCOL_MODBUS_ASCII = "modbus_ascii"

SERIAL_BAUDRATE = 2400
SERIAL_TIMEOUT = 2.0

# Modbus RTU defaults
MODBUS_DEFAULT_SLAVE = 0x01

# Telemetry register range (Function 0x03): regs 0..56
MODBUS_TEL_START = 0
MODBUS_TEL_COUNT = 57

# Telesignalization register range (Function 0x04): regs 81..114
MODBUS_SIG_START = 81
MODBUS_SIG_COUNT = 34
LOG_FILE_NAME = "netpro_ups_usb.log"
LOG_MAX_BYTES = 1048576
LOG_BACKUP_COUNT = 3

PLATFORMS: list[Platform] = [
	Platform.SENSOR,
	Platform.BINARY_SENSOR,
	Platform.BUTTON,
]
