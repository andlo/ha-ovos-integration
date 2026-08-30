"""Persona reachability, as a diagnostic binary sensor -- see
persona_coordinator.py's own docstring for why "not reachable" is a
normal state here, not an error. The status half of the "entity for
data, button for the one-off action, sensor for status, no flow left"
design agreed for ovos-persona (see const.py's own PERSONA_DEVICE_ID
comment; persona_subentry.py, the old one-off "Add sub-entry" flow
this replaces, is removed).
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PERSONA_DEVICE_ID
from .persona_coordinator import OvosPersonaCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities):
    coordinator: OvosPersonaCoordinator = hass.data[DOMAIN][f"{entry.entry_id}_persona"]
    persona_subentry_id = hass.data[DOMAIN][f"{entry.entry_id}_persona_subentry"]
    add_entities(
        [OvosPersonaReachableBinarySensor(coordinator, entry)],
        config_subentry_id=persona_subentry_id,
    )


class OvosPersonaReachableBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """On when ovos-persona's own /health reports bus_connected -- off
    both when it's unreachable AND when CONF_PERSONA_API_URL isn't set
    at all (see persona_coordinator.py's own "configured" vs
    "reachable" distinction) -- either way, "not currently usable" is
    the one thing this sensor needs to convey.
    """

    _attr_has_entity_name = True
    _attr_name = "Persona reachable"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_info = DeviceInfo(identifiers={(DOMAIN, PERSONA_DEVICE_ID)})

    def __init__(self, coordinator: OvosPersonaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_persona_reachable"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("reachable", False))
