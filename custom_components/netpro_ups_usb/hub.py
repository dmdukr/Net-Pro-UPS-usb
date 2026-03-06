"""USB serial transport for NetPRO UPS."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import os
import time

from homeassistant.core import HomeAssistant
import serial
from serial import SerialException

from .const import (
    DOMAIN,
    MODBUS_DEFAULT_SLAVE,
    MODBUS_SIG_COUNT,
    MODBUS_SIG_START,
    MODBUS_TEL_COUNT,
    MODBUS_TEL_START,
    PROTOCOL_AUTO,
    PROTOCOL_MODBUS,
    PROTOCOL_MODBUS_ASCII,
    PROTOCOL_SNT,
    SERIAL_TIMEOUT,
)
from .modbus_ascii import (
    ModbusAsciiError,
    build_ascii_request,
    build_ascii_write_single,
    parse_ascii_response,
)
from .modbus_rtu import (
    FUNC_READ_HOLDING,
    FUNC_READ_INPUT,
    ModbusError,
    build_read_request,
    build_write_single_request,
    parse_read_response,
    to_signed,
)

_LOGGER = logging.getLogger(__name__)


class NetproUpsUsbError(Exception):
    """Base integration error."""


@dataclass(slots=True, frozen=True)
class NetproSerialProfile:
    """Serial line profile used to reach the UPS."""

    name: str
    baudrate: int
    dtr: bool
    rts: bool
    settle_delay: float


@dataclass(slots=True)
class NetproUpsStatus:
    """Parsed UPS status."""

    input_voltage: float
    input_voltage_l2: float | None
    input_voltage_l3: float | None
    input_fault_voltage: float
    output_voltage: float
    output_voltage_l2: float | None
    output_voltage_l3: float | None
    load_percent: int
    input_frequency: float
    output_frequency: float | None
    battery_voltage: float
    battery_level_percent: int | None
    runtime_seconds: int | None
    temperature_celsius: float
    utility_fail: bool
    battery_low: bool
    bypass_active: bool
    ups_failed: bool
    standby_ups: bool
    test_in_progress: bool
    battery_test_result: int | None  # 0=No Test 1=Success 2=Fail 3=Testing
    shutdown_active: bool
    beeper_on: bool
    input_current_a: float | None
    output_power_kw: float | None
    output_apparent_power_kva: float | None
    output_power_factor: float | None
    battery_current_a: float | None
    battery_connected: bool
    input_neutral_lost: bool
    status_bits: str
    mode_code: str | None
    query_command: str

    @property
    def operating_mode(self) -> str:
        """Return a user-facing operating mode."""
        if self.mode_code is not None:
            return _mode_code_to_operating_mode(self.mode_code)
        if self.ups_failed:
            return "fault"
        if self.utility_fail:
            return "on_battery"
        if self.bypass_active:
            return "bypass"
        if self.standby_ups:
            return "standby"
        return "online"


@dataclass(slots=True)
class NetproUpsInfo:
    """Static UPS information."""

    manufacturer: str
    model: str
    firmware_version: str


@dataclass(slots=True)
class NetproUpsRating:
    """UPS nominal ratings."""

    rating_voltage: float
    rating_current: float
    battery_voltage_nominal: float
    rating_frequency: float


@dataclass(slots=True)
class NetproUpsSnapshot:
    """Combined UPS snapshot."""

    status: NetproUpsStatus
    info: NetproUpsInfo | None
    rating: NetproUpsRating | None


class NetproUpsUsbHub:
    """Handle NetPRO UPS communication over USB serial."""

    _SNT_PROFILES: tuple[NetproSerialProfile, ...] = (
        NetproSerialProfile("snt_normal_2400", 2400, True, False, 0.15),
        NetproSerialProfile("snt_reverse_2400", 2400, False, True, 1.10),
        NetproSerialProfile("snt_both_2400", 2400, True, True, 0.15),
        NetproSerialProfile("snt_none_2400", 2400, False, False, 0.15),
        NetproSerialProfile("snt_normal_9600", 9600, True, False, 0.15),
        NetproSerialProfile("snt_reverse_9600", 9600, False, True, 1.10),
    )

    _MODBUS_PROFILES: tuple[NetproSerialProfile, ...] = (
        NetproSerialProfile("mb_9600_normal", 9600, True, False, 0.10),
        NetproSerialProfile("mb_9600_reverse", 9600, False, True, 0.50),
        NetproSerialProfile("mb_9600_both", 9600, True, True, 0.10),
        NetproSerialProfile("mb_9600_none", 9600, False, False, 0.10),
        NetproSerialProfile("mb_19200_normal", 19200, True, False, 0.10),
        NetproSerialProfile("mb_19200_reverse", 19200, False, True, 0.50),
        NetproSerialProfile("mb_2400_normal", 2400, True, False, 0.15),
        NetproSerialProfile("mb_2400_reverse", 2400, False, True, 0.50),
        NetproSerialProfile("mb_4800_normal", 4800, True, False, 0.10),
        NetproSerialProfile("mb_4800_reverse", 4800, False, True, 0.50),
    )

    def __init__(self, name: str, port: str, protocol: str) -> None:
        self.name = name
        self.port = port
        self.protocol = protocol
        self._info: NetproUpsInfo | None = None
        self._rating: NetproUpsRating | None = None
        self._protocol_hint: str | None = None
        self._detected_protocol: str | None = None
        self._serial_profile: NetproSerialProfile | None = None
        self._modbus_profile: NetproSerialProfile | None = None
        self._last_diagnostics: list[str] = []
        self._lock = asyncio.Lock()
        _LOGGER.debug("Hub initialized for %s on port %s using protocol %s", name, port, protocol)

    @property
    def diagnostic_summary(self) -> str:
        """Return a compact human-readable summary of recent failures."""
        if not self._last_diagnostics:
            return "no diagnostics collected"
        return " | ".join(self._last_diagnostics[-8:])

    @property
    def protocol_hint(self) -> str | None:
        """Return the detected protocol hint, if any."""
        return self._protocol_hint

    @property
    def serial_profile_name(self) -> str | None:
        """Return the active serial profile name, if any."""
        return self._serial_profile.name if self._serial_profile else None

    def _remember_diagnostic(self, message: str) -> None:
        """Store recent diagnostics for UI/logging."""
        self._last_diagnostics.append(message)
        if len(self._last_diagnostics) > 20:
            self._last_diagnostics = self._last_diagnostics[-20:]

    async def async_probe(self, hass: HomeAssistant) -> None:
        """Check whether the configured UPS is reachable."""
        _LOGGER.info("Starting UPS probe on %s", self.port)
        await self.async_fetch_snapshot(hass)

    async def async_fetch_snapshot(self, hass: HomeAssistant) -> NetproUpsSnapshot:
        """Fetch a fresh UPS snapshot."""
        async with self._lock:
            effective = self._detected_protocol or self.protocol

            if effective == PROTOCOL_MODBUS_ASCII:
                return await hass.async_add_executor_job(self._fetch_modbus_ascii)
            if effective == PROTOCOL_MODBUS:
                return await hass.async_add_executor_job(self._fetch_modbus)
            if effective == PROTOCOL_SNT:
                return await hass.async_add_executor_job(self._fetch_snt)

            # AUTO — try Modbus ASCII first (HT31/HT33 TX models), then RTU, then SNT.
            for fetch_fn, proto_name in (
                (self._fetch_modbus_ascii, PROTOCOL_MODBUS_ASCII),
                (self._fetch_modbus, PROTOCOL_MODBUS),
                (self._fetch_snt, PROTOCOL_SNT),
            ):
                try:
                    snap = await hass.async_add_executor_job(fetch_fn)
                    self._detected_protocol = proto_name
                    _LOGGER.info("Auto-detected protocol: %s on %s", proto_name, self.port)
                    return snap
                except NetproUpsUsbError:
                    _LOGGER.debug("Protocol %s failed on %s, trying next", proto_name, self.port)

            raise NetproUpsUsbError(
                f"Unable to communicate with UPS on {self.port} "
                "using Modbus ASCII, Modbus RTU, or SNT protocol"
            )

    # ------------------------------------------------------------------
    # Modbus RTU path
    # ------------------------------------------------------------------

    def _fetch_modbus(self) -> NetproUpsSnapshot:
        """Read telemetry + telesignalization via Modbus RTU."""
        self._last_diagnostics = []
        _LOGGER.debug("Fetching Modbus snapshot from %s", self.port)

        tel_regs = self._modbus_read_registers(
            FUNC_READ_HOLDING, MODBUS_TEL_START, MODBUS_TEL_COUNT,
        )
        sig_regs = self._modbus_read_registers(
            FUNC_READ_INPUT, MODBUS_SIG_START, MODBUS_SIG_COUNT,
        )

        status = self._build_modbus_status(tel_regs, sig_regs)

        if self._info is None:
            self._info = self._build_modbus_info(tel_regs)

        if self._rating is None:
            self._rating = self._build_modbus_rating(tel_regs)

        return NetproUpsSnapshot(status=status, info=self._info, rating=self._rating)

    # ------------------------------------------------------------------
    # Modbus ASCII path
    # ------------------------------------------------------------------

    # Single fixed profile: 9600 8N1, no DTR/RTS toggling
    _MODBUS_ASCII_PROFILE = NetproSerialProfile("ascii_9600_8n1", 9600, False, False, 0.3)

    # Seconds to wait for port to reappear after USB disconnect
    _PORT_RECONNECT_TIMEOUT = 15.0

    def _fetch_modbus_ascii(self) -> NetproUpsSnapshot:
        """Read all registers via Modbus ASCII (two block requests)."""
        _LOGGER.debug("Fetching Modbus ASCII snapshot from %s", self.port)
        self._last_diagnostics = []

        profile = self._MODBUS_ASCII_PROFILE
        try:
            with self._open_serial(profile) as ser:
                ser.reset_input_buffer()

                # FC03: regs 1..78 (78 registers)
                ser.write(build_ascii_request(MODBUS_DEFAULT_SLAVE, 0x03, 1, 78))
                raw03 = self._read_ascii_frame(ser)
                tel_raw = parse_ascii_response(raw03, 78)
                # Prepend dummy [0] so tel[reg] == value at register <reg>
                tel = [0] + tel_raw

                # FC04: regs 81..115 (35 registers), sig[i] == reg (81+i)
                ser.write(build_ascii_request(MODBUS_DEFAULT_SLAVE, 0x04, 81, 35))
                raw04 = self._read_ascii_frame(ser)
                sig = parse_ascii_response(raw04, 35)

        except (SerialException, NetproUpsUsbError) as err:
            # Port may have temporarily disconnected — wait and retry once
            _LOGGER.warning("Serial error on %s: %s — waiting for reconnect", self.port, err)
            self._remember_diagnostic(f"serial error, waiting: {err}")
            deadline = time.monotonic() + self._PORT_RECONNECT_TIMEOUT
            while time.monotonic() < deadline:
                if os.path.exists(self.port):
                    time.sleep(1.0)  # let the device settle
                    break
                time.sleep(0.5)
            else:
                raise NetproUpsUsbError(
                    f"Port {self.port} did not reappear within {self._PORT_RECONNECT_TIMEOUT}s"
                ) from err
            # Retry once after reconnect
            try:
                with self._open_serial(profile) as ser:
                    ser.reset_input_buffer()
                    ser.write(build_ascii_request(MODBUS_DEFAULT_SLAVE, 0x03, 1, 78))
                    raw03 = self._read_ascii_frame(ser)
                    tel_raw = parse_ascii_response(raw03, 78)
                    tel = [0] + tel_raw
                    ser.write(build_ascii_request(MODBUS_DEFAULT_SLAVE, 0x04, 81, 35))
                    raw04 = self._read_ascii_frame(ser)
                    sig = parse_ascii_response(raw04, 35)
            except (SerialException, ModbusAsciiError, NetproUpsUsbError) as retry_err:
                self._remember_diagnostic(f"retry failed: {retry_err}")
                raise NetproUpsUsbError(
                    f"Modbus ASCII failed after reconnect on {self.port}: {retry_err}"
                ) from retry_err
        except ModbusAsciiError as err:
            self._remember_diagnostic(f"ASCII parse: {err}")
            raise NetproUpsUsbError(
                f"Modbus ASCII read failed on {self.port}: {err}"
            ) from err

        status = self._build_modbus_status(tel, sig)

        if self._info is None:
            self._info = self._build_modbus_info(tel)

        if self._rating is None:
            self._rating = self._build_modbus_rating(tel)

        return NetproUpsSnapshot(status=status, info=self._info, rating=self._rating)

    @staticmethod
    def _read_ascii_frame(ser: serial.Serial, timeout: float = 3.0) -> bytes:
        """Read one complete Modbus ASCII frame (colon-prefixed, ends with \\r\\n)."""
        buf = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ch = ser.read(1)
            if ch:
                buf.extend(ch)
                if len(buf) > 1 and buf[-1:] == b"\n":
                    return bytes(buf)
            else:
                time.sleep(0.01)
        return bytes(buf)

    def _modbus_candidate_profiles(self) -> tuple[NetproSerialProfile, ...]:
        """Return Modbus profiles, last-successful first."""
        if self._modbus_profile is None:
            return self._MODBUS_PROFILES
        return (self._modbus_profile,) + tuple(
            p for p in self._MODBUS_PROFILES if p != self._modbus_profile
        )

    def _modbus_read_registers(
        self, func: int, start: int, count: int,
    ) -> list[int]:
        """Read a contiguous block of Modbus registers, trying all profiles."""
        request = build_read_request(MODBUS_DEFAULT_SLAVE, func, start, count)
        expected_len = 5 + 2 * count
        last_error: NetproUpsUsbError | None = None

        for profile in self._modbus_candidate_profiles():
            try:
                raw = self._modbus_exchange_raw(profile, request, expected_len)
                regs = parse_read_response(raw, MODBUS_DEFAULT_SLAVE, func)
                self._modbus_profile = profile
                return regs
            except (NetproUpsUsbError, ModbusError) as err:
                last_error = NetproUpsUsbError(str(err))
                tag = f"MB 0x{func:02X} reg{start}/{profile.name}"
                self._remember_diagnostic(f"{tag}: {err}")
                _LOGGER.debug("%s on %s: %s", tag, self.port, err)

        raise NetproUpsUsbError(
            f"Modbus read func=0x{func:02X} start={start} count={count} "
            f"failed on {self.port}. Last: {last_error}"
        )

    def _modbus_exchange_raw(
        self,
        profile: NetproSerialProfile,
        request: bytes,
        expected_len: int,
    ) -> bytes:
        """Send a raw Modbus request and return the raw response bytes."""
        _LOGGER.debug(
            "Modbus TX on %s [%s]: %s", self.port, profile.name, request.hex(),
        )
        with self._open_serial(profile) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            # Modbus RTU inter-frame silence: >= 3.5 char times
            silence = max(0.005, 3.5 * 11 / profile.baudrate)
            time.sleep(silence)
            ser.write(request)
            ser.flush()
            # Wait for TX to physically leave the wire
            tx_time = len(request) * 11 / profile.baudrate
            time.sleep(tx_time + silence)
            response = self._read_modbus_frame(ser, expected_len)

        if response:
            _LOGGER.debug(
                "Modbus RX on %s [%s] (%d bytes): %s",
                self.port, profile.name, len(response), response.hex(),
            )
        else:
            _LOGGER.debug(
                "Modbus RX on %s [%s]: empty (0 bytes)",
                self.port, profile.name,
            )
            raise NetproUpsUsbError("No Modbus response received")

        return response

    @staticmethod
    def _read_modbus_frame(ser: serial.Serial, expected_len: int) -> bytes:
        """Read *expected_len* bytes from *ser* within SERIAL_TIMEOUT."""
        deadline = time.monotonic() + SERIAL_TIMEOUT
        buf = bytearray()
        while time.monotonic() < deadline:
            remaining = expected_len - len(buf)
            chunk = ser.read(max(remaining, 1))
            if chunk:
                buf.extend(chunk)
                if len(buf) >= expected_len:
                    break
            else:
                time.sleep(0.02)
        if buf and len(buf) < expected_len:
            _LOGGER.debug(
                "Modbus partial RX (%d/%d bytes): %s",
                len(buf), expected_len, bytes(buf).hex(),
            )
        return bytes(buf)

    def _build_modbus_status(
        self, tel: list[int], sig: list[int],
    ) -> NetproUpsStatus:
        """Map Modbus register values to NetproUpsStatus."""
        # Telemetry (Function 0x03), registers 0..56
        input_voltage = tel[13] * 0.1
        output_voltage = tel[25] * 0.1
        output_current = tel[28] * 0.1
        input_freq = tel[19] * 0.01
        output_freq = tel[31] * 0.01
        load_pct = tel[46] * 0.1
        batt_v_pos = tel[50] * 0.1
        batt_v_neg = tel[51] * 0.1
        batt_voltage = batt_v_pos + batt_v_neg
        batt_capacity = tel[56] * 0.1
        batt_remain_min = tel[55] * 0.1
        batt_temp = tel[54] * 0.1

        # Additional FC03 telemetry
        input_current = round(tel[16] * 0.1, 1) if tel[16] else None
        output_power_kw = round(tel[40] * 0.1, 2) if tel[40] else None
        output_kva = round(tel[37] * 0.1, 2) if tel[37] else None
        output_pf = round(tel[34] * 0.01, 2) if tel[34] else None
        battery_current = round((tel[52] - tel[53]) * 0.1, 1) if (tel[52] or tel[53]) else None

        # Telesignalization (Function 0x04), registers 81..114
        # sig index 0 = register 81, index 1 = register 82, etc.
        load_source = sig[0]      # 0=None 1=UPS 2=Bypass
        batt_status = sig[1]      # 0=Not Work 1=Float 2=Boost 3=Discharge
        batt_connected = sig[2]   # reg 83: 0=Not Connect 1=Connect
        input_fail = sig[7]       # reg 88: 0=Normal 1=Abnormal
        bypass_fail = sig[10]     # reg 91
        output_shorted = sig[15]  # reg 96
        batt_eod = sig[16]        # reg 97
        batt_test_result = sig[18]  # reg 99: 0/1/2/3
        batt_low = sig[26]        # reg 107
        epo = sig[4]              # reg 85
        neutral_lost = sig[29]    # reg 110: 0=No Lost 1=Lost

        utility_fail = input_fail == 1
        bypass_active = load_source == 2
        on_battery = batt_status == 3
        testing = batt_test_result == 3

        ups_failed = (
            bypass_fail == 1
            or output_shorted == 1
        )

        # Phase B/C voltages (regs 14/15, 26/27); 0 = not populated on this model
        input_voltage_l2 = round(tel[14] * 0.1, 1) if tel[14] else None
        input_voltage_l3 = round(tel[15] * 0.1, 1) if tel[15] else None
        output_voltage_l2 = round(tel[26] * 0.1, 1) if tel[26] else None
        output_voltage_l3 = round(tel[27] * 0.1, 1) if tel[27] else None

        # Operating mode code derived from load source
        _src_to_mode = {0: "S", 1: "L", 2: "B"}
        modbus_mode_code = _src_to_mode.get(load_source, "L")

        return NetproUpsStatus(
            input_voltage=round(input_voltage, 1),
            input_voltage_l2=input_voltage_l2,
            input_voltage_l3=input_voltage_l3,
            input_fault_voltage=round(tel[1] * 0.1, 1),  # bypass voltage as fallback
            output_voltage=round(output_voltage, 1),
            output_voltage_l2=output_voltage_l2,
            output_voltage_l3=output_voltage_l3,
            load_percent=int(round(load_pct)),
            input_frequency=round(input_freq, 2),
            output_frequency=round(output_freq, 2),
            battery_voltage=round(batt_voltage, 1),
            battery_level_percent=int(round(batt_capacity)),
            runtime_seconds=int(batt_remain_min * 60) if batt_remain_min > 0 else None,
            temperature_celsius=round(batt_temp, 1),
            utility_fail=utility_fail or on_battery,
            battery_low=batt_low == 1 or batt_eod == 1,
            bypass_active=bypass_active,
            ups_failed=ups_failed,
            standby_ups=load_source == 0,
            test_in_progress=testing,
            battery_test_result=batt_test_result,
            shutdown_active=epo == 1,
            beeper_on=False,
            input_current_a=input_current,
            output_power_kw=output_power_kw,
            output_apparent_power_kva=output_kva,
            output_power_factor=output_pf,
            battery_current_a=battery_current,
            battery_connected=batt_connected == 1,
            input_neutral_lost=neutral_lost == 1,
            status_bits=f"src={load_source} bat={batt_status}",
            mode_code=modbus_mode_code,
            query_command="MODBUS",
        )

    @staticmethod
    def _build_modbus_info(tel: list[int]) -> NetproUpsInfo:
        """Extract identification from Modbus telemetry."""
        series_map = {
            1: "RMX", 2: "RM", 3: "HT33-L", 4: "HTX33",
            5: "HT33", 6: "HT31", 7: "HT11", 8: "HT11-S", 9: "HT31 TX",
        }
        series_num = tel[78] & 0x3F if len(tel) > 78 else 0
        model = series_map.get(series_num, f"Series-{series_num}")
        mon_ver1 = tel[69] if len(tel) > 69 else 0
        mon_ver2 = tel[70] if len(tel) > 70 else 0
        return NetproUpsInfo(
            manufacturer="NetPRO",
            model=model,
            firmware_version=f"MON {mon_ver1}.{mon_ver2}",
        )

    @staticmethod
    def _build_modbus_rating(tel: list[int]) -> NetproUpsRating:
        """Build nominal ratings from Modbus telemetry (best-effort)."""
        return NetproUpsRating(
            rating_voltage=round(tel[25] * 0.1, 1) if tel[25] else 220.0,
            rating_current=round(tel[28] * 0.1, 1) if tel[28] else 0.0,
            battery_voltage_nominal=round((tel[50] + tel[51]) * 0.1, 1),
            rating_frequency=round(tel[31] * 0.01, 2) if tel[31] else 50.0,
        )

    def _modbus_write_register(self, reg_addr: int, value: int) -> None:
        """Write a single Modbus register (Function 0x06)."""
        request = build_write_single_request(MODBUS_DEFAULT_SLAVE, reg_addr, value)
        last_error: NetproUpsUsbError | None = None

        for profile in self._modbus_candidate_profiles():
            try:
                raw = self._modbus_exchange_raw(profile, request, 8)
                self._modbus_profile = profile
                return
            except (NetproUpsUsbError, ModbusError) as err:
                last_error = NetproUpsUsbError(str(err))
                self._remember_diagnostic(f"MB write reg{reg_addr}/{profile.name}: {err}")

        raise NetproUpsUsbError(
            f"Modbus write reg={reg_addr} failed on {self.port}. Last: {last_error}"
        )

    # ------------------------------------------------------------------
    # SNT (ASCII) path
    # ------------------------------------------------------------------

    def _fetch_snt(self) -> NetproUpsSnapshot:
        """Fetch snapshot via traditional SNT ASCII protocol."""
        _LOGGER.debug("Fetching SNT snapshot from %s", self.port)
        self._last_diagnostics = []
        status = self._query_status()

        if self._info is None:
            self._info = self._query_info_optional()

        if self._rating is None:
            self._rating = self._query_rating_optional()

        return NetproUpsSnapshot(
            status=status,
            info=self._info,
            rating=self._rating,
        )

    async def async_send_command(self, hass: HomeAssistant, command: str) -> None:
        """Send a control command to the UPS."""
        effective = self._detected_protocol or self.protocol
        async with self._lock:
            if effective in (PROTOCOL_MODBUS, PROTOCOL_MODBUS_ASCII):
                await hass.async_add_executor_job(
                    self._modbus_send_command, command,
                )
            else:
                await hass.async_add_executor_job(self._write_command, command)

    def _modbus_send_command(self, command: str) -> None:
        """Translate an SNT-style command to a Modbus write if possible."""
        # Battery Test Begin = reg 98, value 1
        # Stop Test = reg 102, value 1
        cmd_map = {
            "Q": (98, 1),   # self-test
            "T": (98, 1),   # 10-second test (same register)
            "TL": (98, 1),  # test until low
            "CT": (102, 1), # cancel test
        }
        mapped = cmd_map.get(command.upper())
        if mapped is None:
            raise NetproUpsUsbError(
                f"Command '{command}' not supported in Modbus mode"
            )
        effective = self._detected_protocol or self.protocol
        if effective == PROTOCOL_MODBUS_ASCII:
            self._ascii_write_register(mapped[0], mapped[1])
        else:
            self._modbus_write_register(mapped[0], mapped[1])

    def _ascii_write_register(self, reg: int, value: int) -> None:
        """Write a single register via Modbus ASCII (FC06)."""
        profile = self._MODBUS_ASCII_PROFILE
        try:
            with self._open_serial(profile) as ser:
                ser.reset_input_buffer()
                ser.write(build_ascii_write_single(MODBUS_DEFAULT_SLAVE, reg, value))
                self._read_ascii_frame(ser)  # read and discard echo/response
        except (NetproUpsUsbError, SerialException) as err:
            raise NetproUpsUsbError(
                f"ASCII write reg={reg} val={value} failed: {err}"
            ) from err

    def device_identifier(self) -> str:
        """Return the stable device identifier."""
        return self.port

    def device_info_payload(self) -> dict:
        """Build Home Assistant device info."""
        return {
            "identifiers": {(DOMAIN, self.device_identifier())},
            "name": self.name,
            "manufacturer": self._info.manufacturer if self._info else "NetPRO UPS",
            "model": self._info.model if self._info else "USB UPS",
            "sw_version": self._info.firmware_version if self._info else None,
        }

    def _candidate_profiles(self) -> tuple[NetproSerialProfile, ...]:
        """Return candidate SNT serial profiles with the last successful one first."""
        if self._serial_profile is None:
            return self._SNT_PROFILES

        return (self._serial_profile,) + tuple(
            profile for profile in self._SNT_PROFILES if profile != self._serial_profile
        )

    def _open_serial(self, profile: NetproSerialProfile) -> serial.Serial:
        """Open a serial connection using a specific transport profile."""
        try:
            _LOGGER.debug(
                "Opening serial port %s with profile %s (baud=%s dtr=%s rts=%s)",
                self.port,
                profile.name,
                profile.baudrate,
                profile.dtr,
                profile.rts,
            )
            serial_conn = serial.Serial(
                port=self.port,
                baudrate=profile.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.5,
                write_timeout=SERIAL_TIMEOUT,
                rtscts=False,
                dsrdtr=False,
            )
            serial_conn.dtr = profile.dtr
            serial_conn.rts = profile.rts
            if profile.settle_delay > 0:
                time.sleep(profile.settle_delay)
            return serial_conn
        except SerialException as err:
            raise NetproUpsUsbError(f"Cannot open serial port {self.port}: {err}") from err

    def _read_reply(self, serial_conn: serial.Serial) -> bytes:
        """Read a reply line from the UPS in a tolerant way."""
        deadline = time.monotonic() + SERIAL_TIMEOUT
        reply = bytearray()

        while time.monotonic() < deadline:
            waiting = serial_conn.in_waiting
            chunk = serial_conn.read(waiting or 1)
            if chunk:
                reply.extend(chunk)
                if b"\r" in chunk:
                    break
                continue

            time.sleep(0.05)

        return bytes(reply)

    def _query_status(self) -> NetproUpsStatus:
        """Query current UPS status."""
        self._last_diagnostics = []
        self._protocol_hint = self._query_protocol_optional()
        mode_code = self._query_mode_optional()
        _LOGGER.debug(
            "Status query starting on %s. Protocol hint=%s, mode=%s",
            self.port,
            self._protocol_hint,
            mode_code,
        )
        last_error: NetproUpsUsbError | None = None

        for command, parser in (
            ("Q6", self._parse_q6_status),
            ("Q2", self._parse_q2_status),
            ("Q1", self._parse_q1_status),
            ("QS", self._parse_qs_status),
            ("QGS", self._parse_qgs_status),
        ):
            try:
                response = self._exchange(command)
                return parser(response, mode_code)
            except NetproUpsUsbError as err:
                last_error = err
                self._remember_diagnostic(f"{command}: {err}")
                _LOGGER.debug("Status probe %s failed on %s: %s", command, self.port, err)

        raise NetproUpsUsbError(
            f"Unable to read UPS status from {self.port}. Last error: {last_error}"
        )

    def _query_protocol_optional(self) -> str | None:
        """Try to detect the protocol family used by the UPS."""
        for command in ("QPI", "M"):
            try:
                response = self._exchange(command)
            except NetproUpsUsbError:
                continue

            if command == "QPI" and response.startswith("(PI"):
                return response[1:].strip()

            candidate = response.strip("()# ")
            if candidate:
                return candidate

        return None

    def _query_mode_optional(self) -> str | None:
        """Try to query current UPS mode."""
        try:
            response = self._exchange("QMOD")
        except NetproUpsUsbError:
            return None

        if not response.startswith("(") or len(response) < 2:
            return None

        mode_code = response[1:2]
        return mode_code if mode_code else None

    def _query_info_optional(self) -> NetproUpsInfo | None:
        """Try to query static UPS information."""
        try:
            response = self._exchange("I")
        except NetproUpsUsbError:
            return None

        _LOGGER.debug("Info response from %s: %s", self.port, response)

        if not response.startswith("#"):
            return None

        payload = response[1:].strip()
        parts = payload.split()
        if len(parts) < 3:
            return None

        return NetproUpsInfo(
            manufacturer=parts[0],
            model=parts[1],
            firmware_version=" ".join(parts[2:]),
        )

    def _query_rating_optional(self) -> NetproUpsRating | None:
        """Try to query nominal UPS ratings."""
        for command in ("F", "QRI"):
            try:
                response = self._exchange(command)
            except NetproUpsUsbError:
                continue

            _LOGGER.debug("Rating response %s from %s: %s", command, self.port, response)

            if not response.startswith(("#", "(")):
                continue

            payload = response[1:].strip().split()
            if len(payload) < 4:
                continue

            try:
                return NetproUpsRating(
                    rating_voltage=float(payload[0]),
                    rating_current=float(payload[1]),
                    battery_voltage_nominal=float(payload[2]),
                    rating_frequency=float(payload[3]),
                )
            except ValueError:
                _LOGGER.debug("Failed to parse rating response for %s: %s", command, response)

        return None

    def _write_command(self, command: str) -> None:
        """Send a command without requiring a parsed response."""
        last_error: NetproUpsUsbError | None = None

        for profile in self._candidate_profiles():
            try:
                with self._open_serial(profile) as serial_conn:
                    serial_conn.reset_input_buffer()
                    serial_conn.reset_output_buffer()
                    serial_conn.write(f"{command}\r".encode("ascii"))
                    serial_conn.flush()
                    self._read_reply(serial_conn)
                self._serial_profile = profile
                return
            except NetproUpsUsbError as err:
                last_error = err
                self._remember_diagnostic(f"write {command}/{profile.name}: {err}")
                _LOGGER.debug("Command %s failed with profile %s on %s: %s", command, profile.name, self.port, err)

        raise NetproUpsUsbError(
            f"Unable to send command {command} to {self.port}. Last error: {last_error}"
        )

    def _exchange_with_profile(self, profile: NetproSerialProfile, command: str) -> str:
        """Send a command with a specific serial profile and return the reply."""
        _LOGGER.debug("Sending command %s to %s using profile %s", command, self.port, profile.name)
        with self._open_serial(profile) as serial_conn:
            serial_conn.reset_input_buffer()
            serial_conn.reset_output_buffer()
            serial_conn.write(f"{command}\r".encode("ascii"))
            serial_conn.flush()
            raw_reply = self._read_reply(serial_conn)

        if not raw_reply:
            raise NetproUpsUsbError(f"No response received for command {command}")

        reply = raw_reply.decode("ascii", errors="ignore").replace("\x00", "").strip()
        _LOGGER.debug(
            "Received reply for %s on %s with profile %s: %r",
            command,
            self.port,
            profile.name,
            reply,
        )
        if reply == command:
            raise NetproUpsUsbError(f"UPS echoed unsupported command {command}")

        return reply

    def _exchange(self, command: str) -> str:
        """Send a command and read the reply."""
        last_error: NetproUpsUsbError | None = None

        for profile in self._candidate_profiles():
            try:
                reply = self._exchange_with_profile(profile, command)
                self._serial_profile = profile
                return reply
            except NetproUpsUsbError as err:
                last_error = err
                self._remember_diagnostic(f"{command}/{profile.name}: {err}")
                _LOGGER.debug(
                    "Exchange %s failed with profile %s on %s: %s",
                    command,
                    profile.name,
                    self.port,
                    err,
                )

        raise NetproUpsUsbError(
            f"Unable to exchange command {command} with {self.port}. Last error: {last_error}"
        )

    def _parse_q1_like_status(
        self,
        response: str,
        mode_code: str | None,
        query_command: str,
    ) -> NetproUpsStatus:
        """Parse a Q1 or QS style response."""
        if not response.startswith("("):
            raise NetproUpsUsbError(f"Unexpected {query_command} response: {response}")

        parts = response[1:].split()
        if len(parts) < 8:
            raise NetproUpsUsbError(f"Incomplete {query_command} response: {response}")

        flags = parts[7]
        if len(flags) < 8:
            raise NetproUpsUsbError(f"Invalid status flags in response: {response}")

        try:
            return NetproUpsStatus(
                input_voltage=float(parts[0]),
                input_voltage_l2=None,
                input_voltage_l3=None,
                input_fault_voltage=float(parts[1]),
                output_voltage=float(parts[2]),
                output_voltage_l2=None,
                output_voltage_l3=None,
                load_percent=int(parts[3]),
                input_frequency=float(parts[4]),
                output_frequency=float(parts[4]),
                battery_voltage=float(parts[5]),
                battery_level_percent=None,
                runtime_seconds=None,
                temperature_celsius=float(parts[6]),
                utility_fail=_mode_implies_utility_fail(mode_code, flags[0] == "1"),
                battery_low=flags[1] == "1",
                bypass_active=_mode_implies_bypass(mode_code, flags[2] == "1"),
                ups_failed=_mode_implies_fault(mode_code, flags[3] == "1"),
                standby_ups=_mode_implies_standby(mode_code, flags[4] == "1"),
                test_in_progress=_mode_implies_test(mode_code, flags[5] == "1"),
                shutdown_active=_mode_implies_shutdown(mode_code, flags[6] == "1"),
                battery_test_result=None,
                beeper_on=flags[7] == "1",
                input_current_a=None,
                output_power_kw=None,
                output_apparent_power_kva=None,
                output_power_factor=None,
                battery_current_a=None,
                battery_connected=True,
                input_neutral_lost=False,
                status_bits=flags,
                mode_code=mode_code,
                query_command=query_command,
            )
        except ValueError as err:
            raise NetproUpsUsbError(
                f"Failed to parse {query_command} response: {response}"
            ) from err

    def _parse_q1_status(self, response: str, mode_code: str | None) -> NetproUpsStatus:
        """Parse a standard Q1/SNT response."""
        return self._parse_q1_like_status(response, mode_code, "Q1")

    def _parse_qs_status(self, response: str, mode_code: str | None) -> NetproUpsStatus:
        """Parse a QS response used by some Voltronic-compatible models."""
        return self._parse_q1_like_status(response, mode_code, "QS")

    def _parse_q2_status(self, response: str, mode_code: str | None) -> NetproUpsStatus:
        """Parse a Q2 response used by some extended three-phase models."""
        if not response.startswith("("):
            raise NetproUpsUsbError(f"Unexpected Q2 response: {response}")

        parts = response[1:].split()
        if len(parts) < 16:
            raise NetproUpsUsbError(f"Incomplete Q2 response: {response}")

        flags = parts[13]
        if len(flags) < 8:
            raise NetproUpsUsbError(f"Invalid Q2 status flags in response: {response}")

        try:
            runtime_minutes = float(parts[14])
            runtime_seconds = int(runtime_minutes * 60)
        except ValueError:
            runtime_seconds = None

        try:
            return NetproUpsStatus(
                input_voltage=float(parts[0]),
                input_voltage_l2=float(parts[1]),
                input_voltage_l3=float(parts[2]),
                input_fault_voltage=float(parts[3]),
                output_voltage=float(parts[4]),
                output_voltage_l2=float(parts[5]),
                output_voltage_l3=float(parts[6]),
                load_percent=max(int(parts[7]), int(parts[8]), int(parts[9])),
                input_frequency=float(parts[10]),
                output_frequency=float(parts[10]),
                battery_voltage=float(parts[11]),
                battery_level_percent=int(parts[15]) if parts[15].isdigit() else None,
                runtime_seconds=runtime_seconds,
                temperature_celsius=float(parts[12]),
                utility_fail=_mode_implies_utility_fail(mode_code, flags[0] == "1"),
                battery_low=flags[1] == "1",
                bypass_active=_mode_implies_bypass(mode_code, flags[2] == "1"),
                ups_failed=_mode_implies_fault(mode_code, flags[3] == "1"),
                standby_ups=_mode_implies_standby(mode_code, flags[4] == "1"),
                test_in_progress=_mode_implies_test(mode_code, flags[5] == "1"),
                shutdown_active=_mode_implies_shutdown(mode_code, flags[6] == "1"),
                battery_test_result=None,
                beeper_on=flags[7] == "1",
                input_current_a=None,
                output_power_kw=None,
                output_apparent_power_kva=None,
                output_power_factor=None,
                battery_current_a=None,
                battery_connected=True,
                input_neutral_lost=False,
                status_bits=flags,
                mode_code=mode_code,
                query_command="Q2",
            )
        except ValueError as err:
            raise NetproUpsUsbError(f"Failed to parse Q2 response: {response}") from err

    def _parse_q6_status(self, response: str, mode_code: str | None) -> NetproUpsStatus:
        """Parse a Q6 response used by three-phase models."""
        if not response.startswith("("):
            raise NetproUpsUsbError(f"Unexpected Q6 response: {response}")

        parts = response[1:].split()
        if len(parts) < 16:
            raise NetproUpsUsbError(f"Incomplete Q6 response: {response}")

        try:
            load_percent = int(parts[8])
            runtime_seconds = int(parts[14]) if parts[14].isdigit() else None
            battery_level = int(parts[15]) if parts[15].isdigit() else None
            status_bits = " ".join(parts[17:]) if len(parts) > 17 else ""

            return NetproUpsStatus(
                input_voltage=float(parts[0]),
                input_voltage_l2=float(parts[1]),
                input_voltage_l3=float(parts[2]),
                input_fault_voltage=float(parts[0]),
                output_voltage=float(parts[4]),
                output_voltage_l2=float(parts[5]),
                output_voltage_l3=float(parts[6]),
                load_percent=load_percent,
                input_frequency=float(parts[3]),
                output_frequency=float(parts[7]),
                battery_voltage=float(parts[11]),
                battery_level_percent=battery_level,
                runtime_seconds=runtime_seconds,
                temperature_celsius=float(parts[13]),
                utility_fail=_mode_implies_utility_fail(mode_code, False),
                battery_low=False,
                bypass_active=_mode_implies_bypass(mode_code, False),
                ups_failed=_mode_implies_fault(mode_code, False),
                standby_ups=_mode_implies_standby(mode_code, False),
                test_in_progress=_mode_implies_test(mode_code, False),
                shutdown_active=_mode_implies_shutdown(mode_code, False),
                battery_test_result=None,
                beeper_on=False,
                input_current_a=None,
                output_power_kw=None,
                output_apparent_power_kva=None,
                output_power_factor=None,
                battery_current_a=None,
                battery_connected=True,
                input_neutral_lost=False,
                status_bits=status_bits,
                mode_code=mode_code,
                query_command="Q6",
            )
        except ValueError as err:
            raise NetproUpsUsbError(f"Failed to parse Q6 response: {response}") from err

    def _parse_qgs_status(self, response: str, mode_code: str | None) -> NetproUpsStatus:
        """Parse a QGS response used by Voltronic Pxx protocol devices."""
        if not response.startswith("("):
            raise NetproUpsUsbError(f"Unexpected QGS response: {response}")

        parts = response[1:].split()
        if len(parts) < 12:
            raise NetproUpsUsbError(f"Incomplete QGS response: {response}")

        flags = parts[11]
        if len(flags) < 10:
            raise NetproUpsUsbError(f"Invalid QGS flags in response: {response}")

        status_bits = flags[2:10]
        ups_type_bits = flags[:2]

        try:
            battery_level = None
            if parts[9].replace(".", "", 1).isdigit():
                battery_level = int(float(parts[9]))

            return NetproUpsStatus(
                input_voltage=float(parts[0]),
                input_voltage_l2=None,
                input_voltage_l3=None,
                input_fault_voltage=float(parts[0]),
                output_voltage=float(parts[2]),
                output_voltage_l2=None,
                output_voltage_l3=None,
                load_percent=int(parts[5]),
                input_frequency=float(parts[1]),
                output_frequency=float(parts[3]),
                battery_voltage=float(parts[8]),
                battery_level_percent=battery_level,
                runtime_seconds=None,
                temperature_celsius=float(parts[10]),
                utility_fail=_mode_implies_utility_fail(mode_code, status_bits[0] == "1"),
                battery_low=status_bits[1] == "1",
                bypass_active=_mode_implies_bypass(mode_code, status_bits[2] == "1"),
                ups_failed=_mode_implies_fault(mode_code, status_bits[3] == "1"),
                standby_ups=_mode_implies_standby(mode_code, ups_type_bits == "00"),
                test_in_progress=_mode_implies_test(mode_code, status_bits[5] == "1"),
                shutdown_active=_mode_implies_shutdown(mode_code, status_bits[6] == "1"),
                battery_test_result=None,
                beeper_on=status_bits[7] == "1",
                input_current_a=None,
                output_power_kw=None,
                output_apparent_power_kva=None,
                output_power_factor=None,
                battery_current_a=None,
                battery_connected=True,
                input_neutral_lost=False,
                status_bits=status_bits,
                mode_code=mode_code,
                query_command="QGS",
            )
        except ValueError as err:
            raise NetproUpsUsbError(f"Failed to parse QGS response: {response}") from err


def _mode_code_to_operating_mode(mode_code: str) -> str:
    """Map QMOD mode code to a readable mode."""
    return {
        "P": "power_on",
        "S": "standby",
        "Y": "bypass",
        "L": "online",
        "B": "on_battery",
        "T": "battery_test",
        "F": "fault",
        "E": "eco",
        "C": "converter",
        "D": "shutdown",
    }.get(mode_code, "unknown")


def _mode_implies_utility_fail(mode_code: str | None, default: bool) -> bool:
    """Infer utility fail from QMOD when available."""
    if mode_code == "B":
        return True
    return default


def _mode_implies_bypass(mode_code: str | None, default: bool) -> bool:
    """Infer bypass from QMOD when available."""
    if mode_code in {"Y", "E"}:
        return True
    return default


def _mode_implies_fault(mode_code: str | None, default: bool) -> bool:
    """Infer fault from QMOD when available."""
    if mode_code == "F":
        return True
    return default


def _mode_implies_standby(mode_code: str | None, default: bool) -> bool:
    """Infer standby from QMOD when available."""
    if mode_code == "S":
        return True
    return default


def _mode_implies_test(mode_code: str | None, default: bool) -> bool:
    """Infer battery test mode from QMOD when available."""
    if mode_code == "T":
        return True
    return default


def _mode_implies_shutdown(mode_code: str | None, default: bool) -> bool:
    """Infer shutdown from QMOD when available."""
    if mode_code == "D":
        return True
    return default