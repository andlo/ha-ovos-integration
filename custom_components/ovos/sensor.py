"""One sensor entity per installed skill, giving each skill its own
device in HA's device registry -- raised directly by comparing this
integration's subentry list to another integration's proper device
list (name + a model-line subtitle, expandable, not a bare title).

Discovers skills directly from each configured add-on's own /skills
list (curated ovos-skills and ovos-skills-extra), NOT only from
subentries -- a skill installed directly against an add-on's API,
outside this integration's "Add sub-entry" flow, still gets its own
device this way (see skill_settings_coordinator.py's own docstring for
the same reasoning, shared by the live settings entities). A subentry,
when one exists for a given skill_id, still supplies the device's
display name (the catalog's own name, nicer than a bare skill_id) and
scopes the entity for deletion/organization -- but is not a
precondition for the device/entity to exist at all.

Confirmed this is a genuine, modern HA mechanism, not a workaround:
config subentries can own devices (home-assistant/core PR #128157,
"Add config subentry support to device registry"), and entities create
their device automatically via their own device_info, same as any other
integration -- config_subentry_id, when passed, just scopes the entity
to that specific subentry rather than the shared config entry as a
whole.
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN, CONF_SKILL_CONFIG_TOOL_URL
from .shared_config import read_shared_config
from .skill_settings import get_skills_api_url, get_skills_extra_api_url, list_installed_skills


def _fetch_all_installed_skills() -> dict[str, dict]:
    """skill_id -> {"version", ...} across BOTH configured add-ons.
    Best-effort: an unreachable/unconfigured add-on just contributes
    nothing rather than blocking the other's skills from showing.
    """
    skills: dict[str, dict] = {}
    for api_url in (get_skills_api_url(), get_skills_extra_api_url()):
        if not api_url:
            continue
        for skill in list_installed_skills(api_url):
            skill_id = skill.get("skill_id")
            if skill_id and skill_id not in skills:
                skills[skill_id] = skill
    return skills


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities):
    installed = await hass.async_add_executor_job(_fetch_all_installed_skills)
    config_tool_url = await hass.async_add_executor_job(
        lambda: read_shared_config().get(CONF_SKILL_CONFIG_TOOL_URL) or None
    )

    subentry_by_skill = {
        subentry.data["skill_id"]: (subentry_id, subentry.title)
        for subentry_id, subentry in entry.subentries.items()
        if subentry.subentry_type == "skill"
    }

    for skill_id, skill in installed.items():
        subentry_id, title = subentry_by_skill.get(skill_id, (None, skill_id))
        entities = [
            OvosSkillVersionSensor(
                subentry_id or skill_id, skill_id, title, skill.get("version"),
                config_tool_url,
            )
        ]
        if subentry_id:
            add_entities(entities, config_subentry_id=subentry_id)
        else:
            add_entities(entities)


class OvosSkillVersionSensor(SensorEntity):
    """Exists mainly to give the skill its own device (name + model-line
    subtitle in the device list) via device_info -- the entity's own
    state (installed version) is secondary to that; see module docstring.
    """

    _attr_has_entity_name = True
    _attr_name = "Installed version"
    _attr_icon = "mdi:puzzle"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        unique_id_prefix: str,
        skill_id: str,
        name: str,
        version: str | None,
        config_tool_url: str | None = None,
    ) -> None:
        self._attr_unique_id = f"{unique_id_prefix}_version"
        self._attr_native_value = version or "unknown"
        # configuration_url, when set, renders as a native "Visit" link
        # on this device's own page -- HA's own escape-hatch mechanism
        # for "more settings live outside this integration", used here
        # to point at a self-hosted ovos-skill-config-tool instance
        # (see const.py's CONF_SKILL_CONFIG_TOOL_URL) rather than
        # building a bespoke button entity for the same purpose.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, skill_id)},
            name=name,
            manufacturer="OpenVoiceOS",
            model=skill_id,
            sw_version=version,
            configuration_url=config_tool_url,
        )
