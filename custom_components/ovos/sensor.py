"""One sensor entity per installed skill, giving each skill its own
device in HA's device registry -- raised directly by comparing this
integration's subentry list to another integration's proper device
list (name + a model-line subtitle, expandable, not a bare title).

Confirmed this is a genuine, modern HA mechanism, not a workaround:
config subentries can own devices (home-assistant/core PR #128157,
"Add config subentry support to device registry"), and entities create
their device automatically via their own device_info, same as any other
integration -- the only new part is passing config_subentry_id to
async_add_entities so the device is correctly scoped to that specific
skill subentry, not the shared config entry as a whole.

A first cut, deliberately narrow: one read-only sensor (installed
version) per skill, mainly to give the device something to attach to.
Turning each skill's own settings into real, always-visible entities
here (instead of the current one-off "reconfigure" flow) is a separate,
larger piece of work, not attempted in this pass.
"""
from __future__ import annotations

import requests
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN, CONF_SKILLS_API_URL, CONF_SKILL_CONFIG_TOOL_URL
from .shared_config import read_shared_config

REQUEST_TIMEOUT = 10


def _get_skills_api_url() -> str | None:
    return read_shared_config().get(CONF_SKILLS_API_URL) or None


def _fetch_installed_versions(api_url: str) -> dict[str, str]:
    """skill_id -> installed version, from ovos-skills' own /skills
    endpoint. Keyed by skill_id, not package_name -- ovos-skills now
    installs each skill into its own isolated venv and tracks the
    confirmed-real skill_id/package_name pair directly in its manifest
    (see its api.py), so this is an exact, reliable match rather than
    the earlier fuzzy-matching-needed guess. Best-effort still: a
    failure here just means the sensor shows "unknown" rather than
    blocking the device from existing at all.
    """
    try:
        resp = requests.get(f"{api_url}/skills", timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return {s["skill_id"]: s["version"] for s in resp.json().get("skills", [])}
    except requests.RequestException:
        return {}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities):
    api_url = await hass.async_add_executor_job(_get_skills_api_url)
    versions = (
        await hass.async_add_executor_job(_fetch_installed_versions, api_url)
        if api_url else {}
    )
    config_tool_url = await hass.async_add_executor_job(
        lambda: read_shared_config().get(CONF_SKILL_CONFIG_TOOL_URL) or None
    )

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != "skill":
            continue
        skill_id = subentry.data["skill_id"]
        add_entities(
            [
                OvosSkillVersionSensor(
                    subentry_id, skill_id, subentry.title, versions.get(skill_id),
                    config_tool_url,
                )
            ],
            config_subentry_id=subentry_id,
        )


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
        subentry_id: str,
        skill_id: str,
        name: str,
        version: str | None,
        config_tool_url: str | None = None,
    ) -> None:
        self._attr_unique_id = f"{subentry_id}_version"
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
