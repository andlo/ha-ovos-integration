"""Polls the shared /share/mycroft/mycroft.conf on a fixed interval.

One read serves every entity this integration exposes, no matter how many
get added later (language, coordinates, unit, future skill settings) —
see DEVELOPER.md for why polling was chosen over file watching for this
specific data (config that changes rarely, written from multiple
containers via atomic rename).
"""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .shared_config import read_shared_config

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)


class OvosSharedConfigCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="ovos_shared_config",
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict:
        return await self.hass.async_add_executor_job(read_shared_config)
