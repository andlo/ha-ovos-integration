"""The OpenVoiceOS shared config integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    CONF_LANG,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_TIMEZONE,
    CONF_SYSTEM_UNIT,
    CONF_CORE_API_URL,
    CONF_SKILLS_API_URL,
    CONF_PERSONA_API_URL,
    CONF_SKILLS_EXTRA_API_URL,
)
from .coordinator import OvosSharedConfigCoordinator
from .shared_config import write_shared_config_key
from .skill_settings_coordinator import OvosSkillSettingsCoordinator
from .supervisor_discovery import async_discover_addon_api_urls

PLATFORMS = ["text", "number", "select", "sensor", "switch", "conversation"]


def _seed_missing_keys(current: dict, entry: ConfigEntry) -> bool:
    """Write config-flow values into the shared file, but only for keys
    that genuinely aren't there yet — never clobber a value someone (or
    another add-on) already wrote, including on integration reload.
    """
    changed = False
    if CONF_LANG not in current:
        write_shared_config_key(CONF_LANG, entry.data[CONF_LANG])
        changed = True
    if "location" not in current:
        write_shared_config_key(
            "location",
            {
                "coordinate": {
                    "latitude": entry.data[CONF_LATITUDE],
                    "longitude": entry.data[CONF_LONGITUDE],
                },
                "timezone": {"code": entry.data[CONF_TIMEZONE]},
            },
        )
        changed = True
    if CONF_SYSTEM_UNIT not in current:
        write_shared_config_key(CONF_SYSTEM_UNIT, entry.data[CONF_SYSTEM_UNIT])
        changed = True
    return changed


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = OvosSharedConfigCoordinator(hass)
    await coordinator.async_config_entry_first_refresh()

    seeded = await hass.async_add_executor_job(
        _seed_missing_keys, coordinator.data, entry
    )

    # Auto-discover add-on API URLs via Supervisor -- see
    # supervisor_discovery.py and issue #4. Checked against
    # coordinator.data as it stood right after the first refresh above,
    # before any of this function's own writes -- only ever fills in a
    # key that's genuinely still empty, never overwrites a manually
    # entered value or something another add-on already wrote.
    missing_url_keys = [
        key for key in (
            CONF_CORE_API_URL, CONF_SKILLS_API_URL,
            CONF_PERSONA_API_URL, CONF_SKILLS_EXTRA_API_URL,
        )
        if not coordinator.data.get(key)
    ]
    if missing_url_keys:
        discovered = await async_discover_addon_api_urls(hass)
        for key in missing_url_keys:
            if key in discovered:
                await hass.async_add_executor_job(
                    write_shared_config_key, key, discovered[key]
                )
                seeded = True

    if seeded:
        await coordinator.async_request_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Separate coordinator for per-skill settings (issue #3) -- polls
    # each installed skill's own add-on API, not the shared mycroft.conf,
    # so it's stored under its own key rather than overloading the
    # existing entry.entry_id one every other platform already assumes
    # is the shared-config coordinator.
    skill_settings_coordinator = OvosSkillSettingsCoordinator(hass, entry)
    await skill_settings_coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][f"{entry.entry_id}_skill_settings"] = skill_settings_coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        hass.data[DOMAIN].pop(f"{entry.entry_id}_skill_settings", None)
    return unloaded
