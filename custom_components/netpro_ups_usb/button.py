"""Button platform for NetPRO UPS USB."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NetproUpsUsbCoordinator


@dataclass(frozen=True, kw_only=True)
class NetproUpsUsbButtonDescription(ButtonEntityDescription):
    """Describe a NetPRO UPS USB button."""

    command: str


BUTTON_DESCRIPTIONS: tuple[NetproUpsUsbButtonDescription, ...] = (
    NetproUpsUsbButtonDescription(
        key="beeper_toggle",
        translation_key="beeper_toggle",
        name="Toggle Beeper",
        command="Q",
    ),
    NetproUpsUsbButtonDescription(
        key="battery_test_quick",
        translation_key="battery_test_quick",
        name="Battery Test Quick",
        command="T",
    ),
    NetproUpsUsbButtonDescription(
        key="battery_test_deep",
        translation_key="battery_test_deep",
        name="Battery Test Deep",
        entity_registry_enabled_default=False,
        command="TL",
    ),
    NetproUpsUsbButtonDescription(
        key="battery_test_stop",
        translation_key="battery_test_stop",
        name="Battery Test Stop",
        entity_registry_enabled_default=False,
        command="CT",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up NetPRO UPS USB buttons."""
    coordinator: NetproUpsUsbCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        NetproUpsUsbButton(coordinator, description) for description in BUTTON_DESCRIPTIONS
    )


class NetproUpsUsbButton(CoordinatorEntity[NetproUpsUsbCoordinator], ButtonEntity):
    """Representation of a NetPRO UPS USB command button."""

    entity_description: NetproUpsUsbButtonDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NetproUpsUsbCoordinator,
        description: NetproUpsUsbButtonDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.hub.device_identifier()}_{description.key}"

    @property
    def device_info(self) -> dict:
        """Return device information."""
        return self.coordinator.hub.device_info_payload()

    async def async_press(self) -> None:
        """Execute the configured UPS command."""
        await self.coordinator.hub.async_send_command(
            self.coordinator.hass,
            self.entity_description.command,
        )
        await self.coordinator.async_request_refresh()