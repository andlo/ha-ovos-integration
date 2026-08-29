"""Polls each installed skill's own current settings, keyed by skill_id
-- backs the live per-skill settings entities (switch.py/number.py's
and text.py's per-skill classes).

Discovers skills directly from each configured add-on's own /skills
list (curated ovos-skills and ovos-skills-extra, whichever have an API
URL configured) -- NOT from this integration's own subentries. A skill
installed directly against an add-on's API, outside the "Add sub-entry"
flow, still gets its settings polled and shown this way; subentries (if
one exists for a given skill_id) are only consulted separately, by the
platform files, to decide whether a live entity can also be scoped
under that subentry for deletion/organization purposes.
"""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .skill_settings import (
    get_skills_api_url,
    get_skills_extra_api_url,
    list_installed_skills,
    resolve_fields,
)

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
        for api_url, source_type in (
            (get_skills_api_url(), "curated"), (get_skills_extra_api_url(), "extra"),
        ):
            if not api_url:
                continue
            for skill in list_installed_skills(api_url):
                skill_id = skill.get("skill_id")
                if not skill_id or skill_id in result:
                    continue
                package_name = skill.get("package_name", "")
                fields, current = resolve_fields(api_url, skill_id, package_name)
                result[skill_id] = {
                    "fields": fields,
                    "current": current,
                    "api_url": api_url,
                    "version": skill.get("version"),
                    "source_type": source_type,
                    "source": skill.get("source", ""),
                    "package_name": package_name,
                }
        return result
