"""Text entities for a device: the control panel's language, and the
skills' text settings (#15)."""
from __future__ import annotations

from . import panel_entities
from .bus import OvosDevice
from .entity import setup_capabilities
from .panel import CAP_PANEL


async def async_setup_entry(hass, entry, add_entities):
    def factory(device: OvosDevice, cap: str) -> list:
        if cap == CAP_PANEL:
            panel_entities.setup_skill_settings(device, add_entities, "text")
        return panel_entities.texts(device, cap)
    setup_capabilities(hass, entry, add_entities, factory)
