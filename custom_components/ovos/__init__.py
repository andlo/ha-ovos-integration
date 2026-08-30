"""The OpenVoiceOS shared config integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import label_registry as lr

from .const import (
    DOMAIN,
    CORE_SETTINGS_DEVICE_ID,
    PERSONA_DEVICE_ID,
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
from .persona_coordinator import OvosPersonaCoordinator
from .shared_config import write_shared_config_key
from .skill_settings import fetch_catalog_names, get_skills_api_url, prettify_skill_id
from .skill_settings_coordinator import OvosSkillSettingsCoordinator
from .supervisor_discovery import async_discover_addon_api_urls

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["text", "number", "select", "sensor", "switch", "binary_sensor", "button", "conversation"]


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

    # See const.py's own CORE_SETTINGS_DEVICE_ID comment for why this
    # subentry/device exists at all: a real, reported gap where these
    # entities had nowhere to show up as a group, buried under HA's
    # own generic "devices not belonging to a subentry" heading.
    # Auto-created exactly once -- same "does one already exist"
    # guard skill subentries don't need (they're keyed by skill_id,
    # naturally idempotent per skill) but this singleton needs
    # explicitly, since nothing else naturally prevents creating a
    # second one on every restart. Same SOURCE_USER-required mechanism
    # skill_subentry.py's own auto-import path already documents.
    core_settings_subentry_id = next(
        (
            subentry_id for subentry_id, subentry in entry.subentries.items()
            if subentry.subentry_type == "core_settings"
        ),
        None,
    )
    if core_settings_subentry_id is None:
        await hass.config_entries.subentries.async_init(
            (entry.entry_id, "core_settings"),
            context={"source": "user"},
            data={},
        )
        # Re-scan rather than pull an id out of the flow result directly
        # -- confirmed the hard way (a real KeyError: 'subentry_id' on
        # an actual Home Assistant instance) that the exact result shape
        # isn't what was assumed. entry.subentries is refreshed in place
        # by async_init itself (same object skill_subentry.py's own
        # already-working lookups rely on elsewhere in this file), so
        # this same "does one already exist" scan above is a robust
        # way to get the id back regardless of the flow result's own
        # exact structure.
        core_settings_subentry_id = next(
            subentry_id for subentry_id, subentry in entry.subentries.items()
            if subentry.subentry_type == "core_settings"
        )

    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        config_subentry_id=core_settings_subentry_id,
        identifiers={(DOMAIN, CORE_SETTINGS_DEVICE_ID)},
        name="OpenVoiceOS Core Settings",
        manufacturer="OpenVoiceOS",
        model="ovos-core",
    )
    hass.data[DOMAIN][f"{entry.entry_id}_core_settings_subentry"] = core_settings_subentry_id

    # Same pattern again, for the device grouping ovos-persona's own
    # live entities (solver list, reachability, fallback-skill button)
    # -- replaces the old one-off persona_subentry.py flow, see
    # const.py's own PERSONA_DEVICE_ID comment for the full reasoning.
    persona_subentry_id = next(
        (
            subentry_id for subentry_id, subentry in entry.subentries.items()
            if subentry.subentry_type == "persona"
        ),
        None,
    )
    if persona_subentry_id is None:
        await hass.config_entries.subentries.async_init(
            (entry.entry_id, "persona"),
            context={"source": "user"},
            data={},
        )
        persona_subentry_id = next(
            subentry_id for subentry_id, subentry in entry.subentries.items()
            if subentry.subentry_type == "persona"
        )

    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        config_subentry_id=persona_subentry_id,
        identifiers={(DOMAIN, PERSONA_DEVICE_ID)},
        name="OpenVoiceOS Persona",
        manufacturer="OpenVoiceOS",
        model="ovos-persona",
    )
    hass.data[DOMAIN][f"{entry.entry_id}_persona_subentry"] = persona_subentry_id

    persona_coordinator = OvosPersonaCoordinator(hass)
    await persona_coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][f"{entry.entry_id}_persona"] = persona_coordinator

    # Separate coordinator for per-skill settings (issue #3) -- polls
    # each installed skill's own add-on API, not the shared mycroft.conf,
    # so it's stored under its own key rather than overloading the
    # existing entry.entry_id one every other platform already assumes
    # is the shared-config coordinator.
    skill_settings_coordinator = OvosSkillSettingsCoordinator(hass, entry)
    await skill_settings_coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][f"{entry.entry_id}_skill_settings"] = skill_settings_coordinator

    await _async_create_missing_skill_subentries(hass, entry, skill_settings_coordinator)
    await _async_label_skill_devices(hass, entry, skill_settings_coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


SKILL_LABEL_NAME = "OVOS Skill"


async def _async_ensure_skill_label(hass: HomeAssistant) -> str:
    """Real, reported ask: filtering skill devices together elsewhere in
    HA (Settings -> Devices, filtered by label) since the integration's
    own page can't group them under a shared umbrella (subentries don't
    nest, and MQTT's own docs confirm "each subentry holds one device"
    is the intended pattern this project's own skill subentries already
    follow -- see DEVELOPER.md).

    label_registry.async_create raises ValueError if a label with this
    name already exists -- confirmed by reading its own source directly,
    unlike device_registry's own idempotent async_get_or_create -- so
    this checks async_get_label_by_name first, same "does it already
    exist" guard core_settings_subentry_id above already needs for the
    same underlying reason (this runs on every restart, not just once).
    """
    registry = lr.async_get(hass)
    label = registry.async_get_label_by_name(SKILL_LABEL_NAME)
    if label is None:
        label = registry.async_create(
            SKILL_LABEL_NAME, icon="mdi:puzzle", description="An installed OVOS skill"
        )
    return label.label_id


async def _async_label_skill_devices(
    hass: HomeAssistant, entry: ConfigEntry, skill_settings_coordinator: OvosSkillSettingsCoordinator,
) -> None:
    """Applies the OVOS Skill label to every currently-known skill's own
    device. device_registry.async_get_or_create has no labels parameter
    at all -- confirmed by reading its own signature directly -- so this
    is necessarily a separate async_update_device call per device,
    using the device's own real device_id (not its identifiers tuple).
    Not passing config_subentry_id to the async_get_or_create call
    below is deliberate: that parameter defaults to UNDEFINED (leave
    unchanged), so this can't accidentally move a device that already
    has a real subentry into a different one -- same "moves the
    device" warning already seen and understood elsewhere in this
    project (see DEVELOPER.md) is not a risk here, since nothing here
    ever passes a subentry id at all.
    """
    label_id = await _async_ensure_skill_label(hass)
    device_registry = dr.async_get(hass)
    for skill_id in skill_settings_coordinator.data:
        device = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, skill_id)},
        )
        if label_id not in device.labels:
            device_registry.async_update_device(device.id, labels=device.labels | {label_id})


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

    # Retroactive fix, once: a subentry whose own title is still
    # exactly what auto-creation would have produced before this
    # integration's own skill.get("name") fallback existed -- either
    # the raw skill_id itself, or prettify_skill_id's own crude guess
    # -- never got a real name. Confirmed both cases happen for real:
    # a skill installed directly against an add-on's own API sometimes
    # ends up with the bare skill_id as its title, other times with
    # prettify_skill_id's guess, depending on which code path created
    # it. Only retitles those two exact "never really set" cases, never
    # touches any other title -- including one a person may have
    # deliberately renamed to something else, which this must not
    # overwrite.
    for subentry_id, subentry in list(entry.subentries.items()):
        if subentry.subentry_type != "skill":
            continue
        skill_id = subentry.data.get("skill_id")
        skill = skill_settings_coordinator.data.get(skill_id)
        if not skill or subentry.title not in (skill_id, prettify_skill_id(skill_id)):
            continue
        better_title = catalog_names.get(skill_id) or skill.get("name")
        if better_title and better_title != subentry.title:
            hass.config_entries.async_update_subentry(entry, subentry, title=better_title)

    for skill_id, skill in skill_settings_coordinator.data.items():
        if skill_id in existing_skill_ids:
            continue
        # skill.get("name") -- the add-on's own /skills response now
        # includes this when the skill ships a skill.json (see
        # sensor.py's own comment on the same fallback for its device
        # naming). Placed here too so a skill auto-subentried for the
        # first time gets a real name as its subentry's own title
        # immediately, not just prettify_skill_id's crude guess.
        title = catalog_names.get(skill_id) or skill.get("name") or prettify_skill_id(skill_id)
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
