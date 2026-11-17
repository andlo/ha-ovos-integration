"""Say something (#10): notify.send_message -> the device's `speak`."""
from __future__ import annotations

from homeassistant.components.notify import NotifyEntity

from .bus import OvosDevice
from .entity import CAP_BASE, OvosDeviceEntity, setup_capabilities


async def async_setup_entry(hass, entry, add_entities):
    setup_capabilities(hass, entry, add_entities, lambda device, cap:
                       [OvosSay(device)] if cap == CAP_BASE else [])


class OvosSay(OvosDeviceEntity, NotifyEntity):
    def __init__(self, device: OvosDevice) -> None:
        super().__init__(device, "say")

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        data = {"utterance": message}
        if lang := self.device.info.get("lang"):
            data["lang"] = lang
        self.device.send("speak", data)
