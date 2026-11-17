"""Switches (#10): speaker mute, listening (mic), local only, keep screen on."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory

from .bus import CAP_KIOSK, CAP_LOCAL_ONLY, CAP_MIC, CAP_VOLUME, OvosDevice
from . import panel_entities
from .entity import OvosDeviceEntity, setup_capabilities
from .panel import CAP_PANEL


def _entities(device: OvosDevice, cap: str) -> list:
    match cap:
        case "volume":
            return [OvosSpeakerMute(device)]
        case "mic":
            return [OvosListening(device)]
        case "local_only":
            return [OvosLocalOnly(device)]
        case "kiosk":
            return [OvosKeepAwake(device)]
    return []


async def async_setup_entry(hass, entry, add_entities):
    def factory(device: OvosDevice, cap: str) -> list:
        if cap == CAP_PANEL:
            # a switch per skill, as the panel reports them (#15)
            panel_entities.setup_skill_switches(device, add_entities)
            return []
        return _entities(device, cap)
    setup_capabilities(hass, entry, add_entities, factory)


class _OvosSwitch(OvosDeviceEntity, SwitchEntity):
    """on/off is a bus message each way; the device's answer corrects it."""

    attr: str
    invert = False

    def _message(self, on: bool) -> tuple[str, dict]:
        raise NotImplementedError

    @property
    def is_on(self) -> bool | None:
        value = getattr(self.device, self.attr)
        return None if value is None else value != self.invert

    async def _set(self, on: bool) -> None:
        self.device.send(*self._message(on))
        setattr(self.device, self.attr, on != self.invert)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)


class OvosSpeakerMute(_OvosSwitch):
    attr = "speaker_muted"

    def __init__(self, device):
        super().__init__(device, "speaker_mute")

    def _message(self, on):
        return ("mycroft.volume.mute" if on else "mycroft.volume.unmute", {})


class OvosListening(_OvosSwitch):
    """On = the device listens for its wake word (mic not muted)."""

    attr = "mic_muted"
    invert = True

    def __init__(self, device):
        super().__init__(device, "listening")

    def _message(self, on):
        return ("mycroft.mic.unmute" if on else "mycroft.mic.mute", {})


class OvosLocalOnly(_OvosSwitch):
    """ovos-skill-guardian's contract: nothing leaves the device."""

    attr = "local_only"

    def __init__(self, device):
        super().__init__(device, "local_only")

    def _message(self, on):
        return ("ovos.local_only", {"enabled": on})


class OvosKeepAwake(_OvosSwitch):
    """ovos-skill-kiosk's contract: keep the screen on."""

    attr = "keep_awake"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, device):
        super().__init__(device, "keep_awake")

    def _message(self, on):
        return ("ovos.kiosk.keep_awake", {"enabled": on})
