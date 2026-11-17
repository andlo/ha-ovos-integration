"""Buttons (#10): listen now, stop."""
from __future__ import annotations

from .bus import OvosDevice
from .entity import CAP_BASE, OvosDeviceEntity, setup_capabilities
from homeassistant.components.button import ButtonEntity


async def async_setup_entry(hass, entry, add_entities):
    setup_capabilities(hass, entry, add_entities, lambda device, cap:
                       [OvosBusButton(device, "listen", "mycroft.mic.listen"),
                        OvosBusButton(device, "stop", "mycroft.stop")]
                       if cap == CAP_BASE else [])


class OvosBusButton(OvosDeviceEntity, ButtonEntity):
    def __init__(self, device: OvosDevice, key: str, msg_type: str) -> None:
        super().__init__(device, key)
        self._msg_type = msg_type

    async def async_press(self) -> None:
        self.device.send(self._msg_type)
