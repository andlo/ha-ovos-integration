"""General OVOS devices (issue #7): one config entry per OpenVoiceOS device.

The add-on entry (haos-ovos-addons' shared config) is set up in the
integration's own __init__.py as before; device entries are set up here.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from ..const import (
    CONF_DEVICE_ID,
    CONF_MANUFACTURER,
    CONF_MODEL,
    CONF_SW_VERSION,
    DATA_DEVICES,
    DATA_INBOUND_HUB,
    DOMAIN,
)
from .bus import OvosDevice

DEVICE_PLATFORMS = ["assist_satellite", "binary_sensor", "button", "notify", "number", "select", "sensor", "switch"]


async def async_setup_device_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    device = OvosDevice(hass, entry)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device.device_id)},
        name=entry.title,
        manufacturer=entry.data.get(CONF_MANUFACTURER) or "OpenVoiceOS",
        model=entry.data.get(CONF_MODEL) or "OpenVoiceOS",
        sw_version=entry.data.get(CONF_SW_VERSION),
    )
    hass.data[DOMAIN][DATA_DEVICES][device.device_id] = device
    entry.runtime_data = device
    await hass.config_entries.async_forward_entry_setups(entry, DEVICE_PLATFORMS)
    # a device that is already connected (it waited while the entry was
    # accepted, or across a reload) is paired now
    hass.data[DOMAIN][DATA_INBOUND_HUB].try_attach(device.device_id)
    return True


async def async_unload_device_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, DEVICE_PLATFORMS)
    if unloaded:
        device_id = entry.data[CONF_DEVICE_ID]
        device: OvosDevice | None = hass.data[DOMAIN][DATA_DEVICES].pop(device_id, None)
        if device is not None:
            device.detach()
        hass.data[DOMAIN][DATA_INBOUND_HUB].device_unloaded(device_id)
    return unloaded


async def async_remove_device_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    hub = hass.data.get(DOMAIN, {}).get(DATA_INBOUND_HUB)
    if hub is not None:
        hub.device_removed(entry.data[CONF_DEVICE_ID])
