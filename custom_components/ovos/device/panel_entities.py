"""The control panel's settings as entities (#15). See panel.py."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback

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


def selects(device: OvosDevice, cap: str) -> list:
    if cap != CAP_PANEL:
        return []
    return [PanelSelect(device, name, label) for name, (kind, label) in QUICK.items()
            if kind == "select"]


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
    return [PanelUpdates(device)] if cap == CAP_PANEL else []


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


def buttons(device: OvosDevice, cap: str) -> list:
    if cap != CAP_PANEL:
        return []
    return [PanelAction(device, "restart_services"), PanelAction(device, "reboot")]


# --- skills on/off ---------------------------------------------------------------

class PanelSkill(PanelEntity, SwitchEntity):
    _attr_icon = "mdi:puzzle"

    def __init__(self, device: OvosDevice, skill_id: str) -> None:
        super().__init__(device, f"panel_skill_{skill_id}")
        self._skill = skill_id
        self._attr_translation_key = None
        self._attr_name = skill_id

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
