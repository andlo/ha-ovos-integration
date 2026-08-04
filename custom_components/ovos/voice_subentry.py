"""Subentry flow for running ovos-core's /autoconfigure -- picks TTS/STT
plugin and voice defaults for the language already set (see const.py's
CONF_LANG / text.py's OvosLanguageText), matching what `ovos-config
autoconfigure` does on a standard OVOS install. See haos-ovos-addons'
DEVELOPER.md "mycroft.conf-as-master" section for why this writes
directly to the shared file via ovos-core's own endpoint rather than
each Wyoming add-on's own options -- confirmed for real, on hardware,
that each Wyoming add-on now reads that shared value as its own source
of truth once written.

Deliberately a one-off action, not a persisting subentry: nothing here
represents an ongoing "thing" the way an installed skill does, so on
completion this aborts with a result message (what changed) rather than
creating an entry that would just sit there as clutter. Re-run any time
via "Add sub-entry" -> "Autoconfigure voice" again -- each run picks
fresh, based on the language set at that time.

Reconciliation with fields this integration already manages (language,
system unit): by design, not a gap. ovos-core's own autoconfigure also
touches lang/system_unit/date-time-format keys in the shared file
(confirmed by testing directly), and since those are already read live
from the same shared-config coordinator (text.language, select.
system_unit), requesting a coordinator refresh after this call is
enough for them to reflect the new values -- no separate sync code
needed, this *is* what "shared file is master" means.
"""
from __future__ import annotations

from typing import Any

import requests
import voluptuous as vol
from homeassistant.config_entries import ConfigSubentryFlow, SubentryFlowResult

from .const import DOMAIN, CONF_CORE_API_URL, CONF_LANG
from .shared_config import read_shared_config

REQUEST_TIMEOUT = 30  # autoconfigure runs a real subprocess (ovos-config
                       # autoconfigure) on ovos-core's side, not instant
                       # -- more headroom than the skill-catalog calls.

MODE_OPTIONS = ["hybrid", "online", "offline"]
VOICE_OPTIONS = ["unspecified", "male", "female"]


def _get_core_api_url() -> str | None:
    return read_shared_config().get(CONF_CORE_API_URL) or None


def _get_current_lang() -> str:
    return read_shared_config().get(CONF_LANG, "en-us")


class AutoconfigureSubentryFlowHandler(ConfigSubentryFlow):
    """Handle subentry flow for running ovos-core's /autoconfigure."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        api_url = await self.hass.async_add_executor_job(_get_core_api_url)
        if not api_url:
            return self.async_abort(reason="no_core_api_url")

        # Explicit boundary, decided deliberately (see DEVELOPER.md):
        # this step exists so someone without ovos-core installed sees a
        # clear explanation rather than a failed request further in.
        reachable = await self.hass.async_add_executor_job(self._check_health, api_url)
        if not reachable:
            return self.async_abort(reason="core_unreachable")

        if user_input is not None:
            lang = await self.hass.async_add_executor_job(_get_current_lang)
            mode = user_input["mode"]
            voice = user_input["voice"]
            body = {
                "lang": lang,
                "online": mode == "online",
                "offline": mode == "offline",
                "male": voice == "male",
                "female": voice == "female",
            }
            result = await self.hass.async_add_executor_job(
                self._run_autoconfigure, api_url, body
            )
            if result is None:
                return self.async_abort(reason="autoconfigure_failed")

            coordinator = self.hass.data[DOMAIN][self._get_entry().entry_id]
            await coordinator.async_request_refresh()

            changed = result.get("changed_keys", {})
            summary = ", ".join(sorted(changed.keys())) or "nothing"
            return self.async_abort(
                reason="autoconfigure_success",
                description_placeholders={"lang": lang, "changed": summary},
            )

        schema = vol.Schema(
            {
                vol.Required("mode", default="hybrid"): vol.In(MODE_OPTIONS),
                vol.Required("voice", default="unspecified"): vol.In(VOICE_OPTIONS),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    def _check_health(api_url: str) -> bool:
        try:
            resp = requests.get(f"{api_url}/health", timeout=REQUEST_TIMEOUT)
            return resp.status_code == 200 and resp.json().get("bus_connected") is True
        except requests.RequestException:
            return False

    @staticmethod
    def _run_autoconfigure(api_url: str, body: dict) -> dict | None:
        try:
            resp = requests.post(f"{api_url}/autoconfigure", json=body, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                return None
            return resp.json()
        except requests.RequestException:
            return None
