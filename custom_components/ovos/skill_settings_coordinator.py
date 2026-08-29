"""Polls each installed skill's own current settings, keyed by skill_id
-- backs the live per-skill settings entities (switch.py/number.py's
and text.py's per-skill classes). Separate from OvosSharedConfigCoordinator
(that one polls the shared mycroft.conf; this one polls each skill's
own add-on API instead), and keyed per config entry the same way.

Reuses skill_settings.resolve_fields (settingsmeta when present and
exclusively checkbox fields, otherwise inferred from settings.json's
own value types) -- the exact same decision skill_subentry.py's
one-off reconfigure flow makes, so a setting shows up the same way
whether read live here or through that flow.
"""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .skill_settings import api_url_for_source_type, resolve_fields

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)


class OvosSkillSettingsCoordinator(DataUpdateCoordinator[dict]):
    """data shape: {skill_id: {"fields": [...], "current": {...}, "api_url": str}}"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        super().__init__(
            hass, _LOGGER, name="ovos_skill_settings", update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict:
        return await self.hass.async_add_executor_job(self._fetch_all)

    def _fetch_all(self) -> dict:
        result: dict = {}
        for subentry in self._entry.subentries.values():
            if subentry.subentry_type != "skill":
                continue
            skill_id = subentry.data["skill_id"]
            source_type = subentry.data.get("source_type", "curated")
            package_name = subentry.data.get("package_name", "")
            api_url = api_url_for_source_type(source_type)
            if not api_url:
                continue
            fields, current = resolve_fields(api_url, skill_id, package_name)
            result[skill_id] = {
                "fields": fields,
                "current": current,
                "api_url": api_url,
            }
        return result
