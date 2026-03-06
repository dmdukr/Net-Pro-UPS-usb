# Changelog

## 1.0.0

First stable release.

- Switched to **Modbus ASCII** protocol (9600 8N1) — the native protocol of Net PRO HT31/HT33 TX series
- Block reads: 78 FC03 registers + 35 FC04 registers in 2 requests per poll cycle
- Auto-reconnect: waits up to 15 s for USB port to reappear after disconnect, then retries once
- Tolerance for stale data: coordinator keeps last known values for up to 3 consecutive failures before reporting Unavailable
- Removed untested SNT and Modbus RTU protocol options from config flow — only Modbus ASCII is exposed
- Filtered built-in UART ports (`/dev/ttyS*`) from the serial port dropdown
- Fixed temperature: reads battery temperature register (reg 54) instead of undefined reg 49
- Fixed FC06 write commands (beeper toggle, battery test buttons) in ASCII mode
- Added `battery_test_result` sensor: No Test / Testing / Success / Fail
- Enabled `battery_level_percent` and `runtime_seconds` sensors by default
- Detailed bilingual README (English + Ukrainian)
