"""Live switch entities for boolean skill settings -- see issue #3
("Skill settings as live entities... not a one-off reconfigure flow").

One switch per top-level boolean field, on the SAME device as the
skill's own version sensor (see sensor.py) -- reusing that device's
identifiers rather than creating a second device per skill, so a
skill's settings and its version sensor live on one device page.

Nested settings (objects/arrays) and anything matching
skill_settings.SENSITIVE_NAME_HINTS never become live entities here.
Passwords/tokens/etc. specifically: an HA entity's state is stored in
history and exposed via the API/logbook indefinitely, unlike a
form field you fill in once and never see rendered back -- turning a
secret into a standing, queryable piece of state would be a real,
ongoing exposure, not a one-off risk. Use skill_subentry.py's own
one-off reconfigure flow for those, or a self-hosted
ovos-skill-config-tool (CONF_SKILL_CONFIG_TOOL_URL, see sensor.py) if a
genuinely visible/editable-anytime secrets UI is wanted anyway -- a
deliberate choice a person makes for their own instance, not this
integration's default behavior.
"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .skill_settings import write_settings
from .skill_settings_coordinator import OvosSkillSettingsCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities):
    coordinator: OvosSkillSettingsCoordinator = hass.data[DOMAIN][
        f"{entry.entry_id}_skill_settings"
    ]

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != "skill":
            continue
        skill_id = subentry.data["skill_id"]
        skill_data = coordinator.data.get(skill_id)
        if not skill_data:
            continue
        entities = [
            OvosSkillSettingSwitch(coordinator, subentry_id, skill_id, field["name"])
            for field in skill_data["fields"]
            if field.get("type") == "checkbox"
        ]
        if entities:
            add_entities(entities, config_subentry_id=subentry_id)


class OvosSkillSettingSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

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
        # Minimal DeviceInfo -- attaches to the same device sensor.py
        # already fully describes (name/manufacturer/model), matched by
        # identifiers alone, not a second device.
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, skill_id)})

    @property
    def is_on(self) -> bool:
        skill_data = self.coordinator.data.get(self._skill_id, {})
        value = skill_data.get("current", {}).get(self._field_name)
        if isinstance(value, str):
            return value.strip().lower() == "true"
        return bool(value)

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        skill_data = self.coordinator.data.get(self._skill_id, {})
        api_url = skill_data.get("api_url")
        if not api_url:
            return
        # Merge into the FULL current settings, same principle as the
        # reconfigure flow -- never drop sibling keys on a write.
        merged = {**skill_data.get("current", {}), self._field_name: value}
        await self.hass.async_add_executor_job(
            write_settings, api_url, self._skill_id, merged
        )
        await self.coordinator.async_request_refresh()
