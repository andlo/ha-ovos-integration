"""One sensor entity per installed skill, giving each skill its own
device in HA's device registry -- raised directly by comparing this
integration's subentry list to another integration's proper device
list (name + a model-line subtitle, expandable, not a bare title).

Discovers skills directly from each configured add-on's own /skills
list (curated ovos-skills and ovos-skills-extra, whichever have an API
URL set -- NOT assumed to both exist), NOT only from subentries -- a
skill installed directly against an add-on's API, outside this
integration's "Add sub-entry" flow, still gets its own device this way
(see skill_settings_coordinator.py's own docstring for the same
reasoning, shared by the live settings entities).

Display name priority: a subentry's own title (set at install time from
the curated catalog, or the confirmed-real skill_id for an extra
install) when one exists, otherwise a fresh catalog lookup (curated
skills only -- ovos-skills-extra has no catalog by design), otherwise
skill_settings.prettify_skill_id's best-effort cleanup of the raw
skill_id.

Grouping by source add-on: since Home Assistant has no supported way to
create a config subentry outside of a subentry flow (confirmed via
community.home-assistant.io's own "Are there methods like
async_setup_entry for a Config Subentry?" thread -- no lifecycle hooks,
no documented programmatic creation), the subentry-based header
grouping seen for skills added through this integration's own flow
isn't reproducible for skills discovered this way. Per that same
thread's own suggestion ("Using devices... seem to be able to do the
same role of having multiple children for a given config entry"), each
skill device instead sets `via_device` to a small, entity-less "hub"
device for whichever add-on it came from -- shows as "Connected via
device" on the skill's own page and nests it under that hub on the
Devices list, the closest supported equivalent. A hub is only ever
created for an add-on that's actually configured (has an API URL) AND
has at least one skill installed -- never an empty or unreachable one.

ovos-core is NOT one of the hubs here: it has no /skills-equivalent
endpoint to enumerate its own plugin skills (e.g. ovos-skill-boot-
finished) at all yet -- would need a companion change to
haos-ovos-addons' ovos-core/api.py first, not attempted in this pass.

Confirmed subentries owning devices is a genuine, modern HA mechanism,
not a workaround, for the case where one DOES exist (home-assistant/
core PR #128157, "Add config subentry support to device registry").
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN, CONF_SKILL_CONFIG_TOOL_URL
from .shared_config import read_shared_config
from .skill_settings import (
    get_skills_api_url,
    get_skills_extra_api_url,
    list_installed_skills,
    fetch_catalog_names,
    prettify_skill_id,
)

# Stable identifiers for the two possible hub devices -- not user data,
# safe as literal identifier strings.
HUB_SKILLS = "hub_skills"
HUB_SKILLS_EXTRA = "hub_skills_extra"


def _fetch_all_installed_skills() -> dict[str, dict]:
    """skill_id -> {"version", "source_type", ...}, tagged with which
    add-on it came from ("curated"/"extra") so the right hub and the
    right (curated-only) catalog name lookup can be used per skill.
    Best-effort per add-on: an unreachable/unconfigured one just
    contributes nothing rather than blocking the other's skills.
    """
    skills: dict[str, dict] = {}
    curated_url = get_skills_api_url()
    extra_url = get_skills_extra_api_url()
    for api_url, source_type in ((curated_url, "curated"), (extra_url, "extra")):
        if not api_url:
            continue
        for skill in list_installed_skills(api_url):
            skill_id = skill.get("skill_id")
            if skill_id and skill_id not in skills:
                skills[skill_id] = {**skill, "source_type": source_type}
    return skills


def _ensure_hub_device(hass: HomeAssistant, entry: ConfigEntry, source_type: str) -> tuple:
    """Explicitly registers a hub device via the device registry directly
    -- NOT by relying on some entity's own DeviceInfo as a side effect,
    since no entity here belongs to the hub itself. This is exactly the
    "devices (even ones without entities)" mechanism the community
    thread referenced in this module's own docstring points at. Returns
    the (DOMAIN, identifier) tuple to use as a child device's via_device.
    """
    identifier = HUB_SKILLS if source_type == "curated" else HUB_SKILLS_EXTRA
    name = "OVOS Skills" if source_type == "curated" else "OVOS Skills Extra"
    model = "ovos-skills" if source_type == "curated" else "ovos-skills-extra"
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, identifier)},
        name=name,
        manufacturer="OpenVoiceOS",
        model=model,
    )
    return (DOMAIN, identifier)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities):
    installed = await hass.async_add_executor_job(_fetch_all_installed_skills)
    config_tool_url = await hass.async_add_executor_job(
        lambda: read_shared_config().get(CONF_SKILL_CONFIG_TOOL_URL) or None
    )
    curated_url = await hass.async_add_executor_job(get_skills_api_url)
    catalog_names = (
        await hass.async_add_executor_job(fetch_catalog_names, curated_url)
        if curated_url else {}
    )

    subentry_by_skill = {
        subentry.data["skill_id"]: (subentry_id, subentry.title)
        for subentry_id, subentry in entry.subentries.items()
        if subentry.subentry_type == "skill"
    }

    # A hub is created the first time a skill from that source_type is
    # seen -- never upfront/unconditionally, so a configured-but-empty
    # or unconfigured add-on never gets a hub device with nothing under it.
    hub_via_device: dict[str, tuple] = {}

    for skill_id, skill in installed.items():
        subentry_id, subentry_title = subentry_by_skill.get(skill_id, (None, None))
        name = subentry_title or catalog_names.get(skill_id) or prettify_skill_id(skill_id)

        source_type = skill["source_type"]
        if source_type not in hub_via_device:
            hub_via_device[source_type] = _ensure_hub_device(hass, entry, source_type)

        entities = [
            OvosSkillVersionSensor(
                subentry_id or skill_id, skill_id, name, skill.get("version"),
                config_tool_url, hub_via_device[source_type],
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
        config_tool_url: str | None,
        via_device: tuple | None,
    ) -> None:
        self._attr_unique_id = f"{unique_id_prefix}_version"
        self._attr_native_value = version or "unknown"
        # configuration_url, when set, renders as a native "Visit" link
        # on this device's own page -- HA's own escape-hatch mechanism
        # for "more settings live outside this integration", used here
        # to point at a self-hosted ovos-skill-config-tool instance
        # (see const.py's CONF_SKILL_CONFIG_TOOL_URL) rather than
        # building a bespoke button entity for the same purpose.
        # via_device groups this skill under its source add-on's own
        # hub device -- see module docstring for why this, not a
        # subentry, is used for that grouping here.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, skill_id)},
            name=name,
            manufacturer="OpenVoiceOS",
            model=skill_id,
            sw_version=version,
            configuration_url=config_tool_url,
            via_device=via_device,
        )
