"""Actions for OVOS devices (issue #10): ask something, send a bus message.

"Say something" is the device's notify entity (notify.send_message).
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DATA_DEVICES, DOMAIN

ATTR_DEVICE_ID = "device_id"


def _devices(hass: HomeAssistant, call: ServiceCall) -> list:
    registry = dr.async_get(hass)
    found = []
    for ha_device_id in call.data[ATTR_DEVICE_ID]:
        ha_device = registry.async_get(ha_device_id)
        ovos_id = next((i for d, i in ha_device.identifiers if d == DOMAIN), None) if ha_device else None
        device = hass.data[DOMAIN][DATA_DEVICES].get(ovos_id)
        if device is None:
            raise ServiceValidationError(f"{ha_device_id} is not an OpenVoiceOS device")
        if not device.available:
            raise HomeAssistantError(f"{ha_device.name_by_user or ha_device.name} is not connected")
        found.append(device)
    return found


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def ask(call: ServiceCall) -> None:
        for device in _devices(hass, call):
            data = {"utterances": [call.data["utterance"]]}
            if lang := call.data.get("lang") or device.info.get("lang"):
                data["lang"] = lang
            device.send("recognizer_loop:utterance", data)

    async def send_message(call: ServiceCall) -> None:
        for device in _devices(hass, call):
            device.send(call.data["type"], call.data.get("data") or {})

    devices = vol.All(cv.ensure_list, [cv.string])
    hass.services.async_register(DOMAIN, "ask", ask, schema=vol.Schema({
        vol.Required(ATTR_DEVICE_ID): devices,
        vol.Required("utterance"): cv.string,
        vol.Optional("lang"): cv.string,
    }))
    hass.services.async_register(DOMAIN, "send_message", send_message, schema=vol.Schema({
        vol.Required(ATTR_DEVICE_ID): devices,
        vol.Required("type"): cv.string,
        vol.Optional("data"): dict,
    }))
