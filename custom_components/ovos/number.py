"""Latitude/longitude as editable number entities."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN, CONF_LATITUDE, CONF_LONGITUDE
from .shared_config import read_shared_config, write_shared_config_key


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities):
    add_entities(
        [
            OvosCoordinateNumber(entry, "latitude", "Latitude", "mdi:latitude"),
            OvosCoordinateNumber(entry, "longitude", "Longitude", "mdi:longitude"),
        ]
    )


class OvosCoordinateNumber(NumberEntity):
    """One half of location.coordinate — merges into the nested dict
    without disturbing the other half or the sibling timezone key.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = -180.0
    _attr_native_max_value = 180.0
    _attr_native_step = 0.000001

    def __init__(self, entry: ConfigEntry, field: str, name: str, icon: str) -> None:
        self._entry = entry
        self._field = field
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{field}"
        conf_key = CONF_LATITUDE if field == "latitude" else CONF_LONGITUDE
        self._attr_native_value = entry.data[conf_key]

    def _write(self) -> None:
        location = read_shared_config().get("location", {})
        coordinate = location.get("coordinate", {})
        coordinate[self._field] = self._attr_native_value
        location["coordinate"] = coordinate
        write_shared_config_key("location", location)

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        await self.hass.async_add_executor_job(self._write)
        self.async_write_ha_state()
