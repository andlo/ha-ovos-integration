"""OVOS -> HA: the device connects to HA's WebSocket API (issue #9).

For OVOS devices HA can't reach: Emkay in a browser (a browser can't accept
connections) and devices behind NAT. The device logs in to HA like any app
(HA's normal login, see docs/protocol.md), opens HA's WebSocket API and uses
the integration's commands:

  ovos/connect   subscription: "I am device X". Events back: pending (waiting
                 for someone in HA to accept it), ready, bus (a bus message
                 for the device), displaced, removed
  ovos/bus       a bus message from the device

The protocol is versioned (const.PROTOCOL_VERSION) and documented in
docs/protocol.md, so any OVOS client can use it -- tools/ovos_ha_bridge.py is
a small reference client in Python besides Emkay's own in JavaScript.

A device HA doesn't know yet is offered as a discovered integration ("New
OpenVoiceOS device found"), and becomes a config entry when someone accepts
it there. Only the HA user the device first logged in as, or an admin, can
connect as that device afterwards.
"""
from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
import voluptuous as vol

from homeassistant.components.http import KEY_HASS, HomeAssistantView

from homeassistant.components import websocket_api
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, discovery_flow

from ..const import (
    CONF_DEVICE_ID,
    CONF_ENTRY_TYPE,
    CONF_MANUFACTURER,
    CONF_MODEL,
    CONF_NAME,
    CONF_SW_VERSION,
    CONF_USER_ID,
    DATA_DEVICES,
    DATA_INBOUND_HUB,
    DOMAIN,
    ENTRY_TYPE_DEVICE,
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOLS,
)
from .bus import FORWARD_TYPES, OvosDevice
from .satellite import async_setup_satellite_ws
from ..registry import get_device

_LOGGER = logging.getLogger(__name__)

# What a device may say about itself in ovos/connect
_TEXT = vol.All(str, vol.Length(max=100))
CONNECT_SCHEMA = {
    vol.Required("type"): "ovos/connect",
    vol.Required("protocol"): int,
    # stable per device, chosen by the device (a random UUID is fine)
    vol.Required("device_id"): vol.All(str, vol.Length(min=8, max=64),
                                       vol.Match(r"^[A-Za-z0-9_.:-]+$")),
    vol.Required("name"): vol.All(str, vol.Length(min=1, max=100)),
    vol.Optional("model"): _TEXT,
    vol.Optional("manufacturer"): _TEXT,
    vol.Optional("sw_version"): _TEXT,
    vol.Optional("lang"): vol.All(str, vol.Length(max=16)),
    # it sends audio and wants to be an Assist satellite (#11)
    vol.Optional("satellite"): bool,
    # the wake words it can listen for, and the one it uses (#11): chosen in HA
    vol.Optional("wake_words"): [vol.Schema({
        vol.Required("id"): vol.All(str, vol.Length(max=64)),
        vol.Required("wake_word"): vol.All(str, vol.Length(max=64)),
        vol.Optional("languages"): [str],
    })],
    vol.Optional("wake_word"): vol.All(str, vol.Length(max=64)),
}

BUS_SCHEMA = {
    vol.Required("type"): "ovos/bus",
    vol.Required("device_id"): str,
    vol.Required("message"): vol.Schema({
        vol.Required("type"): vol.All(str, vol.Length(min=1, max=200)),
        vol.Optional("data"): dict,
        vol.Optional("context"): dict,
    }),
}


class InboundConnection:
    """One device's open ovos/connect subscription -- its transport."""

    def __init__(self, connection: websocket_api.ActiveConnection, msg_id: int,
                 info: dict[str, Any]) -> None:
        self.connection = connection
        self.msg_id = msg_id
        self.info = info
        self.device_id: str = info[CONF_DEVICE_ID]

    @property
    def user_id(self) -> str:
        return self.connection.user.id

    def send_event(self, event: dict[str, Any]) -> None:
        self.connection.send_message(websocket_api.event_message(self.msg_id, event))

    def send_bus(self, message: dict[str, Any]) -> None:
        self.send_event({"type": "bus", "message": message})


