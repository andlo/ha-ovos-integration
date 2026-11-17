"""The control panel's settings as entities (#15). See panel.py."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.text import TextEntity, TextMode
from homeassistant.const import EntityCategory
from homeassistant.core import callback

from ..skill_settings import SENSITIVE_NAME_HINTS, prettify_skill_id
from .bus import OvosDevice
from .entity import OvosDeviceEntity
from .panel import CAP_PANEL, PanelCoordinator


def coordinator(device: OvosDevice) -> PanelCoordinator:
    """One per device, made when the first panel entity needs it."""
    if getattr(device, "panel", None) is None:
        device.panel = coord = PanelCoordinator(device.hass, device)
        was = {"available": device.available}

        @callback
        def on_change() -> None:
            # fetch as soon as the device is (back) on
            if device.available and not was["available"]:
                device.hass.async_create_task(coord.async_request_refresh())
            was["available"] = device.available

        device.entry.async_on_unload(device.add_update_listener(on_change))
        if device.available:
            device.hass.async_create_task(coord.async_request_refresh())
    return device.panel


class PanelEntity(OvosDeviceEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, device: OvosDevice, key: str) -> None:
        super().__init__(device, key)
        self.coordinator = coordinator(device)

    @property
    def data(self) -> dict[str, Any]:
        return self.coordinator.data or {}

    @property
    def available(self) -> bool:
        return self.device.available and self.coordinator.last_update_success and bool(self.data)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))


# --- the simple settings (/api/config/quick) --------------------------------

class PanelSelect(PanelEntity, SelectEntity):
    """Units, time and date format, voice, speech to text, wake word, VAD."""

    def __init__(self, device: OvosDevice, name: str, label: str) -> None:
        super().__init__(device, "panel_" + name.replace(".", "_").lower())
        self._field = name
        self._attr_translation_key = None
        self._attr_name = label

    @property
    def _spec(self) -> dict[str, Any]:
        return (self.data.get("quick") or {}).get(self._field) or {}

    @property
    def options(self) -> list[str]:
        options = [str(o) for o in self._spec.get("options") or []]
        current = self._spec.get("effective")
        if current and str(current) not in options:
            options.append(str(current))
        return options or ["-"]

    @property
    def current_option(self) -> str | None:
        value = self._spec.get("effective")
        return None if value is None else str(value)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.set_quick(self._field, option)


class PanelText(PanelEntity, TextEntity):
    """The language (a code such as en-us)."""

    _attr_native_max = 16

    def __init__(self, device: OvosDevice, name: str, label: str) -> None:
        super().__init__(device, "panel_" + name.replace(".", "_").lower())
        self._field = name
        self._attr_translation_key = None
        self._attr_name = label

    @property
    def native_value(self) -> str | None:
        value = ((self.data.get("quick") or {}).get(self._field) or {}).get("effective")
        return None if value is None else str(value)

    async def async_set_value(self, value: str) -> None:
        await self.coordinator.set_quick(self._field, value.strip() or None)


QUICK = {"lang": ("text", "Language"), "system_unit": ("select", "Units"),
         "time_format": ("select", "Time format"), "date_format": ("select", "Date format"),
         "tts.module": ("select", "Voice"), "stt.module": ("select", "Speech to text"),
         "listener.wake_word": ("select", "Wake word"),
         "listener.VAD.module": ("select", "Voice activity detection")}


class PanelChannel(PanelEntity, SelectEntity):
    """The release channel updates come from (alpha, testing, stable)."""

    _attr_icon = "mdi:source-branch"

    def __init__(self, device: OvosDevice) -> None:
        super().__init__(device, "panel_channel")
        self._attr_translation_key = None
        self._attr_name = "Release channel"

    @property
    def available(self) -> bool:
        return super().available and bool(self.data.get("channel"))

    @property
    def options(self) -> list[str]:
        channel = self.data.get("channel") or {}
        options = list(channel.get("channels") or [])
        if channel.get("channel") and channel["channel"] not in options:
            options.append(channel["channel"])
        return options or ["-"]

    @property
    def current_option(self) -> str | None:
        return (self.data.get("channel") or {}).get("channel")

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.set_channel(option)


def selects(device: OvosDevice, cap: str) -> list:
    if cap != CAP_PANEL:
        return []
    return [*(PanelSelect(device, name, label) for name, (kind, label) in QUICK.items()
              if kind == "select"), PanelChannel(device)]


def texts(device: OvosDevice, cap: str) -> list:
    if cap != CAP_PANEL:
        return []
    return [PanelText(device, name, label) for name, (kind, label) in QUICK.items()
            if kind == "text"]


# --- health, updates ---------------------------------------------------------

class PanelProblem(PanelEntity, BinarySensorEntity):
    """On when the bus or one of the essential services doesn't answer."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, device: OvosDevice) -> None:
        super().__init__(device, "panel_problem")

    @property
    def is_on(self) -> bool | None:
        health = self.data.get("health")
        return None if health is None else not health.get("healthy")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        health = self.data.get("health") or {}
        return {"bus": (health.get("bus") or {}).get("reachable"),
                **{s["name"]: s.get("state") for s in health.get("services", []) if "name" in s}}


