"""Latitude/longitude, backed by the shared-config coordinator."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_LATITUDE, CONF_LONGITUDE
from .coordinator import OvosSharedConfigCoordinator
from .shared_config import read_shared_config, write_shared_config_key


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities):
    coordinator: OvosSharedConfigCoordinator = hass.data[DOMAIN][entry.entry_id]
    add_entities(
        [
            OvosCoordinateNumber(
                coordinator, entry, "latitude", "Latitude", "mdi:latitude", CONF_LATITUDE
            ),
            OvosCoordinateNumber(
                coordinator, entry, "longitude", "Longitude", "mdi:longitude", CONF_LONGITUDE
            ),
        ]
    )


class OvosCoordinateNumber(CoordinatorEntity, NumberEntity):
    """One half of location.coordinate — merges into the nested dict on
    write, without disturbing the other half or the sibling timezone key.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = -180.0
    _attr_native_max_value = 180.0
    _attr_native_step = 0.000001

    def __init__(
        self,
        coordinator: OvosSharedConfigCoordinator,
        entry: ConfigEntry,
        field: str,
        name: str,
        icon: str,
        conf_key: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._field = field
        self._conf_key = conf_key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{field}"

    @property
    def native_value(self) -> float:
        coordinate = self.coordinator.data.get("location", {}).get("coordinate", {})
        return coordinate.get(self._field, self._entry.data[self._conf_key])

    def _write_value(self, value: float) -> None:
        full_config = read_shared_config()
        location = full_config.get("location", {})
        coordinate = location.get("coordinate", {})
        coordinate[self._field] = value
        location["coordinate"] = coordinate
        write_shared_config_key("location", location)

    async def async_set_native_value(self, value: float) -> None:
        await self.hass.async_add_executor_job(self._write_value, value)
        await self.coordinator.async_request_refresh()
