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

Automatic fallback-skill wiring: if ovos-skills-extra is ALSO configured
and reachable, this flow installs skill-ovos-fallback-chatgpt there
(unverified/community skill, so ovos-skills-extra, not the curated
ovos-skills) after saving solver settings -- so ovos-core's own skill
pipeline gets a last-resort fallback to THIS persona server before
giving up entirely, using OVOS's own, native fallback-priority
mechanism rather than HA's conversation agent trying to chain two
separate systems together itself. ovos-persona's own run.sh points the
skill's settings.json at this server (see that add-on's run.sh) --
nothing here needs to know or guess persona's own address.

Automatic, not a toggle -- raised and settled directly: wiring needs no
external API key (a dummy value satisfies the skill's own check), so
there's no real reason to make someone find and flip a separate
setting. Silently skipped, not an error, when ovos-skills-extra isn't
configured -- ovos-persona must keep working standalone (e.g. via HA's
own Ollama integration pointed directly at it) exactly as before.
"""
from __future__ import annotations

from typing import Any

import requests
import voluptuous as vol
from homeassistant.config_entries import ConfigSubentryFlow, SubentryFlowResult
from homeassistant.helpers import selector

import asyncio
import time

from .const import CONF_PERSONA_API_URL, CONF_SKILLS_EXTRA_API_URL
from .shared_config import read_shared_config

REQUEST_TIMEOUT = 10
FALLBACK_SKILL_SOURCE = "skill-ovos-fallback-chatgpt"
FALLBACK_SKILL_ID = "skill-ovos-fallback-chatgpt.openvoiceos"
FALLBACK_INSTALL_POLL_TIMEOUT = 180
FALLBACK_INSTALL_POLL_INTERVAL = 3


def _get_skills_extra_api_url() -> str | None:
    return read_shared_config().get(CONF_SKILLS_EXTRA_API_URL) or None


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
            fallback_note = await self._wire_up_fallback_skill()

            return self.async_abort(
                reason="persona_success",
                description_placeholders={
                    "solvers": ", ".join(user_input["solvers"]) or "none",
                    "fallback_note": fallback_note,
                },
            )

        schema = vol.Schema({
            vol.Required("solvers", default=current_solvers): selector.SelectSelector(
                selector.SelectSelectorConfig(options=available, multiple=True)
            )
        })
        return self.async_show_form(step_id="user", data_schema=schema)

    async def _wire_up_fallback_skill(self) -> str:
        """Install skill-ovos-fallback-chatgpt via ovos-skills-extra, if
        that add-on is configured and reachable -- see module docstring.
        Silent no-op (empty note) if it isn't; ovos-persona must keep
        working standalone.
        """
        extra_url = await self.hass.async_add_executor_job(_get_skills_extra_api_url)
        if not extra_url:
            return ""

        reachable = await self.hass.async_add_executor_job(self._check_health, extra_url)
        if not reachable:
            return ""

        already_installed = await self.hass.async_add_executor_job(
            self._skill_already_installed, extra_url
        )
        if already_installed:
            return " A fallback-to-persona skill is already installed."

        started = await self.hass.async_add_executor_job(
            self._start_fallback_install, extra_url
        )
        if not started:
            return ""

        result = await self._wait_for_fallback_install(extra_url)
        if result is not None and result.get("status") == "complete":
            return " Also installed a fallback-to-persona skill, for when no other skill answers."
        return ""

    async def _wait_for_fallback_install(self, extra_url: str) -> dict | None:
        deadline = time.monotonic() + FALLBACK_INSTALL_POLL_TIMEOUT
        while time.monotonic() < deadline:
            status = await self.hass.async_add_executor_job(
                self._poll_fallback_install, extra_url
            )
            if status is not None and status.get("status") in ("complete", "failed"):
                return status
            await asyncio.sleep(FALLBACK_INSTALL_POLL_INTERVAL)
        return None

    @staticmethod
    def _skill_already_installed(extra_url: str) -> bool:
        try:
            resp = requests.get(f"{extra_url}/skills", timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return any(
                s.get("skill_id") == FALLBACK_SKILL_ID for s in resp.json().get("skills", [])
            )
        except requests.RequestException:
            return False

    @staticmethod
    def _start_fallback_install(extra_url: str) -> bool:
        try:
            resp = requests.post(
                f"{extra_url}/skills/install",
                json={"url": FALLBACK_SKILL_SOURCE},
                timeout=REQUEST_TIMEOUT,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    @staticmethod
    def _poll_fallback_install(extra_url: str) -> dict | None:
        try:
            resp = requests.get(
                f"{extra_url}/skills/install/status",
                params={"key": FALLBACK_SKILL_SOURCE},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                return None
            return resp.json()
        except requests.RequestException:
            return None

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
