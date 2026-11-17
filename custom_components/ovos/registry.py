"""Device registry lookups that work before and after HA 2026.11.

2026.11 deprecated device_registry.async_get_device (identifiers are no
longer unique across config entries) in favour of
async_get_device_by_identifier(identifier, config_entry_id), which older
versions don't have.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr


def get_device(hass: HomeAssistant, identifier: tuple[str, str],
               config_entry_id: str) -> dr.DeviceEntry | None:
    registry = dr.async_get(hass)
    if hasattr(registry, "async_get_device_by_identifier"):
        return registry.async_get_device_by_identifier(identifier, config_entry_id)
    return registry.async_get_device(identifiers={identifier})
