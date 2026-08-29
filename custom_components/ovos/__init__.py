"""The OpenVoiceOS shared config integration."""
from __future__ import annotations

import logging

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
from .skill_settings import fetch_catalog_names, get_skills_api_url, prettify_skill_id
from .skill_settings_coordinator import OvosSkillSettingsCoordinator
from .supervisor_discovery import async_discover_addon_api_urls

_LOGGER = logging.getLogger(__name__)

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

    await _async_create_missing_skill_subentries(hass, entry, skill_settings_coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_create_missing_skill_subentries(
    hass: HomeAssistant, entry: ConfigEntry, skill_settings_coordinator: OvosSkillSettingsCoordinator,
) -> None:
    """Auto-create a real "skill" subentry for every skill the settings
    coordinator found installed (via each add-on's own /skills list)
    that doesn't already have one -- uses the SOURCE_IMPORT-style
    pattern (skill_subentry.py's async_step_import) HA's own
    auto-discovery flows use for "found this automatically, nothing to
    ask the person about" entries. Confirmed viable by reading this
    HA version's own config_entries.py directly: ConfigSubentryFlowManager
    extends the same FlowManager base the regular config-flow manager
    does, so async_init works the same way, just keyed by
    (entry_id, subentry_type) instead of a domain string.

    Gives every skill this integration discovers the same header-grouped
    placement on its own integration page that a skill added through
    "Add sub-entry -> Skill" already gets, instead of leaving it
    permanently in the ungrouped "devices not belonging to a subentry"
    section -- confirmed genuinely confusing there in practice, not
    just a style preference (see git history for the fuller reasoning
    and the hub-device fallback this doesn't remove, kept as a safety
    net for anything reached before this runs).

    Best-effort per skill: one failing/erroring doesn't stop the rest.
    """
    existing_skill_ids = {
        subentry.data["skill_id"]
        for subentry in entry.subentries.values()
        if subentry.subentry_type == "skill"
    }

    curated_url = await hass.async_add_executor_job(get_skills_api_url)
    catalog_names = (
        await hass.async_add_executor_job(fetch_catalog_names, curated_url)
        if curated_url else {}
    )

    for skill_id, skill in skill_settings_coordinator.data.items():
        if skill_id in existing_skill_ids:
            continue
        title = catalog_names.get(skill_id) or prettify_skill_id(skill_id)
        try:
            await hass.config_entries.subentries.async_init(
                (entry.entry_id, "skill"),
                context={"source": "user"},
                data={
                    "skill_id": skill_id,
                    "source": skill.get("source", ""),
                    "package_name": skill.get("package_name", ""),
                    "source_type": skill.get("source_type", "curated"),
                    "title": title,
                },
            )
        except Exception:  # noqa: BLE001 -- best-effort, see docstring
            _LOGGER.exception(
                "Failed to auto-create a subentry for skill %s", skill_id
            )
            continue


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        hass.data[DOMAIN].pop(f"{entry.entry_id}_skill_settings", None)
    return unloaded
