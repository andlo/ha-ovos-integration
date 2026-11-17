"""The pipeline and "finished speaking" sensitivity for a satellite (#11):
HA's own select entities, as ESPHome and Wyoming satellites have them."""
from __future__ import annotations

from homeassistant.components.assist_pipeline import AssistPipelineSelect, VadSensitivitySelect
from homeassistant.helpers.device_registry import DeviceInfo

from ..const import DOMAIN
from .assist_satellite import CAP_SATELLITE
from .bus import OvosDevice
from .entity import setup_capabilities


async def async_setup_entry(hass, entry, add_entities):
    def factory(device: OvosDevice, cap: str):
        if cap != CAP_SATELLITE:
            return []
        info = DeviceInfo(identifiers={(DOMAIN, device.device_id)})
        pipeline = AssistPipelineSelect(hass, DOMAIN, device.device_id)
        vad = VadSensitivitySelect(hass, device.device_id)
        for e in (pipeline, vad):
            # named from their translation_key ("Assistant", "Finished
            # speaking detection"), under the device's name
            e._attr_has_entity_name = True
            e._attr_device_info = info
        return [pipeline, vad]
    setup_capabilities(hass, entry, add_entities, factory)
