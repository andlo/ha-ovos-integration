"""Language and API URLs as editable text entities, backed by the
shared-config coordinator -- plus live text entities for non-sensitive
string skill settings (see issue #3). See switch.py's docstring for
why a field matching skill_settings.SENSITIVE_NAME_HINTS never becomes
a live entity here.
"""
from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CORE_SETTINGS_DEVICE_ID, CONF_LANG, CONF_SKILLS_API_URL, CONF_CORE_API_URL, CONF_PERSONA_API_URL, CONF_SKILLS_EXTRA_API_URL, CONF_SKILL_CONFIG_TOOL_URL
from .coordinator import OvosSharedConfigCoordinator
from .shared_config import write_shared_config_key, write_nested_config_key
from .skill_settings import write_settings
from .skill_settings_coordinator import OvosSkillSettingsCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities):
    coordinator: OvosSharedConfigCoordinator = hass.data[DOMAIN][entry.entry_id]
    add_entities([
        OvosLanguageText(coordinator, entry),
        OvosSkillsApiUrlText(coordinator, entry),
        OvosCoreApiUrlText(coordinator, entry),
        OvosPersonaApiUrlText(coordinator, entry),
        OvosSkillsExtraApiUrlText(coordinator, entry),
        OvosSkillConfigToolUrlText(coordinator, entry),
        OvosNestedText(
            coordinator, entry, ["location", "city", "name"], "",
            "City", "mdi:city",
        ),
        OvosNestedText(
            coordinator, entry, ["location", "city", "state", "name"], "",
            "State/region", "mdi:map",
        ),
        OvosNestedText(
            coordinator, entry, ["location", "city", "state", "code"], "",
            "State/region code", "mdi:map",
        ),
        OvosNestedText(
            coordinator, entry, ["location", "city", "state", "country", "name"], "",
            "Country", "mdi:earth",
        ),
        OvosNestedText(
            coordinator, entry, ["location", "city", "state", "country", "code"], "",
            "Country code", "mdi:earth",
        ),
        OvosNestedText(
            coordinator, entry, ["location", "timezone", "code"], "",
            "Timezone", "mdi:clock-time-eight-outline",
        ),
    ])


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
            OvosSkillSettingText(
                settings_coordinator, subentry_by_skill.get(skill_id, skill_id),
                skill_id, field["name"],
            )
            for field in skill_data["fields"]
            if field.get("type") == "text"
        ]
        if not skill_entities:
            continue
        subentry_id = subentry_by_skill.get(skill_id)
        if subentry_id:
            add_entities(skill_entities, config_subentry_id=subentry_id)
        else:
            add_entities(skill_entities)


class OvosLanguageText(CoordinatorEntity, TextEntity):
    """Value is always derived live from coordinator.data — same source
    whether it changed via this entity, an external edit, or another
    add-on writing its own section of the shared file.
    """

    _attr_has_entity_name = True
    _attr_device_info = DeviceInfo(identifiers={(DOMAIN, CORE_SETTINGS_DEVICE_ID)})
    _attr_name = "Language"
    _attr_icon = "mdi:translate"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: OvosSharedConfigCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_lang"

    @property
    def native_value(self) -> str:
        return self.coordinator.data.get(CONF_LANG, self._entry.data[CONF_LANG])

    async def async_set_value(self, value: str) -> None:
        await self.hass.async_add_executor_job(
            write_shared_config_key, CONF_LANG, value
        )
        await self.coordinator.async_request_refresh()


class OvosSkillsApiUrlText(CoordinatorEntity, TextEntity):
    """The ovos-skills add-on's own base URL, e.g. http://<hostname>:8500.

    Its Supervisor-assigned hostname is repo-hash-specific and can't be
    guessed reliably, so this is provided once here rather than hardcoded
    — read by the skill-management subentry flow to reach the API.
    """

    _attr_has_entity_name = True
    _attr_device_info = DeviceInfo(identifiers={(DOMAIN, CORE_SETTINGS_DEVICE_ID)})
    _attr_name = "Skills API URL"
    _attr_icon = "mdi:link-variant"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: OvosSharedConfigCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_skills_api_url"

    @property
    def native_value(self) -> str:
        return self.coordinator.data.get(CONF_SKILLS_API_URL, "")

    async def async_set_value(self, value: str) -> None:
        await self.hass.async_add_executor_job(
            write_shared_config_key, CONF_SKILLS_API_URL, value
        )
        await self.coordinator.async_request_refresh()


