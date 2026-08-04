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
from .shared_config import write_shared_config_key

PLATFORMS = ["text", "number", "select"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.data

    def _write_initial() -> None:
        write_shared_config_key(CONF_LANG, entry.data[CONF_LANG])
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
        write_shared_config_key(CONF_SYSTEM_UNIT, entry.data[CONF_SYSTEM_UNIT])

    await hass.async_add_executor_job(_write_initial)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
