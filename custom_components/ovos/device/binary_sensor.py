"""The device's own binary sensors (#10), from ovos.phal.binary_sensor."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity

from .entity import setup_capabilities
from .sensor import OvosPhalSensorBase


async def async_setup_entry(hass, entry, add_entities):
    def factory(device, cap):
        if cap.startswith("sensor:"):
            sid = cap.removeprefix("sensor:")
            if device.sensors.get(sid, {}).get("binary"):
                return [OvosPhalBinarySensor(device, sid)]
        return []
    setup_capabilities(hass, entry, add_entities, factory)


class OvosPhalBinarySensor(OvosPhalSensorBase, BinarySensorEntity):
    @property
    def is_on(self) -> bool | None:
        state = self._sensor.get("state")
        if state is None:
            return None
        if isinstance(state, str):
            return state.lower() in ("on", "true", "1", "yes", "open", "detected")
        return bool(state)