class PanelUpdates(PanelEntity, SensorEntity):
    """How many OVOS packages have a newer version on the device's channel."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, device: OvosDevice) -> None:
        super().__init__(device, "panel_updates")

    @property
    def native_value(self) -> int | None:
        updates = self.data.get("updates")
        return None if updates is None else updates.get("outdated", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        updates = self.data.get("updates") or {}
        return {"channel": updates.get("channel"),
                "packages": {p["name"]: f'{p.get("installed")} -> {p.get("latest")}'
                             for p in updates.get("packages", []) if p.get("outdated")}}


def binary_sensors(device: OvosDevice, cap: str) -> list:
    return [PanelProblem(device)] if cap == CAP_PANEL else []


def sensors(device: OvosDevice, cap: str) -> list:
    return [PanelUpdates(device), PanelLastBackup(device)] if cap == CAP_PANEL else []


# --- actions -------------------------------------------------------------------

class PanelAction(PanelEntity, ButtonEntity):
    """Restart OVOS' services, reboot (they need the panel's token)."""

    def __init__(self, device: OvosDevice, action: str) -> None:
        super().__init__(device, f"panel_{action}")
        self._action = action

    @property
    def available(self) -> bool:
        return self.device.available

    async def async_press(self) -> None:
        await self.coordinator.client.request("POST", f"/system/{self._action}")


class PanelBackup(PanelEntity, ButtonEntity):
    """The panel's archive of the device's settings, kept in /config/ovos_backups."""

    _attr_icon = "mdi:backup-restore"

    def __init__(self, device: OvosDevice) -> None:
        super().__init__(device, "panel_backup")
        self._attr_translation_key = None
        self._attr_name = "Take backup"

    @property
    def available(self) -> bool:
        return self.device.available

    async def async_press(self) -> None:
        await self.coordinator.take_backup()


class PanelLastBackup(PanelEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, device: OvosDevice) -> None:
        super().__init__(device, "panel_last_backup")
        self._attr_translation_key = None
        self._attr_name = "Last backup"

    @property
    def available(self) -> bool:
        return True     # the files are in HA, whether the device is on or not

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.coordinator.last_backup is None:
            await self.coordinator.async_find_last_backup()
            self.async_write_ha_state()

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.last_backup_at

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        path = self.coordinator.last_backup
        return {"file": str(path)} if path else {}


def buttons(device: OvosDevice, cap: str) -> list:
    if cap != CAP_PANEL:
        return []
    return [PanelAction(device, "restart_services"), PanelAction(device, "reboot"),
            PanelBackup(device)]


# --- skills on/off ---------------------------------------------------------------

class PanelSkill(PanelEntity, SwitchEntity):
    _attr_icon = "mdi:puzzle"

    def __init__(self, device: OvosDevice, skill_id: str) -> None:
        super().__init__(device, f"panel_skill_{skill_id}")
        self._skill = skill_id
        self._attr_translation_key = None
        self._attr_name = prettify_skill_id(skill_id)
        self._attr_extra_state_attributes = {"skill_id": skill_id}

    @property
    def is_on(self) -> bool | None:
        return (self.data.get("enabled") or {}).get(self._skill)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.set_skill_enabled(self._skill, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.set_skill_enabled(self._skill, False)


def setup_skill_switches(device: OvosDevice, add_entities) -> None:
    """A switch per installed skill, added as the panel reports them."""
    coord = coordinator(device)
    added: set[str] = set()

    @callback
    def add_new() -> None:
        new = [s["skill_id"] for s in (coord.data or {}).get("skills", [])
               if s["skill_id"] not in added]
        if new:
            added.update(new)
            add_entities([PanelSkill(device, sid) for sid in new])

    device.entry.async_on_unload(coord.async_add_listener(add_new))
    add_new()


# --- skill settings ---------------------------------------------------------------
# One entity per field of a skill's settingsmeta, as the panel's skill page
# shows them. A skill that has no settingsmeta gets one generated from its
# settings.json; those entities start disabled, since nobody chose to show them.

def _truthy(value: Any) -> bool:
    return value is True or str(value).lower() in ("true", "1", "yes", "on")


class PanelSkillSetting(PanelEntity):
    def __init__(self, device: OvosDevice, skill_id: str, field: dict[str, Any],
                 generated: bool) -> None:
        super().__init__(device, f"panel_setting_{skill_id}_{field['name']}")
        self._skill = skill_id
        self._field = field
        self._attr_translation_key = None
        self._attr_name = f"{prettify_skill_id(skill_id)}: {field['label']}"
        self._attr_entity_registry_enabled_default = not generated
        self._attr_extra_state_attributes = {"skill_id": skill_id, "setting": field["name"]}

    @property
    def _info(self) -> dict[str, Any]:
        return self.coordinator.settings.get(self._skill) or {}

    @property
    def _value(self) -> Any:
        settings = self._info.get("settings") or {}
        return settings.get(self._field["name"], self._field.get("default"))

    @property
    def available(self) -> bool:
        return self.device.available and bool(self._info)

    async def _write(self, value: Any) -> None:
        await self.coordinator.set_skill_setting(self._skill, self._field["name"], value)


class PanelSettingSwitch(PanelSkillSetting, SwitchEntity):
    @property
    def is_on(self) -> bool | None:
        return None if self._value is None else _truthy(self._value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._write(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._write(False)


class PanelSettingNumber(PanelSkillSetting, NumberEntity):
    # settingsmeta has no range; the panel's form doesn't either
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = -1_000_000
    _attr_native_max_value = 1_000_000

    @property
    def native_step(self) -> float:
        return 1 if isinstance(self._value, int) or self._value is None else 0.01

    @property
    def native_value(self) -> float | None:
        try:
            return None if self._value in (None, "") else float(self._value)
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        await self._write(int(value) if value.is_integer() and not isinstance(self._value, float)
                          else value)


class PanelSettingText(PanelSkillSetting, TextEntity):
    """A text setting. A secret (a password field, or a name with key,
    token, secret or password in it) can be set from HA but is never read
    back: an entity's state is stored in the recorder and visible to anyone
    who can see the device."""

    _attr_native_max = 255

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        name = self._field["name"].lower()
        self._secret = (self._field["type"] == "password"
                        or any(h in name for h in SENSITIVE_NAME_HINTS))
        if self._secret:
            self._attr_mode = TextMode.PASSWORD
            self._attr_icon = "mdi:key-variant"

    @property
    def native_value(self) -> str | None:
        if self._secret or self._value is None:
            return None
        return str(self._value)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = dict(super().extra_state_attributes or {})
        if self._secret:
            attrs["is_set"] = bool(self._value)
        return attrs

    async def async_set_value(self, value: str) -> None:
        await self._write(value)


class PanelSettingSelect(PanelSkillSetting, SelectEntity):
    @property
    def options(self) -> list[str]:
        return [label for label, _ in self._field["options"]]

    @property
    def current_option(self) -> str | None:
        value = None if self._value is None else str(self._value)
        return next((label for label, v in self._field["options"] if v == value), None)

    async def async_select_option(self, option: str) -> None:
        value = next(v for label, v in self._field["options"] if label == option)
        await self._write(value)


SETTING_ENTITIES = {"switch": PanelSettingSwitch, "number": PanelSettingNumber,
                    "text": PanelSettingText, "select": PanelSettingSelect}


def setup_skill_settings(device: OvosDevice, add_entities, kind: str) -> None:
    """The skills' settings of one kind, added as the panel reports them."""
    coord = coordinator(device)
    if kind in coord.setting_kinds:     # the capability can be announced again
        return
    coord.setting_kinds.add(kind)
    added: set[tuple[str, str]] = set()
    cls = SETTING_ENTITIES[kind]

    @callback
    def add_new() -> None:
        new = []
        for sid, info in coord.settings.items():
            for field in info["fields"]:
                if field["kind"] == kind and (sid, field["name"]) not in added:
                    added.add((sid, field["name"]))
                    new.append(cls(device, sid, field, info["generated"]))
        if new:
            add_entities(new)

    device.entry.async_on_unload(coord.async_add_listener(add_new))
    add_new()
