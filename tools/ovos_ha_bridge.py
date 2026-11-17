#!/usr/bin/env python3
"""Connect an OpenVoiceOS to Home Assistant -- the reference client for the
integration's inbound protocol (docs/protocol.md, issue #9).

Runs next to an OVOS, connects to its messagebus and to Home Assistant's
WebSocket API, and carries bus messages both ways: what HA sends goes on the
OVOS bus, and the message types HA asks for (the "forward" list in the ready
event) go to HA. The OVOS then shows up in HA as a device with its volume,
listening, state and so on. Emkay has its own client in JavaScript; this one
shows the protocol isn't Emkay's.

    pip install aiohttp
    python3 ovos_ha_bridge.py --ha https://ha.example:8123 --token <long-lived token>

The first time, HA shows the device under Settings -> Devices & services ->
Discovered; add it there. The device id is kept in
~/.config/ovos-ha-bridge/device_id, so it stays the same device.

--fake answers like a small OVOS without one (volume, mic, a battery
sensor), for trying the integration out.
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import logging
from pathlib import Path
import platform
import time
import uuid

import aiohttp

LOG = logging.getLogger("ovos-ha-bridge")
PROTOCOL = 1


def stored_device_id() -> str:
    path = Path.home() / ".config" / "ovos-ha-bridge" / "device_id"
    if path.exists():
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    new = f"ovos-{uuid.uuid4()}"
    path.write_text(new)
    return new


class HomeAssistant:
    """HA's WebSocket API, with the integration's ovos/* commands."""

    def __init__(self, url: str, token: str) -> None:
        self.url = url.rstrip("/").replace("http", "ws", 1) + "/api/websocket"
        self.token = token
        self.ids = itertools.count(1)
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.pending: dict[int, asyncio.Future] = {}
        self.connect_id: int | None = None

    async def open(self, session: aiohttp.ClientSession) -> None:
        self.ws = await session.ws_connect(self.url, heartbeat=30)
        hello = await self.ws.receive_json()
        assert hello["type"] == "auth_required", hello
        await self.ws.send_json({"type": "auth", "access_token": self.token})
        auth = await self.ws.receive_json()
        if auth["type"] != "auth_ok":
            raise SystemExit(f"Home Assistant said: {auth.get('message', auth)}")
        LOG.info("logged in to Home Assistant %s", auth.get("ha_version"))

    async def command(self, msg: dict) -> dict:
        msg_id = next(self.ids)
        fut = asyncio.get_running_loop().create_future()
        self.pending[msg_id] = fut
        await self.ws.send_json({"id": msg_id, **msg})
        result = await fut
        if not result.get("success"):
            LOG.warning("HA refused %s: %s", msg.get("type"), result.get("error"))
        return result

    async def events(self):
        """The ovos/connect subscription's events; answers go to command()."""
        async for raw in self.ws:
            if raw.type != aiohttp.WSMsgType.TEXT:
                continue
            msg = json.loads(raw.data)
            if msg.get("id") == self.connect_id:
                if msg.get("type") == "result" and not msg.get("success"):
                    raise SystemExit(f"Home Assistant refused the device: {msg.get('error')}")
                if msg.get("type") == "event":
                    yield msg["event"]
            elif msg.get("type") == "result" and msg.get("id") in self.pending:
                self.pending.pop(msg["id"]).set_result(msg)


class Bridge:
    def __init__(self, args) -> None:
        self.args = args
        self.ha = HomeAssistant(args.ha, args.token)
        self.device_id = args.device_id or stored_device_id()
        self.forward: set[str] = set()
        self.bus: aiohttp.ClientWebSocketResponse | None = None
        # --fake
        self.volume, self.muted, self.mic_muted = 0.6, False, False

    async def run(self) -> None:
        """Connect, and connect again when HA restarts or the network drops."""
        while True:
            try:
                await self._run_once()
                LOG.warning("Home Assistant closed the connection")
            except (aiohttp.ClientError, OSError) as e:
                LOG.warning("can't reach Home Assistant or the bus: %s", e)
            self.ha = HomeAssistant(self.args.ha, self.args.token)
            await asyncio.sleep(10)

    async def _run_once(self) -> None:
        async with aiohttp.ClientSession() as session:
            await self.ha.open(session)
            if not self.args.fake:
                self.bus = await session.ws_connect(self.args.bus)
                LOG.info("connected to the OVOS bus at %s", self.args.bus)
            self.ha.connect_id = next(self.ha.ids)
            await self.ha.ws.send_json({
                "id": self.ha.connect_id, "type": "ovos/connect",
                "protocol": PROTOCOL, "device_id": self.device_id,
                "name": self.args.name, "model": "ovos-ha-bridge",
                "manufacturer": "OpenVoiceOS", "lang": self.args.lang,
            })
            tasks = [asyncio.ensure_future(self._read_ha())]
            if self.bus is not None:
                tasks.append(asyncio.ensure_future(self._read_bus()))
            done, rest = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in rest:
                t.cancel()
            for t in done:
                t.result()

    async def _read_ha(self) -> None:
        async for event in self.ha.events():
            match event.get("type"):
                case "pending":
                    LOG.info("waiting: add the device in Home Assistant "
                             "(Settings -> Devices & services -> Discovered)")
                case "ready":
                    self.forward = set(event.get("forward", []))
                    LOG.info("ready (entry %s); forwarding %d message types",
                             event.get("entry_id"), len(self.forward))
                    if self.args.fake:
                        asyncio.ensure_future(self._fake_sensors())
                case "bus":
                    asyncio.ensure_future(self._to_ovos(event["message"]))
                case "displaced":
                    raise SystemExit("another connection took over this device")
                case "removed":
                    raise SystemExit("the device was removed in Home Assistant")

    async def _read_bus(self) -> None:
        async for raw in self.bus:
            if raw.type != aiohttp.WSMsgType.TEXT:
                continue
            msg = json.loads(raw.data)
            if msg.get("type") in self.forward:
                await self.to_ha(msg)

    async def to_ha(self, msg: dict) -> None:
        LOG.debug("-> HA %s", msg.get("type"))
        await self.ha.command({"type": "ovos/bus", "device_id": self.device_id,
                               "message": {"type": msg["type"],
                                           "data": msg.get("data") or {},
                                           "context": msg.get("context") or {}}})

    async def _to_ovos(self, msg: dict) -> None:
        LOG.debug("<- HA %s %s", msg["type"], msg.get("data"))
        if self.args.fake:
            await self._fake(msg)
        else:
            await self.bus.send_json(msg)

    # --- --fake: a tiny pretend OVOS --------------------------------------

    async def _fake(self, msg: dict) -> None:  # noqa: C901
        t, d = msg["type"], msg.get("data") or {}

        async def reply(typ: str, data: dict | None = None) -> None:
            await self.to_ha({"type": typ, "data": data or {}})

        async def volume() -> None:
            await reply("mycroft.volume.get.response",
                        {"percent": self.volume, "muted": self.muted})

        match t:
            case "mycroft.volume.get":
                await volume()
            case "mycroft.volume.set":
                self.volume = float(d.get("percent", self.volume))
                await volume()
            case "mycroft.volume.mute" | "mycroft.volume.unmute":
                self.muted = t.endswith(".mute")
                await volume()
            case "mycroft.mic.get_status":
                await reply("mycroft.mic.get_status.response", {"muted": self.mic_muted})
            case "mycroft.mic.mute" | "mycroft.mic.unmute":
                self.mic_muted = t.endswith(".mute")
                await reply(t)
            case "speak":
                LOG.info("says: %s", d.get("utterance"))
                await reply("speak", d)
                await reply("recognizer_loop:audio_output_start")
                await asyncio.sleep(2)
                await reply("recognizer_loop:audio_output_end")
            case "recognizer_loop:utterance":
                LOG.info("asked: %s", d.get("utterances"))
                await reply("recognizer_loop:utterance", d)
                await self._fake({"type": "speak",
                                  "data": {"utterance": f"You said {d['utterances'][0]}"}})
            case "mycroft.mic.listen":
                await reply("recognizer_loop:record_begin")
                await asyncio.sleep(1)
                await reply("recognizer_loop:record_end")
                await self._fake({"type": "recognizer_loop:utterance",
                                  "data": {"utterances": ["hello"]}})

    async def _fake_sensors(self) -> None:
        await self.to_ha({"type": "ovos.phal.sensor", "data": {
            "sensor_id": "battery", "name": "Battery", "state": 87,
            "attributes": {"unit_of_measurement": "%", "device_class": "battery"}}})
        await self.to_ha({"type": "ovos.phal.binary_sensor", "data": {
            "sensor_id": "charging", "name": "Charging", "state": True}})
        # two requests "sent out", as a network log would report them (#16)
        for host, kind, service, who in (
                ("stt.openvoiceos.pt", "stt", "speech recognition (OpenVoiceOS server)", "ovos-stt-plugin-server"),
                ("da.wikipedia.org", "wikipedia", "Wikipedia", "ovos-skill-wikipedia")):
            await self.to_ha({"type": "ovos.network.request", "data": {
                "t": int(time.time() * 1000), "host": host, "method": "GET", "status": 200,
                "bytes": 512, "who": who, "kind": kind, "service": service}})


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--ha", required=True, help="Home Assistant's address, e.g. https://ha.example:8123")
    p.add_argument("--token", required=True, help="a long-lived access token (your HA profile -> Security)")
    p.add_argument("--bus", default="ws://127.0.0.1:8181/core", help="the OVOS messagebus")
    p.add_argument("--name", default=platform.node(), help="the device's name in HA")
    p.add_argument("--lang", default="en-us")
    p.add_argument("--device-id", help="override the stored device id")
    p.add_argument("--fake", action="store_true", help="pretend to be an OVOS (no bus)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(Bridge(args).run())


if __name__ == "__main__":
    main()
