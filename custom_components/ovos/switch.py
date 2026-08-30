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

from .const import DOMAIN, CORE_SETTINGS_DEVICE_ID, CONF_CONFIRM_LISTENING, DEFAULT_CONFIRM_LISTENING, CORE_SWITCH_SETTINGS
from .coordinator import OvosSharedConfigCoordinator
from .shared_config import write_shared_config_key, write_nested_config_key
from .skill_settings import write_settings, set_skill_active
from .skill_settings_coordinator import OvosSkillSettingsCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities):
    shared_coordinator: OvosSharedConfigCoordinator = hass.data[DOMAIN][entry.entry_id]
    core_settings_subentry_id = hass.data[DOMAIN][f"{entry.entry_id}_core_settings_subentry"]
    add_entities(
        [OvosConfirmListeningSwitch(shared_coordinator, entry)] + [
            OvosNestedSwitch(shared_coordinator, entry, *row)
            for row in CORE_SWITCH_SETTINGS
        ],
        config_subentry_id=core_settings_subentry_id,
    )

    coordinator: OvosSkillSettingsCoordinator = hass.data[DOMAIN][
        f"{entry.entry_id}_skill_settings"
    ]

    # skill_id -> subentry_id, for skills that DO have one (added via
    # "Add sub-entry -> Skill") -- optional, not a precondition. A
    # skill installed directly against the add-on's own API still gets
    # its entities, just without config_subentry_id (see
    # skill_settings_coordinator.py's own docstring for why coordinator
    # discovery doesn't depend on subentries existing at all).
    subentry_by_skill = {
        subentry.data["skill_id"]: subentry_id
        for subentry_id, subentry in entry.subentries.items()
        if subentry.subentry_type == "skill"
    }

    for skill_id, skill_data in coordinator.data.items():
        entities = [OvosSkillActiveSwitch(coordinator, skill_id)] + [
            OvosSkillSettingSwitch(
                coordinator, subentry_by_skill.get(skill_id, skill_id), skill_id, field["name"]
            )
            for field in skill_data["fields"]
            if field.get("type") == "checkbox"
        ]
        if not entities:
            continue
        subentry_id = subentry_by_skill.get(skill_id)
        if subentry_id:
            add_entities(entities, config_subentry_id=subentry_id)
        else:
            add_entities(entities)


class OvosConfirmListeningSwitch(CoordinatorEntity, SwitchEntity):
    """Whether OVOS plays a beep when it starts listening -- ovos-
    config's own `confirm_listening` setting, the one boolean among its
    top-level preferences (see const.py and select.py's own comment for
    the rest of them). Backed by the shared-config coordinator, not the
    per-skill one below -- this is a global OVOS preference, not a
    skill's own setting.
    """

    _attr_has_entity_name = True
    _attr_name = "Confirm listening"
    _attr_icon = "mdi:bell-ring-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_info = DeviceInfo(identifiers={(DOMAIN, CORE_SETTINGS_DEVICE_ID)})

    def __init__(self, coordinator: OvosSharedConfigCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_confirm_listening"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get(CONF_CONFIRM_LISTENING, DEFAULT_CONFIRM_LISTENING))

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        await self.hass.async_add_executor_job(
            write_shared_config_key, CONF_CONFIRM_LISTENING, value
        )
        await self.coordinator.async_request_refresh()


class OvosNestedSwitch(CoordinatorEntity, SwitchEntity):
    """Any row from const.py's own CORE_SWITCH_SETTINGS table -- one
    generic class for all of ovos-config's deeper boolean intent-
    pipeline settings (Padatious/OCP flags), same reasoning as
    number.py's own OvosNestedNumber and text.py's own OvosNestedText:
    adding a new one later is a new row in that table, not a new class.
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
        default: bool,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._path_parts = path_parts
        self._default = default
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{'_'.join(path_parts)}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, CORE_SETTINGS_DEVICE_ID)})

    @property
    def is_on(self) -> bool:
        node = self.coordinator.data
        for part in self._path_parts:
            if not isinstance(node, dict) or part not in node:
                return self._default
            node = node[part]
        return bool(node)

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        await self.hass.async_add_executor_job(
            write_nested_config_key, self._path_parts, value
        )
        await self.coordinator.async_request_refresh()


class OvosSkillActiveSwitch(CoordinatorEntity, SwitchEntity):
    """Enable/disable this installed skill entirely -- ovos-skills' own
    GET/PUT /skills/{skill_id}/active, sending skillmanager.activate/
    deactivate on the shared bus (confirmed working end-to-end against
    a real skill's own process, see that add-on's own DOCS.md). Genuinely
    different from OvosSkillSettingSwitch below: this disables the
    skill entirely (its own process keeps running but stops responding
    to intents), not one of its own settings.json fields.

    One created per installed skill regardless of whether it has any
    boolean settings.json fields of its own -- every skill can be
    turned off, not just ones that happen to have a checkbox setting.
    """

    _attr_has_entity_name = True
    _attr_name = "Active"
    _attr_icon = "mdi:puzzle"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: OvosSkillSettingsCoordinator, skill_id: str) -> None:
        super().__init__(coordinator)
        self._skill_id = skill_id
        self._attr_unique_id = f"{skill_id}_active"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, skill_id)})

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get(self._skill_id, {}).get("active", True))

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        skill_data = self.coordinator.data.get(self._skill_id, {})
        api_url = skill_data.get("api_url")
        if not api_url:
            return
        await self.hass.async_add_executor_job(
            set_skill_active, api_url, self._skill_id, value
        )
        await self.coordinator.async_request_refresh()


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