class OvosCoreApiUrlText(CoordinatorEntity, TextEntity):
    """The ovos-core add-on's own base URL, e.g. http://<hostname>:8500.

    Same reasoning as OvosSkillsApiUrlText: its Supervisor-assigned
    hostname is repo-hash-specific and can't be guessed reliably, so
    this is provided once here rather than hardcoded -- read by
    voice_subentry.py's autoconfigure flow to reach ovos-core's
    /autoconfigure endpoint.
    """

    _attr_has_entity_name = True
    _attr_device_info = DeviceInfo(identifiers={(DOMAIN, CORE_SETTINGS_DEVICE_ID)})
    _attr_name = "Core API URL"
    _attr_icon = "mdi:link-variant"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: OvosSharedConfigCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_core_api_url"

    @property
    def native_value(self) -> str:
        return self.coordinator.data.get(CONF_CORE_API_URL, "")

    async def async_set_value(self, value: str) -> None:
        await self.hass.async_add_executor_job(
            write_shared_config_key, CONF_CORE_API_URL, value
        )
        await self.coordinator.async_request_refresh()


class OvosPersonaApiUrlText(CoordinatorEntity, TextEntity):
    """The ovos-persona add-on's own bridge API base URL, e.g.
    http://<hostname>:8338 -- see persona_subentry.py. Same reasoning as
    OvosSkillsApiUrlText/OvosCoreApiUrlText: a repo-hash-specific
    hostname that can't be guessed, provided once here. Deliberately
    independent of the other two API URL fields -- ovos-persona can run
    with or without ovos-skills present, see DEVELOPER.md.
    """

    _attr_has_entity_name = True
    _attr_device_info = DeviceInfo(identifiers={(DOMAIN, CORE_SETTINGS_DEVICE_ID)})
    _attr_name = "Persona API URL"
    _attr_icon = "mdi:link-variant"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: OvosSharedConfigCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_persona_api_url"

    @property
    def native_value(self) -> str:
        return self.coordinator.data.get(CONF_PERSONA_API_URL, "")

    async def async_set_value(self, value: str) -> None:
        await self.hass.async_add_executor_job(
            write_shared_config_key, CONF_PERSONA_API_URL, value
        )
        await self.coordinator.async_request_refresh()


class OvosSkillsExtraApiUrlText(CoordinatorEntity, TextEntity):
    """The ovos-skills-extra add-on's own base URL, e.g.
    http://<hostname>:8502. Entirely optional -- ovos-skills-extra is an
    opt-in add-on; leaving this blank just means skill_subentry.py's
    "Extra" install path and persona_subentry.py's automatic
    fallback-skill wiring stay unavailable, nothing breaks.
    """

    _attr_has_entity_name = True
    _attr_device_info = DeviceInfo(identifiers={(DOMAIN, CORE_SETTINGS_DEVICE_ID)})
    _attr_name = "Skills Extra API URL"
    _attr_icon = "mdi:link-variant"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: OvosSharedConfigCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_skills_extra_api_url"

    @property
    def native_value(self) -> str:
        return self.coordinator.data.get(CONF_SKILLS_EXTRA_API_URL, "")

    async def async_set_value(self, value: str) -> None:
        await self.hass.async_add_executor_job(
            write_shared_config_key, CONF_SKILLS_EXTRA_API_URL, value
        )
        await self.coordinator.async_request_refresh()


