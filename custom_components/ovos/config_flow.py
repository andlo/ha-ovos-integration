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
    """Handle the initial setup — one entry only, this is shared config."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Skills are managed as subentries under this one entry —
        Settings → Devices & services → OpenVoiceOS → Add sub-entry.
        """
        return {
            "skill": SkillSubentryFlowHandler,
            "autoconfigure": AutoconfigureSubentryFlowHandler,
        }

    async def async_step_user(self, user_input=None):
        # Only one entry makes sense — this is *the* shared config, not a
        # per-device thing.
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        errors: dict[str, str] = {}
        if user_input is not None:
            return self.async_create_entry(
                title="OpenVoiceOS", data=user_input
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
            step_id="user", data_schema=schema, errors=errors
        )
