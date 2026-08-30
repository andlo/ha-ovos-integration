"""Latitude/longitude, plus live number entities for numeric skill
settings (see issue #3 -- "Skill settings as live entities... not a
one-off reconfigure flow"). Both backed by coordinators, different ones
-- see shared_config-based OvosCoordinateNumber vs. per-skill
OvosSkillSettingNumber below.
"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CORE_SETTINGS_DEVICE_ID, CONF_LATITUDE, CONF_LONGITUDE, CORE_NUMBER_SETTINGS
from .coordinator import OvosSharedConfigCoordinator
from .shared_config import read_shared_config, write_shared_config_key, write_nested_config_key
from .skill_settings import write_settings
from .skill_settings_coordinator import OvosSkillSettingsCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities):
    coordinator: OvosSharedConfigCoordinator = hass.data[DOMAIN][entry.entry_id]
    core_settings_subentry_id = hass.data[DOMAIN][f"{entry.entry_id}_core_settings_subentry"]
    add_entities(
        [
            OvosCoordinateNumber(
                coordinator, entry, "latitude", "Latitude", "mdi:latitude", CONF_LATITUDE
            ),
            OvosCoordinateNumber(
                coordinator, entry, "longitude", "Longitude", "mdi:longitude", CONF_LONGITUDE
            ),
        ] + [
            OvosNestedNumber(coordinator, entry, *row)
            for row in CORE_NUMBER_SETTINGS
        ],
        config_subentry_id=core_settings_subentry_id,
    )

    settings_coordinator: OvosSkillSettingsCoordinator = hass.data[DOMAIN][
        f"{entry.entry_id}_skill_settings"
    ]
    subentry_by_skill = {
        subentry.data["skill_id"]: subentry_id
        for subentry_id, subentry in entry.subentries.items()
        if subentry.subentry_type == "skill"
    }
    for skill_id, skill_data in settings_coordinator.data.items():
        skill_entities = [
            OvosSkillSettingNumber(
                settings_coordinator, subentry_by_skill.get(skill_id, skill_id),
                skill_id, field["name"],
            )
            for field in skill_data["fields"]
            if field.get("type") == "number"
        ]
        if not skill_entities:
            continue
        subentry_id = subentry_by_skill.get(skill_id)
        if subentry_id:
            add_entities(skill_entities, config_subentry_id=subentry_id)
        else:
            add_entities(skill_entities)


class OvosCoordinateNumber(CoordinatorEntity, NumberEntity):
    """One half of location.coordinate — merges into the nested dict on
    write, without disturbing the other half or the sibling timezone key.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_info = DeviceInfo(identifiers={(DOMAIN, CORE_SETTINGS_DEVICE_ID)})
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


class OvosNestedNumber(CoordinatorEntity, NumberEntity):
    """Any row from const.py's own CORE_NUMBER_SETTINGS table -- one
    generic class for all of ovos-config's deeper numeric intent-
    pipeline settings (confidence thresholds, timeouts, ...), same
    reasoning as text.py's own OvosNestedText: adding a new one later
    is a new row in that table, not a new class or a new line in this
    file's own add_entities call.

    native_value walks self.coordinator.data directly, never a helper
    that opens the shared file itself -- confirmed necessary the hard
    way elsewhere in this project (see OvosNestedText's own docstring
    for the actual "Detected blocking call to open... inside the event
    loop" warning this exact pattern avoids).
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: OvosSharedConfigCoordinator,
        entry: ConfigEntry,
        path_parts: list[str],
        name: str,
        icon: str,
        default: float,
        min_value: float,
        max_value: float,
        step: float,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._path_parts = path_parts
        self._default = default
        self._attr_name = name
        self._attr_icon = icon
        self._attr_native_min_value = min_value
        self._attr_native_max_value = max_value
        self._attr_native_step = step
        self._attr_unique_id = f"{entry.entry_id}_{'_'.join(path_parts)}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, CORE_SETTINGS_DEVICE_ID)})

    @property
    def native_value(self) -> float:
        node = self.coordinator.data
        for part in self._path_parts:
            if not isinstance(node, dict) or part not in node:
                return self._default
            node = node[part]
        try:
            return float(node)
        except (TypeError, ValueError):
            return self._default

    async def async_set_native_value(self, value: float) -> None:
        await self.hass.async_add_executor_job(
            write_nested_config_key, self._path_parts, value
        )
        await self.coordinator.async_request_refresh()


class OvosSkillSettingNumber(CoordinatorEntity, NumberEntity):
    """A numeric skill setting as a live entity -- see this module's
    own docstring and switch.py's (same reasoning: attaches to the
    skill's existing device by identifiers, no min/max known ahead of
    time so left unbounded, unlike OvosCoordinateNumber's lat/long
    bounds).
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = -1_000_000_000.0
    _attr_native_max_value = 1_000_000_000.0
    _attr_native_step = 1.0

    def __init__(
        self,
        coordinator: OvosSkillSettingsCoordinator,
        subentry_id: str,
        skill_id: str,
        field_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._skill_id = skill_id
        self._field_name = field_name
        self._attr_name = field_name.replace("_", " ").title()
        self._attr_unique_id = f"{subentry_id}_{field_name}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, skill_id)})

    @property
    def native_value(self) -> float | None:
        skill_data = self.coordinator.data.get(self._skill_id, {})
        value = skill_data.get("current", {}).get(self._field_name)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        skill_data = self.coordinator.data.get(self._skill_id, {})
        api_url = skill_data.get("api_url")
        if not api_url:
            return
        merged = {**skill_data.get("current", {}), self._field_name: value}
        await self.hass.async_add_executor_job(
            write_settings, api_url, self._skill_id, merged
        )
        await self.coordinator.async_request_refresh()
