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
import base64
from datetime import datetime, timedelta
import itertools
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .bus import OvosDevice

_LOGGER = logging.getLogger(__name__)

CAP_PANEL = "panel"
TIMEOUT = 30
POLL = timedelta(minutes=2)
UPDATES_EVERY = 30        # polls between update checks (about an hour)
SETTINGS_EVERY = 15       # polls between re-reading the skills' settings (half an hour)
BACKUP_DIR = "ovos_backups"
KEEP_BACKUPS = 5          # per device

# settingsmeta field types HA can show, and as what
KINDS = {"checkbox": "switch", "number": "number", "select": "select",
         "text": "text", "password": "text", "email": "text"}

_ids = itertools.count(1)


def _options(raw: Any) -> list[tuple[str, str]]:
    """A select field's choices as (label, value): "Label|value;..." as
    Mycroft wrote them, or a list of strings or {label, value}."""
    out: list[tuple[str, str]] = []
    if isinstance(raw, str):
        raw = [o for o in raw.split(";") if o.strip()]
    for opt in raw or []:
        if isinstance(opt, dict):
            value = str(opt.get("value", opt.get("label", "")))
            out.append((str(opt.get("label") or value), value))
        else:
            label, _, value = str(opt).partition("|")
            out.append((label.strip(), (value or label).strip()))
    return out


def skill_fields(info: dict[str, Any]) -> list[dict[str, Any]]:
    """The settings of one skill HA can show: the fields of its
    settingsmeta (the panel's, generated from settings.json when the skill
    has none), each once, nothing internal ("_..."), nothing nested."""
    settings = info.get("settings") or {}
    meta = (info.get("meta") or {}).get("skillMetadata") or {}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for section in meta.get("sections") or []:
        for field in section.get("fields") or []:
            name = field.get("name")
            ftype = str(field.get("type") or "text").lower()
            if (not name or name.startswith("_") or name in seen or ftype not in KINDS
                    or isinstance(settings.get(name), (dict, list))):
                continue
            # the generated meta lists a bool both as checkbox and number
            if ftype == "number" and isinstance(settings.get(name), bool):
                continue
            seen.add(name)
            options = _options(field.get("options")) if ftype == "select" else []
            kind = KINDS[ftype] if ftype != "select" or options else "text"
            out.append({"name": name, "type": ftype, "kind": kind, "options": options,
                        "label": field.get("label") or name.replace("_", " ").capitalize(),
                        "default": field.get("value")})
    return out


class PanelError(HomeAssistantError):
    """The panel answered with an error, or not at all."""


class PanelClient:
    def __init__(self, device: OvosDevice) -> None:
        self.device = device
        self._waiting: dict[int, asyncio.Future] = {}

    async def request(self, method: str, path: str, body: Any = None,
                      binary: bool = False, timeout: float = TIMEOUT) -> Any:
        """One call to the panel's API (path without /api). With binary the
        answer is a file, which the link sends as {content_type, filename,
        data} with data in base64."""
        if not self.device.available:
            raise PanelError(f"{self.device.entry.title} is not connected")
        req_id = next(_ids)
        fut = self.device.hass.loop.create_future()
        self._waiting[req_id] = fut
        event = {"type": "panel", "id": req_id, "method": method, "path": path, "body": body}
        if binary:
            event["binary"] = True
        self.device.send_event(event)
        try:
            status, data = await asyncio.wait_for(fut, timeout)
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
        # skill_id -> {"settings", "fields", "generated"}; kept outside
        # self.data because it is read in the background, one skill at a time
        self.settings: dict[str, dict[str, Any]] = {}
        self._settings_task: asyncio.Task | None = None
        self._asked: set[str] = set()
        self.setting_kinds: set[str] = set()    # platforms already adding settings
        self.last_backup: Path | None = None
        self.last_backup_at: datetime | None = None

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
                data["channel"] = await self.client.request("GET", "/updates/channel")
        except PanelError as err:
            raise UpdateFailed(str(err)) from err
        wanted = [s["skill_id"] for s in data["skills"] if s.get("has_settings") or s.get("has_meta")]
        if self._polls % SETTINGS_EVERY == 0:
            self._read_settings(wanted)
        elif new := [sid for sid in wanted if sid not in self._asked]:
            self._read_settings(new)    # a skill installed since
        self._polls += 1
        return data

    def _read_settings(self, skill_ids: list[str]) -> None:
        """Each skill's settings, in the background: one call per skill,
        and a slow device (Emkay) shouldn't hold up the rest."""
        if self._settings_task is not None and not self._settings_task.done():
            return
        self._asked.update(skill_ids)
        self._settings_task = self.hass.async_create_background_task(
            self._read_settings_now(skill_ids), f"ovos panel settings {self.device.device_id}")

    async def _read_settings_now(self, skill_ids: list[str]) -> None:
        for sid in skill_ids:
            if not self.device.available:
                return
            try:
                info = await self.client.request("GET", f"/skills/{sid}")
            except PanelError as err:
                _LOGGER.debug("settings of %s: %s", sid, err)
                continue
            self.settings[sid] = {"settings": info.get("settings") or {},
                                  "fields": skill_fields(info),
                                  "generated": bool(info.get("generated_meta"))}
            self.async_update_listeners()

    async def set_skill_setting(self, skill_id: str, name: str, value: Any) -> None:
        """One setting of a skill; the panel merges it into settings.json."""
        await self.client.request("PUT", f"/skills/{skill_id}", {"settings": {name: value}})
        self.settings[skill_id]["settings"][name] = value
        self.async_update_listeners()

    # --- backups: the panel's archive of the settings, kept in HA ---------------

    @property
    def backup_dir(self) -> Path:
        """/config/ovos_backups/<device>: inside /config, so HA's own
        backups take them along."""
        return Path(self.hass.config.path(BACKUP_DIR, self.device.device_id))

    def _backups(self) -> list[Path]:
        if not self.backup_dir.is_dir():
            return []
        return sorted(self.backup_dir.glob("*.tar.gz"), key=lambda p: p.stat().st_mtime)

    async def async_find_last_backup(self) -> None:
        """The newest backup already in /config (after a restart)."""
        def newest() -> tuple[Path, float] | None:
            backups = self._backups()
            return (backups[-1], backups[-1].stat().st_mtime) if backups else None

        if found := await self.hass.async_add_executor_job(newest):
            self.last_backup = found[0]
            self.last_backup_at = dt_util.utc_from_timestamp(found[1])

    async def take_backup(self) -> Path:
        """Ask the panel for its archive and keep it, the newest KEEP_BACKUPS."""
        answer = await self.client.request("GET", "/backup", binary=True, timeout=90)
        try:
            blob = base64.b64decode(answer["data"])
        except (KeyError, TypeError, ValueError) as err:
            raise PanelError("the device sent no backup (its link is too old?)") from err
        name = Path(str(answer.get("filename") or "")).name
        if not name.endswith(".tar.gz"):
            name = dt_util.now().strftime("ovos-backup-%Y%m%d-%H%M%S.tar.gz")

        def write() -> Path:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            path = self.backup_dir / name
            path.write_bytes(blob)
            for old in self._backups()[:-KEEP_BACKUPS]:
                old.unlink(missing_ok=True)
            return path

        path = await self.hass.async_add_executor_job(write)
        self.last_backup, self.last_backup_at = path, dt_util.utcnow()
        self.async_update_listeners()
        return path

    async def set_channel(self, channel: str) -> None:
        await self.client.request("POST", "/updates/channel", {"channel": channel})
        self.data["channel"] = {**(self.data.get("channel") or {}), "channel": channel}
        self.async_update_listeners()

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
