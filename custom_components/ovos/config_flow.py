"""Config flow for OpenVoiceOS.

Pre-fills suggested values from hass.config — see DEVELOPER.md's HA Core ->
mycroft.conf field mapping table for exactly which fields and why. These are
*suggestions* the user can edit before submitting, never locked values —
see DEVELOPER.md's "pre-fill, don't lock" design principle.
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigSubentryFlow
from homeassistant.core import callback

from .const import (
    ADDONS_UNIQUE_ID,
    CONF_DEVICE_ID,
    CONF_ENTRY_TYPE,
    CONF_MANUFACTURER,
    CONF_MODEL,
    CONF_NAME,
    CONF_SW_VERSION,
    CONF_TRANSPORT,
    CONF_USER_ID,
    ENTRY_TYPE_ADDONS,
    ENTRY_TYPE_DEVICE,
    ENTRY_TYPE_INBOUND,
    INBOUND_UNIQUE_ID,
    TRANSPORT_INBOUND,
    DOMAIN,
    CONF_LANG,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_TIMEZONE,
    CONF_SYSTEM_UNIT,
    UNIT_METRIC,
    UNIT_IMPERIAL,
)
from .skill_subentry import SkillSubentryFlowHandler
from .voice_subentry import AutoconfigureSubentryFlowHandler
from .persona_subentry import PersonaSubentryFlowHandler
from .core_settings_subentry import CoreSettingsSubentryFlowHandler


def _guess_lang(hass) -> str:
    """f"{language}-{country}" is a reasonable guess, not a guaranteed
    match against a real OVOS locale — see DEVELOPER.md.
    """
    language = (hass.config.language or "en").lower()
    country = (hass.config.country or "US").lower()
    return f"{language}-{country}"


def _guess_unit_system(hass) -> str:
    """HA doesn't expose a single flat metric/imperial label in a
    consistent place across versions — unit_system.length ("km" vs "mi")
    is the reliable proxy, see DEVELOPER.md.
    """
    length_unit = getattr(hass.config.units, "length_unit", "km")
    return UNIT_IMPERIAL if length_unit == "mi" else UNIT_METRIC


class OvosConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Two kinds of entries (issue #7): the one add-on entry (haos-ovos-addons'
    shared config) and one entry per OpenVoiceOS device.

    Version 2 since #7; version 1 entries are migrated in __init__.py.
    """

    VERSION = 2

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Skills are managed as subentries under this one entry —
        Settings → Devices & services → OpenVoiceOS → Add sub-entry.
        Only the add-on entry has them; a device's settings are entities.
        """
        if config_entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_ADDONS) != ENTRY_TYPE_ADDONS:
            return {}
        return {
            "skill": SkillSubentryFlowHandler,
            "autoconfigure": AutoconfigureSubentryFlowHandler,
            "persona": PersonaSubentryFlowHandler,
            "core_settings": CoreSettingsSubentryFlowHandler,
        }

    async def async_step_user(self, user_input=None):
        return self.async_show_menu(step_id="user", menu_options=["addons", "device"])

    async def async_step_device(self, user_input=None):
        """A device isn't added from here: it connects to HA itself (#9)
        and is then offered under Discovered. What is added here is the
        permission for devices to connect at all -- once. HiveMind (#8)
        will be offered here too when it exists."""
        await self.async_set_unique_id(INBOUND_UNIQUE_ID)
        if self._async_current_entries() and any(
            e.unique_id == INBOUND_UNIQUE_ID for e in self._async_current_entries()
        ):
            return self.async_abort(reason="device_connects_itself")
        if user_input is not None:
            return self.async_create_entry(
                title="OpenVoiceOS devices",
                data={CONF_ENTRY_TYPE: ENTRY_TYPE_INBOUND},
            )
        return self.async_show_form(step_id="device")

    async def async_step_integration_discovery(self, discovery_info):
        """A device connected over ovos/connect that HA doesn't know yet."""
        await self.async_set_unique_id(discovery_info[CONF_DEVICE_ID])
        self._abort_if_unique_id_configured()
        self._discovered = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info[CONF_NAME]}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(self, user_input=None):
        info = self._discovered
        if user_input is not None:
            return self.async_create_entry(title=info[CONF_NAME], data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_DEVICE,
                CONF_TRANSPORT: TRANSPORT_INBOUND,
                **{k: info.get(k) for k in (
                    CONF_DEVICE_ID, CONF_NAME, CONF_USER_ID,
                    CONF_MODEL, CONF_MANUFACTURER, CONF_SW_VERSION,
                ) if info.get(k) is not None},
            })
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={
                "name": info[CONF_NAME],
                "model": info.get(CONF_MODEL) or "OpenVoiceOS",
                "user": info.get("user_name") or "?",
            },
        )

    async def async_step_addons(self, user_input=None):
        # Only one add-on entry makes sense — this is *the* shared config of
        # haos-ovos-addons, not a per-device thing.
        await self.async_set_unique_id(ADDONS_UNIQUE_ID)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}
        if user_input is not None:
            return self.async_create_entry(
                title="OpenVoiceOS add-ons",
                data={**user_input, CONF_ENTRY_TYPE: ENTRY_TYPE_ADDONS},
            )

        suggested = {
            CONF_LANG: _guess_lang(self.hass),
            CONF_LATITUDE: self.hass.config.latitude,
            CONF_LONGITUDE: self.hass.config.longitude,
            CONF_TIMEZONE: self.hass.config.time_zone,
            CONF_SYSTEM_UNIT: _guess_unit_system(self.hass),
        }

        schema = vol.Schema(
            {
                vol.Required(CONF_LANG, default=suggested[CONF_LANG]): str,
                vol.Required(
                    CONF_LATITUDE, default=suggested[CONF_LATITUDE]
                ): vol.Coerce(float),
                vol.Required(
                    CONF_LONGITUDE, default=suggested[CONF_LONGITUDE]
                ): vol.Coerce(float),
                vol.Required(
                    CONF_TIMEZONE, default=suggested[CONF_TIMEZONE]
                ): str,
                vol.Required(
                    CONF_SYSTEM_UNIT, default=suggested[CONF_SYSTEM_UNIT]
                ): vol.In([UNIT_METRIC, UNIT_IMPERIAL]),
            }
        )

        return self.async_show_form(
            step_id="addons", data_schema=schema, errors=errors
        )
