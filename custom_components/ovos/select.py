"""System unit (metric/imperial) as an editable select entity."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN, CONF_SYSTEM_UNIT, UNIT_METRIC, UNIT_IMPERIAL
from .shared_config import read_shared_config, write_shared_config_key


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities):
    shared = await hass.async_add_executor_job(read_shared_config)
    current = shared.get(CONF_SYSTEM_UNIT, entry.data[CONF_SYSTEM_UNIT])
    add_entities([OvosSystemUnitSelect(entry, current)])


class OvosSystemUnitSelect(SelectEntity):
    """metric/imperial, written straight to the shared file's system_unit key."""

    _attr_has_entity_name = True
    _attr_name = "System unit"
    _attr_icon = "mdi:ruler"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = [UNIT_METRIC, UNIT_IMPERIAL]

    def __init__(self, entry: ConfigEntry, current_value: str) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_system_unit"
        self._attr_current_option = current_value

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        await self.hass.async_add_executor_job(
            write_shared_config_key, CONF_SYSTEM_UNIT, option
        )
        self.async_write_ha_state()
