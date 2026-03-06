"""Sensor platform for NetPRO UPS USB."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NetproUpsUsbCoordinator
from .hub import NetproUpsSnapshot


@dataclass(frozen=True, kw_only=True)
class NetproUpsUsbSensorDescription(SensorEntityDescription):
    """Describe a NetPRO UPS USB sensor."""

    value_fn: Callable[[NetproUpsSnapshot], str | int | float | None]


SENSOR_DESCRIPTIONS: tuple[NetproUpsUsbSensorDescription, ...] = (
    # --- Voltages ---
    NetproUpsUsbSensorDescription(
        key="input_voltage",
        translation_key="input_voltage",
        name="Input Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.status.input_voltage,
    ),
    NetproUpsUsbSensorDescription(
        key="output_voltage",
        translation_key="output_voltage",
        name="Output Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.status.output_voltage,
    ),
    # --- Currents ---
    NetproUpsUsbSensorDescription(
        key="input_current",
        translation_key="input_current",
        name="Input Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.status.input_current_a,
    ),
    # --- Power ---
    NetproUpsUsbSensorDescription(
        key="output_power_kw",
        translation_key="output_power_kw",
        name="Output Power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.status.output_power_kw,
    ),
    NetproUpsUsbSensorDescription(
        key="output_apparent_power_kva",
        translation_key="output_apparent_power_kva",
        name="Output Apparent Power",
        native_unit_of_measurement="kVA",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.status.output_apparent_power_kva,
    ),
    NetproUpsUsbSensorDescription(
        key="output_power_factor",
        translation_key="output_power_factor",
        name="Output Power Factor",
        native_unit_of_measurement=None,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.status.output_power_factor,
    ),
    # --- Load ---
    NetproUpsUsbSensorDescription(
        key="load_percent",
        translation_key="load_percent",
        name="Load",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.status.load_percent,
    ),
    # --- Frequency ---
    NetproUpsUsbSensorDescription(
        key="input_frequency",
        translation_key="input_frequency",
        name="Input Frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.status.input_frequency,
    ),
    NetproUpsUsbSensorDescription(
        key="output_frequency",
        translation_key="output_frequency",
        name="Output Frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.status.output_frequency,
    ),
    # --- Battery ---
    NetproUpsUsbSensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        name="Battery Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.status.battery_voltage,
    ),
    NetproUpsUsbSensorDescription(
        key="battery_level_percent",
        translation_key="battery_level_percent",
        name="Battery Level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.status.battery_level_percent,
    ),
    NetproUpsUsbSensorDescription(
        key="battery_current",
        translation_key="battery_current",
        name="Battery Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.status.battery_current_a,
    ),
    NetproUpsUsbSensorDescription(
        key="runtime_seconds",
        translation_key="runtime_seconds",
        name="Runtime",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda data: data.status.runtime_seconds if data.status.runtime_seconds is not None else "∞",
    ),
    # --- Temperature ---
    NetproUpsUsbSensorDescription(
        key="temperature",
        translation_key="temperature",
        name="Battery Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.status.temperature_celsius,
    ),
    # --- Status ---
    NetproUpsUsbSensorDescription(
        key="operating_mode",
        translation_key="operating_mode",
        name="Operating Mode",
        value_fn=lambda data: data.status.operating_mode,
    ),
    NetproUpsUsbSensorDescription(
        key="battery_test_result",
        translation_key="battery_test_result",
        name="Battery Test Result",
        value_fn=lambda data: {
            0: "No Test", 1: "Success", 2: "Fail", 3: "Testing",
        }.get(data.status.battery_test_result) if data.status.battery_test_result is not None else None,
    ),
    # --- Debug (disabled by default) ---
    NetproUpsUsbSensorDescription(
        key="status_bits",
        translation_key="status_bits",
        name="Status Bits",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.status.status_bits,
    ),
    NetproUpsUsbSensorDescription(
        key="query_command",
        translation_key="query_command",
        name="Status Query Command",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.status.query_command,
    ),
    NetproUpsUsbSensorDescription(
        key="mode_code",
        translation_key="mode_code",
        name="Mode Code",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.status.mode_code,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up NetPRO UPS USB sensors."""
    coordinator: NetproUpsUsbCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        NetproUpsUsbSensor(coordinator, description) for description in SENSOR_DESCRIPTIONS
    )


class NetproUpsUsbSensor(CoordinatorEntity[NetproUpsUsbCoordinator], SensorEntity):
    """Representation of a NetPRO UPS USB sensor."""

    entity_description: NetproUpsUsbSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NetproUpsUsbCoordinator,
        description: NetproUpsUsbSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.hub.device_identifier()}_{description.key}"

    @property
    def native_value(self) -> str | int | float | None:
        """Return the current value."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def device_info(self) -> dict:
        """Return device information."""
        return self.coordinator.hub.device_info_payload()