class InboundHub:
    """Keeps the open device connections and pairs them with config entries."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.connections: dict[str, InboundConnection] = {}
        # set by the "inbound" entry: devices may connect at all
        self.enabled = False

    @callback
    def try_attach(self, device_id: str) -> None:
        """Pair a live connection with its loaded device, if both are there."""
        conn = self.connections.get(device_id)
        device: OvosDevice | None = self.hass.data[DOMAIN][DATA_DEVICES].get(device_id)
        if conn is None or device is None:
            return
        _update_device_info(self.hass, device.entry, conn.info)
        ha_device = get_device(self.hass, (DOMAIN, device_id), device.entry.entry_id)
        # ready first: attach() asks the device what it can do at once, and
        # a client only answers once it has heard ready (and its forward list)
        conn.send_event({
            "type": "ready",
            "protocol": PROTOCOL_VERSION,
            "entry_id": device.entry.entry_id,
            # HA's own id for the device: give it as device_id to
            # assist_pipeline/run, so Assist knows where it was asked (area)
            "device_id": ha_device.id if ha_device else None,
            "forward": FORWARD_TYPES,
            # what this integration offers beyond the bus
            "features": ["satellite"],
        })
        device.attach(conn, conn.info)

    @callback
    def device_unloaded(self, device_id: str) -> None:
        """The entry was unloaded (reload, disabled): wait again."""
        conn = self.connections.get(device_id)
        if conn is not None:
            conn.send_event({"type": "pending"})

    @callback
    def device_removed(self, device_id: str) -> None:
        """The entry was deleted: tell the device and forget the connection."""
        conn = self.connections.pop(device_id, None)
        if conn is not None:
            conn.send_event({"type": "removed"})

    @callback
    def disconnected(self, conn: InboundConnection) -> None:
        if self.connections.get(conn.device_id) is conn:
            del self.connections[conn.device_id]
        device: OvosDevice | None = self.hass.data[DOMAIN][DATA_DEVICES].get(conn.device_id)
        if device is not None:
            device.detach(conn)


def _find_entry(hass: HomeAssistant, device_id: str) -> ConfigEntry | None:
    for entry in hass.config_entries.async_entries(DOMAIN, include_ignore=False):
        if (entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_DEVICE
                and entry.data.get(CONF_DEVICE_ID) == device_id):
            return entry
    return None


def _update_device_info(hass: HomeAssistant, entry: ConfigEntry, info: dict) -> None:
    """Keep model/version current as the device updates itself."""
    new = {k: info[k] for k in (CONF_MODEL, CONF_MANUFACTURER, CONF_SW_VERSION) if k in info}
    if any(entry.data.get(k) != v for k, v in new.items()):
        hass.config_entries.async_update_entry(entry, data={**entry.data, **new})
        registry = dr.async_get(hass)
        if (device := get_device(hass, (DOMAIN, entry.data[CONF_DEVICE_ID]), entry.entry_id)):
            registry.async_update_device(
                device.id,
                model=new.get(CONF_MODEL, device.model),
                manufacturer=new.get(CONF_MANUFACTURER, device.manufacturer),
                sw_version=new.get(CONF_SW_VERSION, device.sw_version),
            )


@websocket_api.websocket_command(CONNECT_SCHEMA)
@websocket_api.async_response
async def ws_connect(hass: HomeAssistant, connection: websocket_api.ActiveConnection,
                     msg: dict) -> None:
    hub: InboundHub = hass.data[DOMAIN][DATA_INBOUND_HUB]
    if not hub.enabled:
        connection.send_error(
            msg["id"], "not_enabled",
            "add the OpenVoiceOS integration in Home Assistant and choose "
            "\"Let OpenVoiceOS devices connect\" first",
        )
        return
    if msg["protocol"] not in SUPPORTED_PROTOCOLS:
        connection.send_error(
            msg["id"], "unsupported_protocol",
            f"this integration speaks protocol {', '.join(map(str, SUPPORTED_PROTOCOLS))}",
        )
        return

    device_id = msg["device_id"]
    entry = _find_entry(hass, device_id)
    if (entry is not None and entry.data.get(CONF_USER_ID) != connection.user.id
            and not connection.user.is_admin):
        connection.send_error(msg["id"], websocket_api.ERR_UNAUTHORIZED,
                              "this device belongs to another user")
        return

    info = {k: v for k, v in msg.items() if k not in ("id", "type", "protocol")}
    conn = InboundConnection(connection, msg["id"], info)
    if (old := hub.connections.get(device_id)) is not None:
        old.send_event({"type": "displaced"})
        hub.disconnected(old)
    hub.connections[device_id] = conn
    connection.subscriptions[msg["id"]] = lambda: hub.disconnected(conn)
    connection.send_result(msg["id"])

    if entry is None:
        conn.send_event({"type": "pending"})
        discovery_flow.async_create_flow(
            hass, DOMAIN,
            context={"source": SOURCE_INTEGRATION_DISCOVERY},
            data={
                CONF_DEVICE_ID: device_id,
                CONF_NAME: msg["name"],
                CONF_USER_ID: connection.user.id,
                CONF_MODEL: msg.get("model"),
                CONF_MANUFACTURER: msg.get("manufacturer"),
                CONF_SW_VERSION: msg.get("sw_version"),
                "user_name": connection.user.name,
            },
        )
        return

    if hass.data[DOMAIN][DATA_DEVICES].get(device_id) is None:
        conn.send_event({"type": "pending"})   # entry disabled or still loading
        return
    hub.try_attach(device_id)


@websocket_api.websocket_command(BUS_SCHEMA)
@callback
def ws_bus(hass: HomeAssistant, connection: websocket_api.ActiveConnection,
           msg: dict) -> None:
    hub: InboundHub = hass.data[DOMAIN][DATA_INBOUND_HUB]
    conn = hub.connections.get(msg["device_id"])
    if conn is None or conn.connection is not connection:
        connection.send_error(msg["id"], "not_connected",
                              "send ovos/connect for this device first")
        return
    device: OvosDevice | None = hass.data[DOMAIN][DATA_DEVICES].get(msg["device_id"])
    if device is not None and device.transport is conn:
        device.handle_message(msg["message"])
    connection.send_result(msg["id"])


class OvosTtsView(HomeAssistantView):
    """HA's TTS audio (tts-end's token), with CORS.

    /api/tts_proxy/<token> has no CORS headers, so a page on another site
    (Emkay at app.emkay.ai) can't fetch it to play it through its own
    speaker -- the face's mouth and the volume go through Web Audio, which
    needs the bytes. Same content, same unguessable token, nothing more.
    """

    url = "/api/ovos/tts/{token}"
    name = "api:ovos:tts"
    requires_auth = False
    cors_allowed = True

    async def get(self, request: web.Request, token: str) -> web.StreamResponse:
        hass = request.app[KEY_HASS]
        try:
            from homeassistant.components.tts import TextToSpeechView
            from homeassistant.components.tts.const import DATA_TTS_MANAGER
            manager = hass.data[DATA_TTS_MANAGER]
        except (ImportError, KeyError):
            return web.Response(status=404)
        return await TextToSpeechView(manager).get(request, token)


@callback
def async_setup_inbound(hass: HomeAssistant) -> None:
    hass.data[DOMAIN][DATA_INBOUND_HUB] = InboundHub(hass)
    hass.http.register_view(OvosTtsView())
    async_setup_satellite_ws(hass)
    websocket_api.async_register_command(hass, ws_connect)
    websocket_api.async_register_command(hass, ws_bus)
