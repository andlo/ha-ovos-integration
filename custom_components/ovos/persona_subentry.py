"""Subentry flow for editing ovos-persona's solver list -- which
question-solver plugins are active, in priority order (persona.json's
own "solvers" field).

Deliberately a one-off action, not a persisting subentry, same reasoning
as voice_subentry.py's autoconfigure flow: there's only ever one
persona configuration to edit here, not multiple repeatable "things"
the way installed skills are. Aborts with a result message on
completion rather than creating an entry that would just sit there.

Deliberately its own, independent API URL (CONF_PERSONA_API_URL, its
own text entity) -- never derived from or assumed alongside
CONF_SKILLS_API_URL/CONF_CORE_API_URL. Raised directly: a person can
genuinely run ovos-persona without ovos-skills, ovos-skills without
ovos-persona, or both. This flow only checks for ovos-persona's own
bridge being reachable, nothing else.

Scope, matching ovos-persona's own api.py: only the "solvers" list
(which plugins run, in what order) is editable here. persona.json's
per-solver sub-objects (enabled flags, API keys) are genuinely nested
config, not attempted here -- see that add-on's DOCS.md for why.
"""
from __future__ import annotations

from typing import Any

import requests
import voluptuous as vol
from homeassistant.config_entries import ConfigSubentryFlow, SubentryFlowResult
from homeassistant.helpers import selector

from .const import CONF_PERSONA_API_URL
from .shared_config import read_shared_config

REQUEST_TIMEOUT = 10


def _get_persona_api_url() -> str | None:
    return read_shared_config().get(CONF_PERSONA_API_URL) or None


class PersonaSubentryFlowHandler(ConfigSubentryFlow):
    """Handle subentry flow for editing ovos-persona's solver list."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        api_url = await self.hass.async_add_executor_job(_get_persona_api_url)
        if not api_url:
            return self.async_abort(reason="no_persona_api_url")

        reachable = await self.hass.async_add_executor_job(self._check_health, api_url)
        if not reachable:
            return self.async_abort(reason="persona_unreachable")

        available = await self.hass.async_add_executor_job(self._fetch_available_solvers, api_url)
        if not available:
            return self.async_abort(reason="no_solvers_found")

        current = await self.hass.async_add_executor_job(self._fetch_current_settings, api_url)
        current_solvers = [s for s in current.get("solvers", []) if s in available]

        if user_input is not None:
            merged = {**current, "solvers": user_input["solvers"]}
            ok = await self.hass.async_add_executor_job(
                self._write_settings, api_url, merged
            )
            if not ok:
                return self.async_abort(reason="settings_write_failed")
            return self.async_abort(
                reason="persona_success",
                description_placeholders={"solvers": ", ".join(user_input["solvers"]) or "none"},
            )

        schema = vol.Schema({
            vol.Required("solvers", default=current_solvers): selector.SelectSelector(
                selector.SelectSelectorConfig(options=available, multiple=True)
            )
        })
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    def _check_health(api_url: str) -> bool:
        try:
            resp = requests.get(f"{api_url}/health", timeout=REQUEST_TIMEOUT)
            return resp.status_code == 200 and resp.json().get("bus_connected") is True
        except requests.RequestException:
            return False

    @staticmethod
    def _fetch_available_solvers(api_url: str) -> list[str]:
        try:
            resp = requests.get(f"{api_url}/available-solvers", timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json().get("solvers", [])
        except requests.RequestException:
            return []

    @staticmethod
    def _fetch_current_settings(api_url: str) -> dict:
        try:
            resp = requests.get(f"{api_url}/settings", timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            return {}

    @staticmethod
    def _write_settings(api_url: str, settings: dict) -> bool:
        try:
            resp = requests.put(f"{api_url}/settings", json=settings, timeout=REQUEST_TIMEOUT)
            return resp.status_code == 200
        except requests.RequestException:
            return False
