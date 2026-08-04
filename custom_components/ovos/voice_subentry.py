"""Subentry flow for running ovos-core's /autoconfigure -- picks TTS/STT
plugin and voice defaults for a chosen language, matching what
`ovos-config autoconfigure` does on a standard OVOS install. See
haos-ovos-addons' DEVELOPER.md "mycroft.conf-as-master" section for why
this writes directly to the shared file via ovos-core's own endpoint
rather than each Wyoming add-on's own options -- confirmed for real, on
hardware, that each Wyoming add-on now reads that shared value as its
own source of truth once written.

Deliberately a one-off action, not a persisting subentry: nothing here
represents an ongoing "thing" the way an installed skill does, so on
completion this aborts with a result message rather than creating an
entry that would just sit there as clutter. Re-run any time via "Add
sub-entry" -> "Autoconfigure voice" again.

Language is a field in this flow, not silently read from the existing
Language text entity -- raised directly in discussion: autoconfigure's
own result already writes back to the shared "lang" key regardless, and
that's the same field the Language entity already reads live (via the
shared-config coordinator), so letting the flow ask for it directly is
both more correct (works for someone autoconfiguring a language other
than what's currently set) and doesn't introduce any new
inconsistency -- the coordinator refresh below picks it up either way.

Reconciliation with fields this integration already manages (language,
system unit): by design, not a gap -- see the coordinator refresh below.

Auto-installing whatever plugin gets chosen was considered and
deliberately NOT built. Confirmed by reading OVOS's own documentation:
plugin selection (autoconfigure) and plugin installation are two
separate steps in OVOS's own official workflow (ovos-docker's own
Wyoming plugin-install docs use a person-edited requirements-style list;
the ovos-installer manual's own advice is to run autoconfigure --help
*after* install and adjust by hand). Also confirmed for real: an OVOS
module name and its actual pip package name aren't reliably the same
("ovos-tts-plugin-phoonnx" the module vs. "phoonnx" the real PyPI
package) -- no general rule exists to derive one from the other safely.
So this flow reports back exactly what's now active, in plain terms,
and leaves adding it to the right add-on's own "Extra pip packages"
field to the person -- the same two-step process OVOS's own tooling
expects.
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

        current_lang = await self.hass.async_add_executor_job(_get_current_lang)

        if user_input is not None:
            lang = user_input["lang"]
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

            if result.get("not_available"):
                return self.async_abort(
                    reason="autoconfigure_nothing_found",
                    description_placeholders={"lang": lang},
                )

            return self.async_abort(
                reason="autoconfigure_success",
                description_placeholders={
                    "lang": lang,
                    "tts_module": result.get("tts_module") or "(unchanged)",
                    "stt_module": result.get("stt_module") or "(unchanged)",
                },
            )

        schema = vol.Schema(
            {
                vol.Required("lang", default=current_lang): str,
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
