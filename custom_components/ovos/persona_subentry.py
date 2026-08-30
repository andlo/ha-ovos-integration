"""Subentry flow for the one "OpenVoiceOS Persona" device.

Purely structural -- no user interaction, no choices. Same reasoning
as core_settings_subentry.py's own docstring: exists only so this
device gets its own named section on the integration's page, instead
of Home Assistant's own generic "devices not belonging to a subentry"
heading.

This REPLACES what used to be here: an interactive one-off flow for
editing ovos-persona's own solver list (and, as a side effect, wiring
up a fallback skill via ovos-skills-extra). That functionality moved
to live entities instead -- see const.py's own PERSONA_DEVICE_ID
comment for the full reasoning agreed directly: a text entity for the
solver list (text.py's own OvosPersonaSolversText), a button for the
fallback-skill action (button.py's own OvosPersonaFallbackSkillButton,
kept as a button rather than an automatic side effect of editing the
solver list, since a fresh install can take up to 3 minutes), and a
binary sensor for reachability (binary_sensor.py's own
OvosPersonaReachableBinarySensor) -- entity for data, button for the
one-off action, sensor for status, no flow left.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigSubentryFlow, SubentryFlowResult


class PersonaSubentryFlowHandler(ConfigSubentryFlow):
    """Creates the single "Persona" subentry -- no user input, no
    branching, called exactly once (see __init__.py).
    """

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return self.async_create_entry(
            title="Persona",
            data={},
            unique_id="persona",
        )
