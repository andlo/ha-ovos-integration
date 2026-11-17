"""One OpenVoiceOS device, as HA sees it: a bus (issue #10).

Whatever the transport -- the device connecting to HA (#9, inbound.py) or
HA connecting to its hivemind-core (#8, later) -- the device is a stream of
OVOS bus messages both ways. Everything the entities show comes from those
messages, and everything they do is a bus message, so the same entities work
for every kind of OVOS and both directions.

What a device can do is found out by asking it over the bus (probe): it
answers `mycroft.volume.get`, so it has a volume; it answers
`ovos.local_only.status`, so it has "local only"; it sends
`ovos.phal.sensor`, so it has that sensor. The integration never needs to
know which kind of OVOS it is talking to. What has been found is kept in the
config entry, so the entities are there (unavailable) after a restart, before
the device is back.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
from typing import Any, Protocol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later

from ..const import CONF_DEVICE_ID, SIGNAL_NEW_CAPABILITY

_LOGGER = logging.getLogger(__name__)

CONF_CAPABILITIES = "capabilities"
CONF_SENSORS = "sensors"

# Capabilities a device answers to (found by probing)
CAP_VOLUME = "volume"          # mycroft.volume.get -> .response {percent, muted}
CAP_MIC = "mic"                # mycroft.mic.get_status -> .response {muted}
CAP_LOCAL_ONLY = "local_only"  # ovos.local_only.status -> .response {enabled}
CAP_KIOSK = "kiosk"            # ovos.kiosk.status -> .response {keep_awake, ...}

# What is asked when a device (re)connects: request -> capability
PROBES = {
    "mycroft.volume.get": CAP_VOLUME,
    "mycroft.mic.get_status": CAP_MIC,
    "ovos.local_only.status": CAP_LOCAL_ONLY,
    "ovos.kiosk.status": CAP_KIOSK,
}

STATE_IDLE = "idle"
STATE_LISTENING = "listening"
STATE_THINKING = "thinking"
STATE_SPEAKING = "speaking"
STATE_SLEEPING = "sleeping"
STATES = [STATE_IDLE, STATE_LISTENING, STATE_THINKING, STATE_SPEAKING, STATE_SLEEPING]

# "thinking" that never ends (a skill that says nothing, a lost message)
# falls back to idle after this long
THINKING_TIMEOUT = 30

# The bus messages HA wants from a device. Sent to the client in the
# "ready" event, so a client bridging a whole OVOS bus can forward just
# these instead of everything (docs/protocol.md).
FORWARD_TYPES = sorted({
    # state
    "recognizer_loop:wakeword", "recognizer_loop:record_begin",
    "recognizer_loop:record_end", "recognizer_loop:utterance",
    "recognizer_loop:audio_output_start", "recognizer_loop:audio_output_end",
    "recognizer_loop:sleep", "recognizer_loop:wake_up",
    "ovos.utterance.handled", "mycroft.stop", "speak",
    # answers to the probes, and changes made on the device itself
    *(f"{t}.response" for t in PROBES),
    "mycroft.mic.mute", "mycroft.mic.unmute", "mycroft.mic.mute.toggle",
    "ovos.local_only.changed",
    "ovos.kiosk.keep_awake.response",
    # whatever sensors the device has (ovos-PHAL-sensors' messages)
    "ovos.phal.sensor", "ovos.phal.binary_sensor",
})


class Transport(Protocol):
    """How a device's bus reaches HA (inbound.py; hivemind later)."""

    def send_bus(self, message: dict[str, Any]) -> None:
        """A bus message from HA to the device."""


