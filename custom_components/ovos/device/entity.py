"""Shared base for a device's entities, and how they appear as the device
turns out to have more capabilities (bus.py's probe)."""
from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from ..const import DOMAIN, SIGNAL_NEW_CAPABILITY
from .bus import OvosDevice

# Pseudo-capability every device has: what only needs a bus
CAP_BASE = "base"


class OvosDeviceEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: OvosDevice, key: str) -> None:
        self.device = device
        self._attr_unique_id = f"{device.device_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device.device_id)})

    @property
    def available(self) -> bool:
        return self.device.available

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.device.add_update_listener(self.async_write_ha_state))


def setup_capabilities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    add_entities: Callable[[Iterable[Entity]], None],
    factory: Callable[[OvosDevice, str], list[Entity]],
) -> None:
    """Add the platform's entities for every capability the device has --
    known now, and found later while it is connected."""
    device: OvosDevice = entry.runtime_data
    added: set[str] = set()

    @callback
    def add(capability: str) -> None:
        if capability in added:
            return
        entities = factory(device, capability)
        if entities:
            added.add(capability)
            add_entities(entities)

    for capability in [CAP_BASE, *sorted(device.capabilities),
                       *(f"sensor:{sid}" for sid in device.sensors)]:
        add(capability)
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_NEW_CAPABILITY.format(entry.entry_id), add)
    )
