"""Binary sensors for NetPRO UPS USB."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NetproUpsUsbCoordinator
from .hub import NetproUpsSnapshot


@dataclass(frozen=True, kw_only=True)
class NetproUpsUsbBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a NetPRO UPS USB binary sensor."""

    value_fn: Callable[[NetproUpsSnapshot], bool]


BINARY_SENSOR_DESCRIPTIONS: tuple[NetproUpsUsbBinarySensorDescription, ...] = (
    NetproUpsUsbBinarySensorDescription(
        key="utility_fail",
        translation_key="utility_fail",
        name="Utility Fail",
        value_fn=lambda data: data.status.utility_fail,
    ),
    NetproUpsUsbBinarySensorDescription(
        key="battery_low",
        translation_key="battery_low",
        name="Battery Low",
        value_fn=lambda data: data.status.battery_low,
    ),
    NetproUpsUsbBinarySensorDescription(
        key="bypass_active",
        translation_key="bypass_active",
        name="Bypass Active",
        value_fn=lambda data: data.status.bypass_active,
    ),
    NetproUpsUsbBinarySensorDescription(
        key="ups_failed",
        translation_key="ups_failed",
        name="UPS Failed",
        value_fn=lambda data: data.status.ups_failed,
    ),
    NetproUpsUsbBinarySensorDescription(
        key="test_in_progress",
        translation_key="test_in_progress",
        name="Test In Progress",
        value_fn=lambda data: data.status.test_in_progress,
    ),
    NetproUpsUsbBinarySensorDescription(
        key="shutdown_active",
        translation_key="shutdown_active",
        name="Shutdown Active",

        value_fn=lambda data: data.status.shutdown_active,
    ),
    NetproUpsUsbBinarySensorDescription(
        key="beeper_on",
        translation_key="beeper_on",
        name="Beeper On",

        value_fn=lambda data: data.status.beeper_on,
    ),
    NetproUpsUsbBinarySensorDescription(
        key="battery_connected",
        translation_key="battery_connected",
        name="Battery Connected",
        value_fn=lambda data: data.status.battery_connected,
    ),
    NetproUpsUsbBinarySensorDescription(
        key="input_neutral_lost",
        translation_key="input_neutral_lost",
        name="Input Neutral Lost",

        value_fn=lambda data: data.status.input_neutral_lost,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up NetPRO UPS USB binary sensors."""
    coordinator: NetproUpsUsbCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        NetproUpsUsbBinarySensor(coordinator, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
    )


class NetproUpsUsbBinarySensor(
    CoordinatorEntity[NetproUpsUsbCoordinator], BinarySensorEntity
):
    """Representation of a NetPRO UPS USB binary sensor."""

    entity_description: NetproUpsUsbBinarySensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NetproUpsUsbCoordinator,
        description: NetproUpsUsbBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.hub.device_identifier()}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the current binary state."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def device_info(self) -> dict:
        """Return device information."""
        return self.coordinator.hub.device_info_payload()