class OvosDevice:
    """The runtime side of one device config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.device_id: str = entry.data[CONF_DEVICE_ID]
        self.transport: Transport | None = None
        self.info: dict[str, Any] = {}

        self.capabilities: set[str] = set(entry.data.get(CONF_CAPABILITIES, []))
        # sensor_id -> {"binary": bool, "name": str, "state": ..., "attributes": {}}
        self.sensors: dict[str, dict[str, Any]] = {
            sid: {**s, "state": None, "attributes": {}}
            for sid, s in entry.data.get(CONF_SENSORS, {}).items()
        }

        self.state = STATE_IDLE
        self.last_question: str | None = None
        self.last_answer: str | None = None
        self.volume: float | None = None        # 0..1
        self.speaker_muted: bool | None = None
        self.mic_muted: bool | None = None
        self.local_only: bool | None = None
        self.keep_awake: bool | None = None

        self._spoke = False
        self._thinking_timer: CALLBACK_TYPE | None = None
        self._update_listeners: list[Callable[[], None]] = []
        self._listeners: dict[str, list[Callable[[dict], None]]] = {}
        self._waiters: dict[str, list[asyncio.Future]] = {}

    # --- connection ------------------------------------------------------

    @property
    def available(self) -> bool:
        return self.transport is not None

    @callback
    def attach(self, transport: Transport, info: dict[str, Any]) -> None:
        self.transport = transport
        self.info = info
        self._set_state(STATE_IDLE)
        self._notify()
        self.probe()

    @callback
    def detach(self, transport: Transport | None = None) -> None:
        if transport is not None and transport is not self.transport:
            return
        self.transport = None
        self._cancel_thinking_timer()
        for futs in self._waiters.values():
            for fut in futs:
                if not fut.done():
                    fut.cancel()
        self._waiters.clear()
        self._notify()

    @callback
    def probe(self) -> None:
        """Ask what the device can do; the answers come as .response."""
        for request in PROBES:
            self.send(request)

    # --- talking to the device -----------------------------------------

    @callback
    def send(self, msg_type: str, data: dict | None = None,
             context: dict | None = None) -> bool:
        if self.transport is None:
            return False
        self.transport.send_bus({
            "type": msg_type,
            "data": data or {},
            "context": {"source": "homeassistant", **(context or {})},
        })
        return True

    async def request(self, msg_type: str, data: dict | None = None,
                      timeout: float = 5) -> dict | None:
        """Send and wait for `<type>.response`; None if none came."""
        fut: asyncio.Future = self.hass.loop.create_future()
        self._waiters.setdefault(f"{msg_type}.response", []).append(fut)
        if not self.send(msg_type, data):
            return None
        try:
            return await asyncio.wait_for(fut, timeout)
        except (TimeoutError, asyncio.CancelledError):
            return None

    @callback
    def listen(self, msg_type: str, fn: Callable[[dict], None]) -> CALLBACK_TYPE:
        """Every message of a type from the device (for #11 and services)."""
        self._listeners.setdefault(msg_type, []).append(fn)
        return lambda: self._listeners[msg_type].remove(fn)

    @callback
    def add_update_listener(self, fn: Callable[[], None]) -> CALLBACK_TYPE:
        self._update_listeners.append(fn)
        return lambda: self._update_listeners.remove(fn)

    # --- messages from the device ---------------------------------------

    @callback
    def handle_message(self, message: dict[str, Any]) -> None:
        msg_type = message.get("type")
        data = message.get("data") or {}
        if not isinstance(msg_type, str) or not isinstance(data, dict):
            return
        for fut in self._waiters.pop(msg_type, []):
            if not fut.done():
                fut.set_result(data)
        changed = self._update_from(msg_type, data)
        for fn in list(self._listeners.get(msg_type, [])):
            fn(message)
        if changed:
            self._notify()

    def _update_from(self, msg_type: str, data: dict) -> bool:  # noqa: C901
        match msg_type:
            case "recognizer_loop:wakeword" | "recognizer_loop:record_begin":
                self._set_state(STATE_LISTENING)
            case "recognizer_loop:record_end":
                self._set_state(STATE_THINKING)
            case "recognizer_loop:utterance":
                utterances = data.get("utterances") or []
                if utterances:
                    self.last_question = str(utterances[0])[:255]
                self._spoke = False
                self._set_state(STATE_THINKING)
            case "speak":
                if data.get("utterance"):
                    self.last_answer = str(data["utterance"])[:255]
                self._spoke = True
            case "recognizer_loop:audio_output_start":
                self._set_state(STATE_SPEAKING)
            case "recognizer_loop:audio_output_end" | "mycroft.stop":
                self._set_state(STATE_IDLE)
            case "ovos.utterance.handled":
                if self.state == STATE_THINKING and not self._spoke:
                    self._set_state(STATE_IDLE)
            case "recognizer_loop:sleep":
                self._set_state(STATE_SLEEPING)
            case "recognizer_loop:wake_up":
                self._set_state(STATE_IDLE)
            case "mycroft.volume.get.response":
                if "percent" in data:
                    self.volume = max(0.0, min(1.0, float(data["percent"])))
                if "muted" in data:
                    self.speaker_muted = bool(data["muted"])
                self._found(CAP_VOLUME)
            case "mycroft.mic.get_status.response":
                self.mic_muted = bool(data.get("muted"))
                self._found(CAP_MIC)
            case "mycroft.mic.mute":
                self.mic_muted = True
            case "mycroft.mic.unmute":
                self.mic_muted = False
            case "mycroft.mic.mute.toggle":
                self.send("mycroft.mic.get_status")
                return False
            case "ovos.local_only.status.response" | "ovos.local_only.changed":
                self.local_only = bool(data.get("enabled"))
                self._found(CAP_LOCAL_ONLY)
            case "ovos.kiosk.status.response" | "ovos.kiosk.keep_awake.response":
                if "keep_awake" in data:
                    self.keep_awake = bool(data["keep_awake"])
                elif "enabled" in data:
                    self.keep_awake = bool(data["enabled"])
                if msg_type == "ovos.kiosk.status.response" and data.get("supported", True):
                    self._found(CAP_KIOSK)
            case "ovos.phal.sensor" | "ovos.phal.binary_sensor":
                self._sensor(msg_type == "ovos.phal.binary_sensor", data)
            case _:
                return False
        return True

    def _sensor(self, binary: bool, data: dict) -> None:
        sensor_id = data.get("sensor_id")
        if not isinstance(sensor_id, str) or not sensor_id:
            return
        attributes = data.get("attributes")
        known = self.sensors.get(sensor_id)
        if known is None:
            # ovos-PHAL-sensors puts the readable name in friendly_name
            # ("Battery Level"); `name` is the bare reading ("level")
            name = (attributes or {}).get("friendly_name") if isinstance(attributes, dict) else None
            known = self.sensors[sensor_id] = {
                "binary": binary, "name": str(name or data.get("name") or sensor_id),
            }
            self._save()
            async_dispatcher_send(
                self.hass, SIGNAL_NEW_CAPABILITY.format(self.entry.entry_id),
                f"sensor:{sensor_id}",
            )
        known["state"] = data.get("state")
        known["attributes"] = attributes if isinstance(attributes, dict) else {}

    # --- bookkeeping ------------------------------------------------------

    def _found(self, capability: str) -> None:
        if capability in self.capabilities:
            return
        self.capabilities.add(capability)
        self._save()
        async_dispatcher_send(
            self.hass, SIGNAL_NEW_CAPABILITY.format(self.entry.entry_id), capability,
        )

    def _save(self) -> None:
        self.hass.config_entries.async_update_entry(self.entry, data={
            **self.entry.data,
            CONF_CAPABILITIES: sorted(self.capabilities),
            CONF_SENSORS: {
                sid: {"binary": s["binary"], "name": s["name"]}
                for sid, s in self.sensors.items()
            },
        })

    def _set_state(self, state: str) -> None:
        self.state = state
        self._cancel_thinking_timer()
        if state == STATE_THINKING:
            self._thinking_timer = async_call_later(
                self.hass, THINKING_TIMEOUT, self._thinking_timed_out
            )

    @callback
    def _thinking_timed_out(self, _now) -> None:
        self._thinking_timer = None
        if self.state == STATE_THINKING:
            self.state = STATE_IDLE
            self._notify()

    def _cancel_thinking_timer(self) -> None:
        if self._thinking_timer is not None:
            self._thinking_timer()
            self._thinking_timer = None

    def _notify(self) -> None:
        for fn in list(self._update_listeners):
            fn()
