"""A device's ovos-control-panel, through its own connection (#15).

What can be set in the control panel -- language, units, voice, speech to
text, wake word, skills on/off, restart and reboot -- shows up in HA as
entities. The integration doesn't read or write mycroft.conf itself: the
panel does, as it always does (your own layer only, a backup on every save).

HA never talks to the panel over the network. The device's link (Emkay,
ovos-phal-plugin-ha-link) says `panel: true` in ovos/connect, and HA's
requests travel over that connection as `panel` events; the link makes the
call to the panel on the device itself (localhost, with the panel's own
token) and answers with ovos/panel/response. So the panel never has to be
opened on the network, and it works behind NAT.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
import itertools
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .bus import OvosDevice

_LOGGER = logging.getLogger(__name__)

CAP_PANEL = "panel"
TIMEOUT = 30
POLL = timedelta(minutes=2)
UPDATES_EVERY = 30        # polls between update checks (about an hour)

_ids = itertools.count(1)


class PanelError(HomeAssistantError):
    """The panel answered with an error, or not at all."""


class PanelClient:
    def __init__(self, device: OvosDevice) -> None:
        self.device = device
        self._waiting: dict[int, asyncio.Future] = {}

    async def request(self, method: str, path: str, body: Any = None) -> Any:
        """One call to the panel's API (path without /api)."""
        if not self.device.available:
            raise PanelError(f"{self.device.entry.title} is not connected")
        req_id = next(_ids)
        fut = self.device.hass.loop.create_future()
        self._waiting[req_id] = fut
        self.device.send_event({"type": "panel", "id": req_id, "method": method,
                                "path": path, "body": body})
        try:
            status, data = await asyncio.wait_for(fut, TIMEOUT)
        except TimeoutError as err:
            raise PanelError(f"the control panel on {self.device.entry.title} did not answer") from err
        finally:
            self._waiting.pop(req_id, None)
        if status >= 400:
            detail = data.get("detail") if isinstance(data, dict) else data
            raise PanelError(f"control panel: {detail or status}")
        return data

    def response(self, req_id: int, status: int, body: Any) -> None:
        fut = self._waiting.get(req_id)
        if fut is not None and not fut.done():
            fut.set_result((status, body))


class PanelCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """What the panel shows, fetched now and then while the device is connected."""

    def __init__(self, hass: HomeAssistant, device: OvosDevice) -> None:
        super().__init__(hass, _LOGGER, name=f"ovos panel {device.device_id}",
                         update_interval=POLL)
        self.device = device
        self.client = PanelClient(device)
        self._polls = 0

    async def _async_update_data(self) -> dict[str, Any]:
        if not self.device.available:
            raise UpdateFailed("not connected")
        data = dict(self.data or {})
        try:
            quick = await self.client.request("GET", "/config/quick")
            data["quick"] = {f["name"]: f for f in quick.get("fields", [])}
            data["health"] = await self.client.request("GET", "/health")
            data["skills"] = (await self.client.request("GET", "/skills")).get("skills", [])
            # off = in skills.blacklisted_skills, as the panel decides it
            merged = (await self.client.request("GET", "/config/merged")).get("config", {})
            off = set((merged.get("skills") or {}).get("blacklisted_skills") or [])
            data["enabled"] = {s["skill_id"]: s["skill_id"] not in off for s in data["skills"]}
            if self._polls % UPDATES_EVERY == 0:
                data["updates"] = await self.client.request("GET", "/updates")
        except PanelError as err:
            raise UpdateFailed(str(err)) from err
        self._polls += 1
        return data

    async def set_quick(self, name: str, value: str | None) -> None:
        await self.client.request("POST", "/config/quick", {"values": {name: value}})
        # shown at once; the next poll has the panel's own word on it
        field = (self.data or {}).get("quick", {}).get(name)
        if field is not None and value is not None:
            field["effective"] = field["value"] = value
            self.async_update_listeners()
        await self.async_request_refresh()

    async def set_skill_enabled(self, skill_id: str, enabled: bool) -> None:
        await self.client.request("PUT", f"/skills/{skill_id}/enabled", {"enabled": enabled})
        self.data["enabled"][skill_id] = enabled
        self.async_update_listeners()
