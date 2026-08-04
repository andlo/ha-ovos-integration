"""System unit (metric/imperial), backed by the shared-config coordinator."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_SYSTEM_UNIT, UNIT_METRIC, UNIT_IMPERIAL
from .coordinator import OvosSharedConfigCoordinator
from .shared_config import write_shared_config_key


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities):
    coordinator: OvosSharedConfigCoordinator = hass.data[DOMAIN][entry.entry_id]
    add_entities([OvosSystemUnitSelect(coordinator, entry)])


class OvosSystemUnitSelect(CoordinatorEntity, SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "System unit"
    _attr_icon = "mdi:ruler"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = [UNIT_METRIC, UNIT_IMPERIAL]

    def __init__(self, coordinator: OvosSharedConfigCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_system_unit"

    @property
    def current_option(self) -> str:
        return self.coordinator.data.get(
            CONF_SYSTEM_UNIT, self._entry.data[CONF_SYSTEM_UNIT]
        )

    async def async_select_option(self, option: str) -> None:
        await self.hass.async_add_executor_job(
            write_shared_config_key, CONF_SYSTEM_UNIT, option
        )
        await self.coordinator.async_request_refresh()
