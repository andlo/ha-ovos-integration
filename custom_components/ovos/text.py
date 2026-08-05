"""Language as an editable text entity, backed by the shared-config coordinator."""
from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_LANG, CONF_SKILLS_API_URL, CONF_CORE_API_URL, CONF_PERSONA_API_URL
from .coordinator import OvosSharedConfigCoordinator
from .shared_config import write_shared_config_key


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities):
    coordinator: OvosSharedConfigCoordinator = hass.data[DOMAIN][entry.entry_id]
    add_entities([
        OvosLanguageText(coordinator, entry),
        OvosSkillsApiUrlText(coordinator, entry),
        OvosCoreApiUrlText(coordinator, entry),
        OvosPersonaApiUrlText(coordinator, entry),
    ])


class OvosLanguageText(CoordinatorEntity, TextEntity):
    """Value is always derived live from coordinator.data — same source
    whether it changed via this entity, an external edit, or another
    add-on writing its own section of the shared file.
    """

    _attr_has_entity_name = True
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
