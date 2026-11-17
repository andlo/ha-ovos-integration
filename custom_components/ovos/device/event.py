"""The network log (#16): every request a device makes, as an event.

From ovos.network.request -- one bus message per request, with the same
fields as a line of Emkay's network log (never the path, query or body).
The event type is what kind of service it was; the rest are attributes, so
automations can react ("the kitchen tablet contacted something new") and
the logbook shows what went out.
"""
from __future__ import annotations

from homeassistant.components.event import EventEntity

from .bus import CAP_NETLOG, NET_KINDS, OvosDevice
from .entity import OvosDeviceEntity, setup_capabilities


async def async_setup_entry(hass, entry, add_entities):
    setup_capabilities(hass, entry, add_entities, lambda device, cap:
                       [OvosNetworkRequest(device)] if cap == CAP_NETLOG else [])


class OvosNetworkRequest(OvosDeviceEntity, EventEntity):
    _attr_event_types = NET_KINDS

    def __init__(self, device: OvosDevice) -> None:
        super().__init__(device, "network_request")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.device.listen("ovos.network.request", self._on_request))

    def _on_request(self, message: dict) -> None:
        data = message.get("data") or {}
        kind = data.get("kind") if data.get("kind") in NET_KINDS else "other"
        self._trigger_event(kind, {k: data.get(k) for k in
                                   ("host", "method", "status", "bytes", "who", "service", "t")})
        self.async_write_ha_state()
