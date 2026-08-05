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
)
from .coordinator import OvosSharedConfigCoordinator
from .shared_config import write_shared_config_key

PLATFORMS = ["text", "number", "select", "sensor", "conversation"]


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
    if seeded:
        await coordinator.async_request_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