class OvosSkillConfigToolUrlText(CoordinatorEntity, TextEntity):
    """Base URL for a self-hosted ovos-skill-config-tool instance
    (https://github.com/OscillateLabsLLC/ovos-skill-config-tool),
    e.g. http://<hostname>:8000. Entirely optional and not one of this
    project's own add-ons -- not auto-discovered via Supervisor for
    that reason (see supervisor_discovery.py). When set, each skill
    device gets a "Visit" link to it (see sensor.py) as an escape hatch
    for settings this integration's own live entities can't represent
    (nested objects/arrays) -- never a replacement for them.
    """

    _attr_has_entity_name = True
    _attr_device_info = DeviceInfo(identifiers={(DOMAIN, CORE_SETTINGS_DEVICE_ID)})
    _attr_name = "Skill Config Tool URL"
    _attr_icon = "mdi:link-variant"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: OvosSharedConfigCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_skill_config_tool_url"

    @property
    def native_value(self) -> str:
        return self.coordinator.data.get(CONF_SKILL_CONFIG_TOOL_URL, "")

    async def async_set_value(self, value: str) -> None:
        await self.hass.async_add_executor_job(
            write_shared_config_key, CONF_SKILL_CONFIG_TOOL_URL, value
        )
        await self.coordinator.async_request_refresh()


class OvosNestedText(CoordinatorEntity, TextEntity):
    """Any of ovos-config's own nested string preferences (location's
    own sub-fields, timezone code) -- deeper than write_shared_config_
    key's own flat top-level-only merge handles, so writes go through
    write_nested_config_key instead (see shared_config.py's own
    docstring). One generic class rather than one near-identical one
    per field, same reasoning as select.py's own OvosPreferenceSelect.

    native_value walks self.coordinator.data directly -- NOT a fresh
    disk read. Confirmed the hard way (a real
    "Detected blocking call to open... inside the event loop" warning
    on an actual Home Assistant instance): this property is called
    synchronously from HA Core's own event loop, same as
    OvosCoordinateNumber's own native_value in number.py already does
    correctly (walking self.coordinator.data, not calling a disk-
    reading helper) -- the coordinator's own _async_update_data is the
    only place file I/O for reads is supposed to happen, already
    correctly wrapped in async_add_executor_job.

    Empty string default, not one of ovos-config's own baked-in values
    like OvosPreferenceSelect's DEFAULT_* constants use -- confirmed by
    reading ovos-config's own default mycroft.conf directly: its own
    location block is a real US address (Lawrence, Kansas), not a
    placeholder meant to be shipped as anyone's actual default: a
    blank field prompting deliberate entry is more honest here than
    quietly defaulting a Danish (or any other) install to Kansas.
    """

    _attr_has_entity_name = True
    _attr_device_info = DeviceInfo(identifiers={(DOMAIN, CORE_SETTINGS_DEVICE_ID)})
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: OvosSharedConfigCoordinator,
        entry: ConfigEntry,
        path_parts: list[str],
        default: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._path_parts = path_parts
        self._default = default
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{'_'.join(path_parts)}"

    @property
    def native_value(self) -> str:
        node = self.coordinator.data
        for part in self._path_parts:
            if not isinstance(node, dict) or part not in node:
                return self._default
            node = node[part]
        return node

    async def async_set_value(self, value: str) -> None:
        await self.hass.async_add_executor_job(
            write_nested_config_key, self._path_parts, value
        )
        await self.coordinator.async_request_refresh()


class OvosSkillSettingText(CoordinatorEntity, TextEntity):
    """A non-sensitive string skill setting as a live entity -- see
    this module's own docstring. Only ever created for fields
    skill_settings.infer_fields_from_settings/resolve_fields already
    classified as plain "text" (never "password") -- the safety
    decision is made once, upstream, not re-checked here.
    """

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
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, skill_id)})

    @property
    def native_value(self) -> str:
        skill_data = self.coordinator.data.get(self._skill_id, {})
        return str(skill_data.get("current", {}).get(self._field_name, ""))

    async def async_set_value(self, value: str) -> None:
        skill_data = self.coordinator.data.get(self._skill_id, {})
        api_url = skill_data.get("api_url")
        if not api_url:
            return
        merged = {**skill_data.get("current", {}), self._field_name: value}
        await self.hass.async_add_executor_job(
            write_settings, api_url, self._skill_id, merged
        )
        await self.coordinator.async_request_refresh()
