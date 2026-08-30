"""System unit (metric/imperial) and the rest of ovos-config's own
top-level format/unit preferences, all backed by the shared-config
coordinator. See const.py's own comment for why only these -- ovos-
config's simple, global preferences -- are exposed here, not every
top-level key in the shared config (nested plugin/wiring sections are
deliberately left alone).
"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN, CONF_SYSTEM_UNIT, UNIT_METRIC, UNIT_IMPERIAL,
    CONF_TEMPERATURE_UNIT, DEFAULT_TEMPERATURE_UNIT, TEMP_CELSIUS, TEMP_FAHRENHEIT,
    CONF_WINDSPEED_UNIT, DEFAULT_WINDSPEED_UNIT, WINDSPEED_UNITS,
    CONF_PRECIPITATION_UNIT, DEFAULT_PRECIPITATION_UNIT, PRECIPITATION_UNITS,
    CONF_TIME_FORMAT, DEFAULT_TIME_FORMAT,
    CONF_SPOKEN_TIME_FORMAT, DEFAULT_SPOKEN_TIME_FORMAT,
    CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT, TIME_FORMATS, DATE_FORMATS,
)
from .coordinator import OvosSharedConfigCoordinator
from .shared_config import write_shared_config_key


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities):
    coordinator: OvosSharedConfigCoordinator = hass.data[DOMAIN][entry.entry_id]
    add_entities([
        OvosSystemUnitSelect(coordinator, entry),
        OvosPreferenceSelect(
            coordinator, entry, CONF_TEMPERATURE_UNIT, DEFAULT_TEMPERATURE_UNIT,
            [TEMP_CELSIUS, TEMP_FAHRENHEIT], "Temperature unit", "mdi:thermometer",
        ),
        OvosPreferenceSelect(
            coordinator, entry, CONF_WINDSPEED_UNIT, DEFAULT_WINDSPEED_UNIT,
            WINDSPEED_UNITS, "Windspeed unit", "mdi:weather-windy",
        ),
        OvosPreferenceSelect(
            coordinator, entry, CONF_PRECIPITATION_UNIT, DEFAULT_PRECIPITATION_UNIT,
            PRECIPITATION_UNITS, "Precipitation unit", "mdi:weather-pouring",
        ),
        OvosPreferenceSelect(
            coordinator, entry, CONF_TIME_FORMAT, DEFAULT_TIME_FORMAT,
            TIME_FORMATS, "Time format", "mdi:clock-outline",
        ),
        OvosPreferenceSelect(
            coordinator, entry, CONF_SPOKEN_TIME_FORMAT, DEFAULT_SPOKEN_TIME_FORMAT,
            TIME_FORMATS, "Spoken time format", "mdi:clock-time-four-outline",
        ),
        OvosPreferenceSelect(
            coordinator, entry, CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT,
            DATE_FORMATS, "Date format", "mdi:calendar",
        ),
    ])


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


class OvosPreferenceSelect(CoordinatorEntity, SelectEntity):
    """Any of ovos-config's own simple top-level enum preferences
    (temperature/windspeed/precipitation unit, time/date format) --
    same shape as OvosSystemUnitSelect, generalized rather than one
    near-identical class per setting, since all of these differ only
    in their key/default/valid-options/name/icon, not in behavior.

    Falls back to a hardcoded default (see const.py's own DEFAULT_*
    comment for why these exactly match ovos-config's real baked-in
    values), not self._entry.data like OvosSystemUnitSelect does --
    these settings are new, never part of the original config flow's
    own entry.data the way system_unit already was.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: OvosSharedConfigCoordinator,
        entry: ConfigEntry,
        conf_key: str,
        default: str,
        options: list[str],
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._conf_key = conf_key
        self._default = default
        self._attr_options = options
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{conf_key}"

    @property
    def current_option(self) -> str:
        return self.coordinator.data.get(self._conf_key, self._default)

    async def async_select_option(self, option: str) -> None:
        await self.hass.async_add_executor_job(
            write_shared_config_key, self._conf_key, option
        )
        await self.coordinator.async_request_refresh()

