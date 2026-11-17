"""WebSocket commands for satellites (#11), next to ovos/connect and ovos/bus.

  ovos/satellite/run    subscription: one pipeline run. start_stage "stt":
                        the result is followed by {"type": "init",
                        "handler_id": n}, then the device sends the
                        recording as binary frames (the handler id's byte,
                        then 16 kHz mono 16-bit PCM) and that byte alone to
                        end it. start_stage "intent": `text` instead. The
                        pipeline's events follow, as assist_pipeline/run's
  ovos/satellite/done   the device finished playing: what "tts" (an answer)
                        or "announce" (with its id)
"""
from __future__ import annotations

import asyncio

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from ..const import DATA_DEVICES, DATA_INBOUND_HUB, DOMAIN


def _satellite(hass, connection, msg):
    """The device's satellite entity, if this connection holds the device."""
    hub = hass.data[DOMAIN][DATA_INBOUND_HUB]
    conn = hub.connections.get(msg["device_id"])
    device = hass.data[DOMAIN][DATA_DEVICES].get(msg["device_id"])
    if conn is None or conn.connection is not connection or device is None:
        connection.send_error(msg["id"], "not_connected", "send ovos/connect for this device first")
        return None
    if getattr(device, "satellite", None) is None:
        connection.send_error(msg["id"], "not_a_satellite",
                              "connect with satellite: true to be an Assist satellite")
        return None
    return device.satellite


@websocket_api.websocket_command({
    vol.Required("type"): "ovos/satellite/run",
    vol.Required("device_id"): str,
    vol.Required("start_stage"): vol.In(["stt", "intent"]),
    vol.Optional("text"): str,
    vol.Optional("wake_word_phrase"): str,
})
@websocket_api.async_response
async def ws_run(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    if (satellite := _satellite(hass, connection, msg)) is None:
        return
    msg_id = msg["id"]

    @callback
    def sink(event: dict) -> None:
        connection.send_message(websocket_api.event_message(msg_id, event))

    if msg["start_stage"] == "intent":
        if not msg.get("text"):
            connection.send_error(msg_id, "no_text", "start_stage intent needs text")
            return
        connection.send_result(msg_id)
        sink({"type": "init", "handler_id": None})
        task = hass.async_create_background_task(
            satellite.async_run_text(msg["text"], sink), f"ovos satellite text {msg['device_id']}")
        connection.subscriptions[msg_id] = task.cancel
        return

    audio: asyncio.Queue[bytes] = asyncio.Queue()

    @callback
    def on_binary(_hass, _connection, data: bytes) -> None:
        audio.put_nowait(data)

    handler_id, unregister = connection.async_register_binary_handler(on_binary)

    async def stream():
        while chunk := await audio.get():   # empty = the end of the recording
            yield chunk

    connection.send_result(msg_id)
    sink({"type": "init", "handler_id": handler_id})
    hass.async_create_background_task(
        satellite.async_run_audio(stream(), sink, msg.get("wake_word_phrase")),
        f"ovos satellite run {msg['device_id']}")

    def unsub() -> None:
        audio.put_nowait(b"")
        unregister()

    connection.subscriptions[msg_id] = unsub


@websocket_api.websocket_command({
    vol.Required("type"): "ovos/satellite/done",
    vol.Required("device_id"): str,
    vol.Required("what"): vol.In(["tts", "announce"]),
    vol.Optional("announce_id"): int,
})
@callback
def ws_done(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    if (satellite := _satellite(hass, connection, msg)) is None:
        return
    satellite.device_done(msg["what"], msg.get("announce_id"))
    connection.send_result(msg["id"])


@websocket_api.websocket_command({
    vol.Required("type"): "ovos/satellite/media",
    vol.Required("device_id"): str,
    vol.Required("state"): vol.In(["playing", "paused", "idle"]),
    vol.Optional("url"): vol.Any(str, None),
})
@callback
def ws_media(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """What the device's media player is doing (media_player.py)."""
    if (satellite := _satellite(hass, connection, msg)) is None:
        return
    satellite.device.set_media(msg["state"], msg.get("url"))
    connection.send_result(msg["id"])


@callback
def async_setup_satellite_ws(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_run)
    websocket_api.async_register_command(hass, ws_done)
    websocket_api.async_register_command(hass, ws_media)
