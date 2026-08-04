"""Subentry flow for managing OVOS skills — one subentry per installed skill.

Add flow: dropdown of the official catalog (36 skills, confirmed small
enough — see haos-ovos-addons/ovos-skills/DOCS.md), picking one calls that
add-on's /skills/install (fire-and-poll, matching its own async design —
see that repo's DEVELOPER.md for why a blocking call would be wrong here).
"""
from __future__ import annotations

from typing import Any

import requests
import voluptuous as vol
from homeassistant.config_entries import ConfigSubentryFlow, SubentryFlowResult

from .const import DOMAIN, CONF_SKILLS_API_URL
from .shared_config import read_shared_config

REQUEST_TIMEOUT = 10  # catalog fetch / kicking off install — not waiting
                       # for pip itself, which the add-on's own API already
                       # doesn't block on (see its /skills/install design)


def _get_skills_api_url() -> str | None:
    return read_shared_config().get(CONF_SKILLS_API_URL) or None


class SkillSubentryFlowHandler(ConfigSubentryFlow):
    """Handle subentry flow for adding an OVOS skill."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        api_url = await self.hass.async_add_executor_job(_get_skills_api_url)
        if not api_url:
            return self.async_abort(reason="no_api_url")

        catalog = await self.hass.async_add_executor_job(self._fetch_catalog, api_url)
        if catalog is None:
            return self.async_abort(reason="catalog_unreachable")

        skills_by_id = {item["skill_id"]: item for item in catalog}

        if user_input is not None:
            skill = skills_by_id.get(user_input["skill_id"])
            if skill is None:
                return self.async_abort(reason="unknown_skill")

            ok = await self.hass.async_add_executor_job(
                self._start_install, api_url, skill["source"]
            )
            if not ok:
                return self.async_abort(reason="install_request_failed")

            return self.async_create_entry(
                title=skill["name"],
                data={
                    "skill_id": skill["skill_id"],
                    "source": skill["source"],
                    "package_name": skill.get("package_name", ""),
                },
                unique_id=skill["skill_id"],
            )

        schema = vol.Schema(
            {vol.Required("skill_id"): vol.In(
                {sid: item["name"] for sid, item in skills_by_id.items()}
            )}
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    def _fetch_catalog(api_url: str) -> list[dict] | None:
        try:
            resp = requests.get(f"{api_url}/catalog", timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json().get("items", [])
        except requests.RequestException:
            return None

    @staticmethod
    def _start_install(api_url: str, source_url: str) -> bool:
        try:
            resp = requests.post(
                f"{api_url}/skills/install",
                json={"url": source_url},
                timeout=REQUEST_TIMEOUT,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False
