"""Coordinator for NetPRO UPS USB."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .hub import NetproUpsSnapshot, NetproUpsUsbError, NetproUpsUsbHub

_LOGGER = logging.getLogger(__name__)


class NetproUpsUsbCoordinator(DataUpdateCoordinator[NetproUpsSnapshot]):
    """Coordinate updates from the UPS."""

    # Keep last known data for this many consecutive failures before going Unavailable
    _STALE_THRESHOLD = 3

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        hub: NetproUpsUsbHub,
        update_interval_seconds: int,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=update_interval_seconds),
        )
        self.entry = entry
        self.hub = hub
        self._consecutive_failures = 0

    async def _async_update_data(self) -> NetproUpsSnapshot:
        """Fetch data from the UPS, keeping last values on transient port errors."""
        try:
            snapshot = await self.hub.async_fetch_snapshot(self.hass)
            self._consecutive_failures = 0
            return snapshot
        except NetproUpsUsbError as err:
            self._consecutive_failures += 1
            if self._consecutive_failures < self._STALE_THRESHOLD and self.data is not None:
                _LOGGER.debug(
                    "UPS poll failed (%d/%d), keeping last known data: %s",
                    self._consecutive_failures,
                    self._STALE_THRESHOLD,
                    err,
                )
                return self.data
            raise UpdateFailed(str(err)) from err
