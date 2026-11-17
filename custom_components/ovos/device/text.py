"""Text entities for a device: the control panel's language (#15)."""
from __future__ import annotations

from . import panel_entities
from .entity import setup_capabilities


async def async_setup_entry(hass, entry, add_entities):
    setup_capabilities(hass, entry, add_entities, panel_entities.texts)
