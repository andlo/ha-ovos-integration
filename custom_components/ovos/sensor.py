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

from .const import DOMAIN, CONF_SKILLS_API_URL
from .shared_config import read_shared_config

REQUEST_TIMEOUT = 10


def _get_skills_api_url() -> str | None:
    return read_shared_config().get(CONF_SKILLS_API_URL) or None


def _fetch_installed_versions(api_url: str) -> dict[str, str]:
    """package_name -> installed version, from ovos-skills' own /skills
    endpoint (a pip list under the hood). Best-effort in two ways: (1) a
    failure here just means the sensor shows "unknown" rather than
    blocking the device from existing at all; (2) exact-match only --
    the catalog's package_name doesn't always match the real installed
    name 1:1 (confirmed elsewhere in this project, e.g.
    skill-ovos-fallback-chatgpt installs under a different name than its
    own catalog entry says), so some correctly-installed skills will
    still show "unknown" here. Same fuzzy-match fallback ovos-skills'
    own api.py already uses internally (_find_installed_package) would
    fix this properly -- not pulled in here yet, left for a follow-up
    that exposes it as its own endpoint rather than duplicating the
    matching logic in two repos.
    """
    try:
        resp = requests.get(f"{api_url}/skills", timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return {s["name"]: s["version"] for s in resp.json().get("skills", [])}
    except requests.RequestException:
        return {}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities):
    api_url = await hass.async_add_executor_job(_get_skills_api_url)
    versions = (
        await hass.async_add_executor_job(_fetch_installed_versions, api_url)
        if api_url else {}
    )

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != "skill":
            continue
        skill_id = subentry.data["skill_id"]
        package_name = subentry.data.get("package_name", "")
        add_entities(
            [
                OvosSkillVersionSensor(
                    subentry_id, skill_id, subentry.title, versions.get(package_name)
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
        self, subentry_id: str, skill_id: str, name: str, version: str | None
    ) -> None:
        self._attr_unique_id = f"{subentry_id}_version"
        self._attr_native_value = version or "unknown"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, skill_id)},
            name=name,
            manufacturer="OpenVoiceOS",
            model=skill_id,
            sw_version=version,
        )
