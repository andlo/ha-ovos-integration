"""Subentry flow for managing OVOS skills — one subentry per installed skill.

Add flow: dropdown of the official catalog (36 skills, confirmed small
enough — see haos-ovos-addons/ovos-skills/DOCS.md), picking one calls that
add-on's /skills/install (fire-and-poll, matching its own async design —
see that repo's DEVELOPER.md for why a blocking call would be wrong here).
Dropdown labels fold in a short description — HA's select selector has no
secondary/subtitle line (confirmed against the selector docs), so a
one-line "Name — description" is the only way to show more than the bare
name without a custom frontend card, out of scope here.

Reconfigure flow: edits a skill's settings.json, but ONLY when there's a
settingsmeta.json with exclusively confirmed-mappable fields (currently
just 'checkbox') to build a real form from — not every skill ships one
(confirmed for real: date-time has it, fallback-chatgpt doesn't). Rather
than fall back to a raw-JSON box for everything else, reconfigure simply
isn't offered for those skills: a clean "no settings" boundary, matching
what a skill without settingsmeta actually is — not configurable through
this UI, not a lesser version of one that is.
"""
from __future__ import annotations

import logging
from typing import Any

import requests
import voluptuous as vol
from homeassistant.config_entries import ConfigSubentryFlow, SubentryFlowResult

from .const import DOMAIN, CONF_SKILLS_API_URL
from .shared_config import read_shared_config

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10  # catalog fetch / kicking off install — not waiting
                       # for pip itself, which the add-on's own API already
                       # doesn't block on (see its /skills/install design)

MAX_DESCRIPTION_LEN = 60


def _get_skills_api_url() -> str | None:
    return read_shared_config().get(CONF_SKILLS_API_URL) or None


def _dropdown_label(item: dict) -> str:
    desc = (item.get("description") or "").strip().split("\n")[0]
    if not desc:
        return item["name"]
    if len(desc) > MAX_DESCRIPTION_LEN:
        desc = desc[:MAX_DESCRIPTION_LEN].rstrip() + "…"
    return f"{item['name']} — {desc}"


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
                {sid: _dropdown_label(item) for sid, item in skills_by_id.items()}
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
        _LOGGER.warning(
            "SETTINGSMETA DEBUG: subentry.data=%s, skill_id=%r, package_name=%r",
            dict(subentry.data), skill_id, package_name,
        )
        meta = await self.hass.async_add_executor_job(
            self._fetch_settingsmeta, api_url, skill_id, package_name
        )

        mappable = bool(
            meta and meta.get("has_settingsmeta") and meta["fields"]
            and all(f.get("type") == "checkbox" for f in meta["fields"])
        )
        if not mappable:
            # No settingsmeta at all, or one with field types we haven't
            # confirmed how to render (e.g. 'select') — a clean "not
            # configurable through this UI" boundary rather than a raw
            # JSON box standing in for "we're not sure what this is".
            return self.async_abort(reason="no_settings_available")

        current = await self.hass.async_add_executor_job(
            self._fetch_current_settings, api_url, skill_id
        )
        return await self.async_step_reconfigure_fields(
            user_input, api_url=api_url, skill_id=skill_id,
            fields=meta["fields"], current=current,
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

    @staticmethod
    def _fetch_settingsmeta(api_url: str, skill_id: str, package_name: str) -> dict | None:
        url = f"{api_url}/skills/{skill_id}/settingsmeta"
        try:
            resp = requests.get(url, params={"package_name": package_name}, timeout=REQUEST_TIMEOUT)
            _LOGGER.warning(
                "SETTINGSMETA DEBUG: GET %s?package_name=%s -> %s %s",
                url, package_name, resp.status_code, resp.text[:300],
            )
            if resp.status_code != 200:
                return None
            return resp.json()
        except requests.RequestException as exc:
            _LOGGER.warning("SETTINGSMETA DEBUG: request to %s failed: %s", url, exc)
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
