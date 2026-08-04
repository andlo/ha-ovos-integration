"""Subentry flow for managing OVOS skills — one subentry per installed skill.

Add flow: dropdown of the official catalog (36 skills, confirmed small
enough — see haos-ovos-addons/ovos-skills/DOCS.md), picking one calls that
add-on's /skills/install (fire-and-poll, matching its own async design —
see that repo's DEVELOPER.md for why a blocking call would be wrong here).

Reconfigure flow: edits a skill's settings.json. Not every skill ships a
settingsmeta.json describing its fields — confirmed for real by installing
two different skills, one had it, one didn't (see haos-ovos-addons/
ovos-skills/DOCS.md). When it exists, only the confirmed 'checkbox' field
type gets a real form control; everything else, and skills with no
settingsmeta at all, fall back to a single raw-JSON text field — scoped
down deliberately rather than guessing at unconfirmed field types like
'select'.
"""
from __future__ import annotations

import json
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

    # --- reconfigure: edit an existing skill's settings.json ---

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        api_url = await self.hass.async_add_executor_job(_get_skills_api_url)
        if not api_url:
            return self.async_abort(reason="no_api_url")

        skill_id = subentry.data["skill_id"]
        package_name = subentry.data.get("package_name", "")
        meta = await self.hass.async_add_executor_job(
            self._fetch_settingsmeta, api_url, skill_id, package_name
        )
        current = await self.hass.async_add_executor_job(
            self._fetch_current_settings, api_url, skill_id
        )

        if meta and meta.get("has_settingsmeta") and all(
            f.get("type") == "checkbox" for f in meta["fields"]
        ) and meta["fields"]:
            # Every field is a confirmed, mappable type — real form.
            return await self.async_step_reconfigure_fields(
                user_input, api_url=api_url, skill_id=skill_id,
                fields=meta["fields"], current=current,
            )

        # No settingsmeta, or it has field types we haven't confirmed how
        # to map yet (e.g. 'select') — raw JSON, same pattern used
        # elsewhere in this project for exactly this kind of gap.
        return await self.async_step_reconfigure_json(
            user_input, api_url=api_url, skill_id=skill_id, current=current,
        )

    async def async_step_reconfigure_fields(
        self,
        user_input: dict[str, Any] | None,
        *,
        api_url: str,
        skill_id: str,
        fields: list[dict],
        current: dict,
    ) -> SubentryFlowResult:
        if user_input is not None:
            ok = await self.hass.async_add_executor_job(
                self._write_settings, api_url, skill_id, user_input
            )
            if not ok:
                return self.async_abort(reason="settings_write_failed")
            return self.async_update_and_abort(self._get_entry(), self._get_reconfigure_subentry())

        schema_dict = {}
        for field in fields:
            name = field["name"]
            existing = current.get(name, field.get("value"))
            # settingsmeta's own "value" is a string ("false"/"true"),
            # confirmed for real — normalize either that or a properly
            # typed value already in settings.json to an actual bool.
            default = str(existing).strip().lower() == "true"
            schema_dict[vol.Optional(name, default=default)] = bool

        return self.async_show_form(
            step_id="reconfigure_fields", data_schema=vol.Schema(schema_dict)
        )

    async def async_step_reconfigure_json(
        self,
        user_input: dict[str, Any] | None,
        *,
        api_url: str,
        skill_id: str,
        current: dict,
    ) -> SubentryFlowResult:
        if user_input is not None:
            try:
                parsed = json.loads(user_input["raw_json"])
            except json.JSONDecodeError:
                return self.async_show_form(
                    step_id="reconfigure_json",
                    data_schema=vol.Schema(
                        {vol.Required("raw_json", default=user_input["raw_json"]): str}
                    ),
                    errors={"raw_json": "invalid_json"},
                )
            ok = await self.hass.async_add_executor_job(
                self._write_settings, api_url, skill_id, parsed
            )
            if not ok:
                return self.async_abort(reason="settings_write_failed")
            return self.async_update_and_abort(self._get_entry(), self._get_reconfigure_subentry())

        schema = vol.Schema(
            {vol.Required("raw_json", default=json.dumps(current, indent=2)): str}
        )
        return self.async_show_form(step_id="reconfigure_json", data_schema=schema)

    @staticmethod
    def _fetch_settingsmeta(api_url: str, skill_id: str, package_name: str) -> dict | None:
        try:
            resp = requests.get(
                f"{api_url}/skills/{skill_id}/settingsmeta",
                params={"package_name": package_name},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                return None
            return resp.json()
        except requests.RequestException:
            return None

    @staticmethod
    def _fetch_current_settings(api_url: str, skill_id: str) -> dict:
        try:
            resp = requests.get(f"{api_url}/skills/{skill_id}/settings", timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            return {}

    @staticmethod
    def _write_settings(api_url: str, skill_id: str, settings: dict) -> bool:
        try:
            resp = requests.put(
                f"{api_url}/skills/{skill_id}/settings",
                json=settings,
                timeout=REQUEST_TIMEOUT,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False
