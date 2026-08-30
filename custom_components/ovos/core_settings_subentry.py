"""Subentry flow for the one "OpenVoiceOS Core Settings" device.

Purely structural -- no user interaction, no choices. Exists only so
this device gets its own named section on the integration's page
(Settings -> Devices & services -> OpenVoiceOS), the same as skill/
persona/voice subentries already get, instead of falling under HA's
own generic "devices not belonging to a subentry" heading -- confirmed
a real, reported UX gap: that heading is HA's own core UI string for
config-entry-level devices, not something a custom integration can
rename, but a device CAN move out from under it by belonging to its
own subentry instead.

Auto-created exactly once at startup (see __init__.py's own
_async_create_core_settings_subentry) via the same shape-detection
entry point skill_subentry.py's own async_step_user already uses for
its auto-import path -- confirmed directly against this HA version's
own config_entries.py that ConfigSubentryFlow.async_create_entry hard-
requires self.source == SOURCE_USER, so even a fully automatic,
no-input creation like this one still has to go through
async_step_user, not some SOURCE_IMPORT-style path (subentries have no
equivalent). Unlike skill_subentry.py, there's no interactive branch
at all here -- this flow only ever does the one thing.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigSubentryFlow, SubentryFlowResult


class CoreSettingsSubentryFlowHandler(ConfigSubentryFlow):
    """Creates the single "Core Settings" subentry -- no user input,
    no branching, called exactly once (see __init__.py).
    """

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return self.async_create_entry(
            title="Core Settings",
            data={},
            unique_id="core_settings",
        )
