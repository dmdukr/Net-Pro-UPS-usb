"""Modbus ASCII frame utilities for NetPRO UPS."""

from __future__ import annotations


class ModbusAsciiError(Exception):
    """Modbus ASCII communication error."""


def _lrc(data: bytes) -> int:
    """Calculate Longitudinal Redundancy Check."""
    return (-sum(data)) & 0xFF


def build_ascii_request(slave: int, fc: int, reg: int, count: int = 1) -> bytes:
    """Build a Modbus ASCII read request frame (FC03/FC04).

    Format: :{slave}{fc}{reg_hi}{reg_lo}{count_hi}{count_lo}{LRC}\\r\\n
    """
    payload = bytes([slave, fc, reg >> 8, reg & 0xFF, count >> 8, count & 0xFF])
    return f":{payload.hex().upper()}{_lrc(payload):02X}\r\n".encode()


def build_ascii_write_single(slave: int, reg: int, value: int) -> bytes:
    """Build a Modbus ASCII FC06 write-single-register frame."""
    payload = bytes([slave, 0x06, reg >> 8, reg & 0xFF, value >> 8, value & 0xFF])
    return f":{payload.hex().upper()}{_lrc(payload):02X}\r\n".encode()


def parse_ascii_response(resp: bytes, expected_count: int) -> list[int]:
    """Parse a Modbus ASCII block-read response into register values.

    Response format: :{slave}{fc}{byte_count}{data...}{LRC}\\r\\n
    Each register is 4 hex chars (2 bytes big-endian).
    """
    if not resp or not resp.startswith(b":"):
        raise ModbusAsciiError(f"Invalid Modbus ASCII frame: {resp!r}")

    inner = resp[1:].rstrip(b"\r\n")
    try:
        byte_count = int(inner[4:6], 16)
        data_hex = inner[6 : 6 + byte_count * 2]
        result = [int(data_hex[i : i + 4], 16) for i in range(0, len(data_hex), 4)]
    except (ValueError, IndexError) as exc:
        raise ModbusAsciiError(f"Parse error in ASCII response: {exc}") from exc

    if len(result) != expected_count:
        raise ModbusAsciiError(
            f"Expected {expected_count} registers, got {len(result)}"
        )
    return result
