"""Volume (#10): mycroft.volume.set / mycroft.volume.get."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE

from . import panel_entities
from .bus import CAP_VOLUME, OvosDevice
from .entity import OvosDeviceEntity, setup_capabilities
from .panel import CAP_PANEL


async def async_setup_entry(hass, entry, add_entities):
    def factory(device: OvosDevice, cap: str) -> list:
        if cap == CAP_PANEL:
            # skills' number settings (#15)
            panel_entities.setup_skill_settings(device, add_entities, "number")
            return []
        return [OvosVolume(device)] if cap == CAP_VOLUME else []
    setup_capabilities(hass, entry, add_entities, factory)


class OvosVolume(OvosDeviceEntity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, device: OvosDevice) -> None:
        super().__init__(device, "volume")

    @property
    def native_value(self) -> float | None:
        return None if self.device.volume is None else round(self.device.volume * 100)

    async def async_set_native_value(self, value: float) -> None:
        # play_sound: false -- no "blop" when an automation sets it at night
        self.device.send("mycroft.volume.set", {"percent": value / 100, "play_sound": False})
        self.device.volume = value / 100
        self.async_write_ha_state()
