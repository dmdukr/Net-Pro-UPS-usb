"""NetPRO UPS USB integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant

from .const import CONF_DEBUG_LOG, CONF_POLL_INTERVAL, DOMAIN, PLATFORMS
from .coordinator import NetproUpsUsbCoordinator
from .hub import NetproUpsUsbHub
from .logger import setup_integration_file_logger, teardown_integration_file_logger

_LOGGER = logging.getLogger(__name__)


def _effective(entry: ConfigEntry, key: str):
    """Return options value if present, otherwise fall back to data."""
    return entry.options.get(key, entry.data.get(key))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up NetPRO UPS USB from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    if _effective(entry, CONF_DEBUG_LOG):
        log_path = setup_integration_file_logger(hass)
        _LOGGER.info(
            "Setting up entry %s for %s on %s. Dedicated log: %s",
            entry.entry_id,
            _effective(entry, CONF_NAME),
            _effective(entry, CONF_PORT),
            log_path,
        )
    else:
        _LOGGER.info(
            "Setting up entry %s for %s on %s",
            entry.entry_id,
            _effective(entry, CONF_NAME),
            _effective(entry, CONF_PORT),
        )

    hub = NetproUpsUsbHub(
        name=_effective(entry, CONF_NAME),
        port=_effective(entry, CONF_PORT),
        protocol=entry.data["protocol"],
    )
    coordinator = NetproUpsUsbCoordinator(
        hass=hass,
        entry=entry,
        hub=hub,
        update_interval_seconds=_effective(entry, CONF_POLL_INTERVAL),
    )

    await coordinator.async_refresh()

    if not coordinator.last_update_success:
        _LOGGER.warning(
            "NetPRO UPS USB on %s started without a successful initial refresh. "
            "Protocol hint: %s, serial profile: %s, diagnostics: %s",
            _effective(entry, CONF_PORT),
            hub.protocol_hint,
            hub.serial_profile_name,
            hub.diagnostic_summary,
        )

    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading entry %s for port %s", entry.entry_id, _effective(entry, CONF_PORT))
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    hass.data[DOMAIN].pop(entry.entry_id, None)
    if not hass.data[DOMAIN]:
        teardown_integration_file_logger(hass)
        hass.data.pop(DOMAIN)
    return True
