# NetPRO UPS USB — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![GitHub release](https://img.shields.io/github/v/release/dmdukr/Net-Pro-UPS-usb)](https://github.com/dmdukr/Net-Pro-UPS-usb/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![HA min version](https://img.shields.io/badge/Home%20Assistant-%3E%3D2025.1.0-blue)](https://www.home-assistant.io)

---

> **[English](#english) | [Українська](#ukrainian)**

---

## English

Custom Home Assistant integration for **Net PRO UPS** devices connected via USB serial (CH340 USB-UART).
Communicates using **Modbus ASCII** protocol at 9600 8N1 — the native protocol used by Net PRO HT31/HT33 TX series.

### Tested hardware

| UPS model | Series | Firmware | USB adapter | HA version | Status |
|-----------|--------|----------|-------------|------------|--------|
| Net PRO UPS 31-10KL | HT31 TX | — | CH340 (USB Serial) | 2025.3.x | ✅ Working |

> Other models in the HT31 / HT33 TX series are expected to work — please open an issue with your results.

---

### Features

- **Modbus ASCII** block read: 78 FC03 registers + 35 FC04 registers in 2 requests per poll cycle
- **Auto-reconnect**: when USB is disconnected, the integration waits up to 15 s for the port to reappear, then retries automatically
- **Tolerance for stale data**: up to 3 consecutive poll failures return last known values before reporting Unavailable
- Automatic detection of stable `/dev/serial/by-id/...` paths — preferred over volatile `/dev/ttyUSBx`
- Dedicated rotating log file at `/config/netpro_ups_usb.log` for serial diagnostics
- Full HACS-compatible packaging

---

### Installation

#### Via HACS (recommended)

1. Open **HACS** in Home Assistant
2. Click **Integrations** → three-dot menu → **Custom repositories**
3. Add:
   - Repository: `https://github.com/dmdukr/Net-Pro-UPS-usb`
   - Category: **Integration**
4. Find **NetPRO UPS USB** in the list and click **Download**
5. Restart Home Assistant
6. Go to **Settings → Devices & Services → Add Integration** → search for **NetPRO UPS USB**

#### Manual

1. Copy `custom_components/netpro_ups_usb/` to your HA `config/custom_components/` directory
2. Restart Home Assistant
3. Add the integration as described above

---

### Configuration

The setup wizard asks for three fields:

| Field | Description | Default |
|-------|-------------|---------|
| **Name** | Device name shown in Home Assistant | `NetPRO UPS` |
| **Serial port** | USB-serial port. Detected ports shown in dropdown; use `/dev/serial/by-id/...` for stability | `/dev/ttyUSB0` |
| **Poll interval** | How often to query the UPS in seconds | `30` |

> **Skip connection check** — enable this checkbox only if the initial probe fails and you want to create the integration anyway (useful for troubleshooting). The integration will start in Unavailable state and attempt normal polling on schedule.

**Proxmox USB passthrough note:** If you run Home Assistant OS as a VM on Proxmox, pass the USB device through at the VM level. The port will appear as `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0` (CH340 chip) or similar.

**NUT conflict note:** If you have NUT (`nut-server`) configured on the same host for the same port, stop it before adding this integration — NUT holds the serial port open.

---

### Entities

The integration creates a single device with the following entities:

#### Sensors (measurement)

| Entity | Unit | Default | Description |
|--------|------|---------|-------------|
| `sensor.input_voltage` | V | Enabled | AC mains input voltage (L1) |
| `sensor.output_voltage` | V | Enabled | AC output voltage (L1) |
| `sensor.load_percent` | % | Enabled | Load percentage |
| `sensor.battery_voltage` | V | Enabled | Battery pack voltage |
| `sensor.battery_level_percent` | % | Enabled | Battery charge level |
| `sensor.runtime_seconds` | s | Enabled | Estimated remaining runtime on battery |
| `sensor.input_frequency` | Hz | Enabled | Mains input frequency |
| `sensor.temperature` | °C | Enabled | Battery/internal temperature |
| `sensor.operating_mode` | — | Enabled | Current UPS operating mode string |
| `sensor.battery_test_result` | — | Enabled | Last battery test result (No Test / Testing / Success / Fail) |
| `sensor.input_fault_voltage` | V | Disabled | Input fault voltage (advanced) |
| `sensor.input_voltage_l2` | V | Disabled | Input voltage L2 (3-phase) |
| `sensor.input_voltage_l3` | V | Disabled | Input voltage L3 (3-phase) |
| `sensor.output_voltage_l2` | V | Disabled | Output voltage L2 (3-phase) |
| `sensor.output_voltage_l3` | V | Disabled | Output voltage L3 (3-phase) |
| `sensor.output_frequency` | Hz | Disabled | Output frequency |
| `sensor.status_bits` | — | Disabled | Raw status bitmask |
| `sensor.mode_code` | — | Disabled | Raw mode code byte |
| `sensor.query_command` | — | Disabled | Last Modbus command used |

#### Binary sensors

| Entity | Default | Description |
|--------|---------|-------------|
| `binary_sensor.utility_fail` | Enabled | Mains power failure (UPS on battery) |
| `binary_sensor.battery_low` | Enabled | Battery low warning |
| `binary_sensor.bypass_active` | Enabled | Bypass mode active |
| `binary_sensor.ups_failed` | Enabled | UPS internal fault |
| `binary_sensor.test_in_progress` | Enabled | Battery test running |
| `binary_sensor.shutdown_active` | Disabled | Shutdown sequence active |
| `binary_sensor.beeper_on` | Disabled | Audible beeper state |

#### Buttons

| Entity | Default | Description |
|--------|---------|-------------|
| `button.beeper_toggle` | Enabled | Toggle audible alarm on/off |
| `button.battery_test_quick` | Enabled | Start a quick 10-second battery test |
| `button.battery_test_deep` | Disabled | Start a deep battery test (until low threshold) |
| `button.battery_test_stop` | Disabled | Cancel an in-progress battery test |

---

### Automation examples

#### Notify when mains power fails

```yaml
automation:
  - alias: "UPS: Mains power failure"
    trigger:
      - platform: state
        entity_id: binary_sensor.netpro_ups_utility_fail
        to: "on"
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "Power failure"
          message: >
            UPS switched to battery.
            Remaining runtime: {{ states('sensor.netpro_ups_runtime_seconds') | int // 60 }} min,
            battery {{ states('sensor.netpro_ups_battery_level_percent') }}%.
```

#### Notify when mains power is restored

```yaml
automation:
  - alias: "UPS: Mains power restored"
    trigger:
      - platform: state
        entity_id: binary_sensor.netpro_ups_utility_fail
        to: "off"
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "Power restored"
          message: "Mains power is back. UPS back online."
```

#### Alert on low battery

```yaml
automation:
  - alias: "UPS: Battery low"
    trigger:
      - platform: state
        entity_id: binary_sensor.netpro_ups_battery_low
        to: "on"
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "UPS Battery Low"
          message: >
            Battery critically low!
            Runtime: {{ states('sensor.netpro_ups_runtime_seconds') | int // 60 }} min.
            Consider graceful shutdown.
```

#### Scheduled weekly battery test

```yaml
automation:
  - alias: "UPS: Weekly battery test"
    trigger:
      - platform: time
        at: "03:00:00"
    condition:
      - condition: time
        weekday: [sun]
    action:
      - service: button.press
        target:
          entity_id: button.netpro_ups_battery_test_quick
```

---

### Repository structure

```
.
├── LICENSE
├── README.md
├── CHANGELOG.md
├── hacs.json
└── custom_components/
    └── netpro_ups_usb/
        ├── __init__.py
        ├── binary_sensor.py
        ├── brand/
        │   ├── icon.png
        │   ├── icon@2x.png
        │   ├── logo.png
        │   └── logo@2x.png
        ├── button.py
        ├── config_flow.py
        ├── const.py
        ├── coordinator.py
        ├── hub.py
        ├── manifest.json
        ├── modbus_ascii.py
        ├── modbus_rtu.py
        ├── sensor.py
        ├── strings.json
        └── translations/
            └── ru.json
```

---

### Troubleshooting

- **All entities show Unavailable**: Check that no other process (NUT, another integration) holds the serial port. On the **Proxmox host** (not inside HAOS), run `lsof /dev/ttyUSB0` or `systemctl status nut-server`.
- **USB disconnects after a few minutes**: Some UPS models drop the USB bus when polled too aggressively. Increase the poll interval to 30 s or more in the integration options.
- **Port not detected in dropdown**: Only USB serial ports are shown. Built-in UART ports (`/dev/ttyS0–3`) are hidden automatically. To find your device path go to **Settings → System → Hardware → All Hardware**, locate your USB-serial adapter, and copy the path (e.g. `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`) into the port field manually.
- **Need to change the port after installation**: Open the integration in **Settings → Devices & Services**, click **Configure** to open the options dialog, and select a new port. The integration will reload automatically.
- **Detailed logs**: In the integration options (**Configure**), enable **Debug log file**. Logs will be written to `/config/netpro_ups_usb.log` at DEBUG level.

---

### Bug reports

Please include the following when opening an issue:

1. Enable **Debug log file** in the integration options (**Configure**)
2. Reproduce the issue
3. Attach the contents of `/config/netpro_ups_usb.log` — it contains UPS model, serial profile, firmware version, all register values and error details
4. Screenshot of the integration's device page
5. Home Assistant version and integration version (visible in the log header)

---

---

## Ukrainian

<a name="ukrainian"></a>

Інтеграція для Home Assistant для підключення **Net PRO UPS** через USB-serial (CH340 USB-UART).
Використовує протокол **Modbus ASCII** на 9600 8N1 — нативний протокол серії Net PRO HT31/HT33 TX.

### Перевірене обладнання

| Модель ДБЖ | Серія | Прошивка | USB-адаптер | Версія HA | Статус |
|------------|-------|----------|-------------|-----------|--------|
| Net PRO UPS 31-10KL | HT31 TX | — | CH340 (USB Serial) | 2025.3.x | ✅ Працює |

> Інші моделі серії HT31 / HT33 TX мають працювати аналогічно — будь ласка, повідомте про результати у вигляді issue.

---

### Можливості

- **Modbus ASCII** блочне читання: 78 регістрів FC03 + 35 регістрів FC04 за 2 запити на цикл
- **Авто-перепідключення**: при відключенні USB інтеграція чекає до 15 с на повернення порту і автоматично повторює підключення
- **Толерантність до застарілих даних**: до 3 послідовних збоїв повертають останні відомі значення до переходу в стан Недоступно
- Автоматичне визначення стабільних шляхів `/dev/serial/by-id/...`
- Окремий лог-файл `/config/netpro_ups_usb.log` для діагностики serial-обміну
- Повна підтримка HACS

---

### Встановлення

#### Через HACS (рекомендовано)

1. Відкрийте **HACS** у Home Assistant
2. **Integrations** → три крапки → **Custom repositories**
3. Додайте:
   - Repository: `https://github.com/dmdukr/Net-Pro-UPS-usb`
   - Category: **Integration**
4. Знайдіть **NetPRO UPS USB** у списку та натисніть **Download**
5. Перезапустіть Home Assistant
6. **Налаштування → Пристрої та служби → Додати інтеграцію** → знайдіть **NetPRO UPS USB**

#### Вручну

1. Скопіюйте папку `custom_components/netpro_ups_usb/` до `config/custom_components/`
2. Перезапустіть Home Assistant
3. Додайте інтеграцію як описано вище

---

### Налаштування

Майстер налаштування запитує три поля:

| Поле | Опис | За замовчуванням |
|------|------|-----------------|
| **Назва** | Назва пристрою у Home Assistant | `NetPRO UPS` |
| **Serial port** | USB-serial порт. Виявлені порти показані у випадаючому списку; рекомендується `/dev/serial/by-id/...` | `/dev/ttyUSB0` |
| **Poll interval** | Інтервал опитування ДБЖ у секундах | `30` |

> **Skip connection check** — увімкніть, якщо початкова перевірка підключення не проходить і ви хочете все одно створити інтеграцію. Корисно для налагодження.

**Примітка для Proxmox:** якщо Home Assistant OS запущено як VM на Proxmox, передайте USB-пристрій через налаштування VM. Порт буде виглядати як `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`.

**Примітка щодо NUT:** якщо на тому ж хості налаштований NUT (`nut-server`) для того ж порту — зупиніть його перед додаванням інтеграції.

---

### Сутності

Інтеграція створює один пристрій з такими сутностями:

#### Сенсори (вимірювання)

| Сутність | Одиниця | За замовч. | Опис |
|----------|---------|------------|------|
| `sensor.input_voltage` | В | Увімкнено | Вхідна напруга мережі (L1) |
| `sensor.output_voltage` | В | Увімкнено | Вихідна напруга (L1) |
| `sensor.load_percent` | % | Увімкнено | Завантаженість |
| `sensor.battery_voltage` | В | Увімкнено | Напруга акумулятора |
| `sensor.battery_level_percent` | % | Увімкнено | Рівень заряду акумулятора |
| `sensor.runtime_seconds` | с | Увімкнено | Залишковий час роботи від акумулятора |
| `sensor.input_frequency` | Гц | Увімкнено | Частота вхідної мережі |
| `sensor.temperature` | °C | Увімкнено | Температура акумулятора |
| `sensor.operating_mode` | — | Увімкнено | Поточний режим роботи ДБЖ |
| `sensor.battery_test_result` | — | Увімкнено | Результат тесту акумулятора |
| `sensor.input_fault_voltage` | В | Вимкнено | Напруга при аварії (розширені) |
| `sensor.input_voltage_l2` | В | Вимкнено | Вхідна напруга L2 (3-фаза) |
| `sensor.input_voltage_l3` | В | Вимкнено | Вхідна напруга L3 (3-фаза) |
| `sensor.output_voltage_l2` | В | Вимкнено | Вихідна напруга L2 (3-фаза) |
| `sensor.output_voltage_l3` | В | Вимкнено | Вихідна напруга L3 (3-фаза) |
| `sensor.output_frequency` | Гц | Вимкнено | Вихідна частота |
| `sensor.status_bits` | — | Вимкнено | Бітова маска статусу (raw) |
| `sensor.mode_code` | — | Вимкнено | Байт режиму (raw) |
| `sensor.query_command` | — | Вимкнено | Остання команда Modbus |

#### Бінарні сенсори

| Сутність | За замовч. | Опис |
|----------|------------|------|
| `binary_sensor.utility_fail` | Увімкнено | Відключення мережі (ДБЖ на акумуляторі) |
| `binary_sensor.battery_low` | Увімкнено | Низький заряд акумулятора |
| `binary_sensor.bypass_active` | Увімкнено | Режим байпасу активний |
| `binary_sensor.ups_failed` | Увімкнено | Внутрішня несправність ДБЖ |
| `binary_sensor.test_in_progress` | Увімкнено | Тест акумулятора виконується |
| `binary_sensor.shutdown_active` | Вимкнено | Послідовність вимкнення активна |
| `binary_sensor.beeper_on` | Вимкнено | Стан звукового сигналу |

#### Кнопки

| Сутність | За замовч. | Опис |
|----------|------------|------|
| `button.beeper_toggle` | Увімкнено | Увімк./вимкн. звуковий сигнал |
| `button.battery_test_quick` | Увімкнено | Запустити швидкий тест акумулятора (10 с) |
| `button.battery_test_deep` | Вимкнено | Глибокий тест акумулятора (до порогу розряду) |
| `button.battery_test_stop` | Вимкнено | Зупинити тест акумулятора |

---

### Приклади автоматизацій

#### Сповіщення при відключенні мережі

```yaml
automation:
  - alias: "ДБЖ: Відключення мережі"
    trigger:
      - platform: state
        entity_id: binary_sensor.netpro_ups_utility_fail
        to: "on"
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "Відключення світла"
          message: >
            ДБЖ перейшов на акумулятор.
            Залишок: {{ states('sensor.netpro_ups_runtime_seconds') | int // 60 }} хв,
            заряд {{ states('sensor.netpro_ups_battery_level_percent') }}%.
```

#### Сповіщення при відновленні мережі

```yaml
automation:
  - alias: "ДБЖ: Відновлення мережі"
    trigger:
      - platform: state
        entity_id: binary_sensor.netpro_ups_utility_fail
        to: "off"
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "Мережа відновлена"
          message: "Електроживлення відновлено. ДБЖ знову в мережі."
```

#### Попередження при низькому заряді

```yaml
automation:
  - alias: "ДБЖ: Низький заряд"
    trigger:
      - platform: state
        entity_id: binary_sensor.netpro_ups_battery_low
        to: "on"
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "ДБЖ: Низький заряд акумулятора"
          message: >
            Критично низький заряд!
            Залишок: {{ states('sensor.netpro_ups_runtime_seconds') | int // 60 }} хв.
            Рекомендується плавне вимкнення.
```

#### Щотижневий тест акумулятора

```yaml
automation:
  - alias: "ДБЖ: Щотижневий тест"
    trigger:
      - platform: time
        at: "03:00:00"
    condition:
      - condition: time
        weekday: [sun]
    action:
      - service: button.press
        target:
          entity_id: button.netpro_ups_battery_test_quick
```

---

### Усунення несправностей

- **Всі сутності показують Недоступно**: перевірте, що жоден інший процес (NUT, інша інтеграція) не утримує serial-порт. На **хості Proxmox** (не всередині HAOS) виконайте `lsof /dev/ttyUSB0` або `systemctl status nut-server`.
- **USB відключається через кілька хвилин**: деякі моделі ДБЖ скидають USB-шину при занадто частому опитуванні. Збільшіть інтервал опитування до 30 с і більше в налаштуваннях інтеграції.
- **Порт не виявляється у випадаючому списку**: показуються тільки USB serial порти. Вбудовані UART (`/dev/ttyS0–3`) приховані автоматично. Щоб знайти шлях до пристрою перейдіть до **Налаштування → Система → Апаратне забезпечення → Всі пристрої**, знайдіть USB-serial адаптер і скопіюйте шлях (наприклад `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`) у поле порту вручну.
- **Потрібно змінити порт після встановлення**: відкрийте інтеграцію в **Налаштування → Пристрої та служби**, натисніть **Налаштувати** і оберіть новий порт. Інтеграція перезавантажиться автоматично.
- **Детальні логи**: у налаштуваннях інтеграції (**Налаштувати**) увімкніть **Файл debug-логу**. Логи записуватимуться до `/config/netpro_ups_usb.log` на рівні DEBUG.

---

### Повідомлення про помилки

При створенні issue:

1. Увімкніть **Файл debug-логу** у налаштуваннях інтеграції (**Налаштувати**)
2. Відтворіть проблему
3. Додайте вміст `/config/netpro_ups_usb.log` — він містить модель ДБЖ, серійний профіль, версію прошивки, всі значення регістрів і деталі помилок
4. Скріншот сторінки пристрою інтеграції
5. Версію Home Assistant та інтеграції (видно в заголовку логу)
