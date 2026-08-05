"""Subentry flow for managing OVOS skills — one subentry per installed skill.

Add flow: two steps, not one. A single dropdown with "Name — description"
per option (36 catalog entries) turned out genuinely hard to scan in
practice — each option wrapping onto multiple visual lines in the actual
HA frontend, confirmed by screenshot, not just a guess. Step one is a
compact, name-only dropdown; step two shows the selected skill's full
description as plain text before kicking off the install. Keeps the list
scannable without losing the description entirely.

Reconfigure flow: edits a skill's settings.json, using two layers:

1. settingsmeta.json, when present and exclusively 'checkbox' fields —
   the only field type confirmed how to map safely so far. Not every
   skill ships one (confirmed for real: date-time has it, many others
   don't).

2. Falling back to settings.json's OWN shape when there's no usable
   settingsmeta. Confirmed by reading Mycroft's own skill-settings
   documentation: settingsmeta.json was built specifically to upload a
   skill's settings schema to the old home.mycroft.ai backend, so a
   web account page could render a form for it — a backend OVOS
   explicitly doesn't require (see haos-ovos-addons' DEVELOPER.md).
   settings.json itself, in contrast, is created automatically the
   moment a skill loads at all, with or without any settingsmeta.
   That means settings.json's own values — a bool, a number, a string
   — already tell us the shape of a real form (checkbox / number /
   text), no metadata file needed. This is more aligned with a
   backend-less setup than leaning on settingsmeta ever was, not a
   workaround for its absence. Nested dicts/lists and internal keys
   (leading "__", e.g. "__mycroft_skill_firstrun") are skipped —
   editing those safely isn't confirmed, so they're left untouched
   rather than guessed at.

   For this to have anything to read, the skill needs to have loaded at
   least once — ovos-skills' own /skills/install now hot-launches every
   newly-installed skill regardless of the install job's own (unreliable
   — see its api.py) reported status, specifically so a freshly-installed
   skill gets a chance to write its own settings.json before someone
   opens this form.

   Field-name heuristic: a name containing "key", "token", "secret", or
   "password" renders as a masked password input (HA's own TextSelector
   password mode) rather than plain text — cheap, imperfect, but a
   sensible default for the exact kind of value (API keys) this layer
   exists for.

Writing back: always merges into the skill's FULL current settings.json
(fetched fresh, not just what's on the form) rather than replacing it
outright — skipped/internal keys survive a save instead of being
silently dropped.

If neither layer has anything usable, reconfigure isn't offered at all:
a clean "no settings available" boundary, matching what a skill without
either really is — not configurable through this UI, not a lesser
version of one that is.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import requests
import voluptuous as vol
from homeassistant.config_entries import ConfigSubentryFlow, SubentryFlowResult
from homeassistant.helpers import selector

from .const import DOMAIN, CONF_SKILLS_API_URL
from .shared_config import read_shared_config

REQUEST_TIMEOUT = 10  # catalog fetch / kicking off install — not waiting
                       # for pip itself, which the add-on's own API already
                       # doesn't block on (see its /skills/install design)

# A fresh venv + full dependency install can genuinely take 1-2 minutes
# on real hardware (confirmed this session) -- generous but bounded.
INSTALL_POLL_TIMEOUT = 180
INSTALL_POLL_INTERVAL = 3

SENSITIVE_NAME_HINTS = ("key", "token", "secret", "password")


def _get_skills_api_url() -> str | None:
    return read_shared_config().get(CONF_SKILLS_API_URL) or None


def _infer_fields_from_settings(current: dict) -> list[dict]:
    """Build a settingsmeta-shaped field list directly from settings.json's
    own values, for skills that have no usable settingsmeta.json (see
    module docstring). Only top-level primitives are considered safely
    inferable; nested dicts/lists are skipped rather than guessed at,
    and "__"-prefixed keys are OVOS's own internal bookkeeping (e.g.
    "__mycroft_skill_firstrun"), not something a person should edit.
    """
    fields = []
    for name, value in current.items():
        if name.startswith("__") or isinstance(value, (dict, list)):
            continue
        if isinstance(value, bool):
            ftype = "checkbox"
        elif isinstance(value, (int, float)):
            ftype = "number"
        elif any(hint in name.lower() for hint in SENSITIVE_NAME_HINTS):
            ftype = "password"
        else:
            ftype = "text"
        fields.append({"name": name, "type": ftype, "value": value})
    return fields


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

        self._skills_by_id = {item["skill_id"]: item for item in catalog}

        if user_input is not None:
            skill = self._skills_by_id.get(user_input["skill_id"])
            if skill is None:
                return self.async_abort(reason="unknown_skill")
            self._selected_skill = skill
            return await self.async_step_confirm()

        # Name-only, sorted — a "Name — description" label per option was
        # confirmed genuinely hard to scan across 36 entries (each
        # wrapping onto multiple lines in the real frontend). The
        # description shows on the next step instead.
        options = sorted(
            self._skills_by_id.items(), key=lambda kv: kv[1]["name"].lower()
        )
        schema = vol.Schema(
            {vol.Required("skill_id"): vol.In({sid: item["name"] for sid, item in options})}
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        skill = self._selected_skill
        api_url = await self.hass.async_add_executor_job(_get_skills_api_url)

        if user_input is not None:
            ok = await self.hass.async_add_executor_job(
                self._start_install, api_url, skill["source"]
            )
            if not ok:
                return self.async_abort(reason="install_request_failed")

            # Wait for the real result instead of firing-and-forgetting --
            # confirmed for real this session: the catalog's own
            # skill_id doesn't reliably match what a skill actually
            # registers as at runtime (ovos-skills' entry_points-based
            # discovery, e.g. "skill-ovos-date-time..." in the catalog
            # vs. the real "ovos-skill-date-time..."), so creating the
            # subentry with the catalog's guess silently broke
            # settingsmeta/settings lookups for every skill installed
            # this way. This also stops a skill that never actually
            # started (like an earlier real case, a dependency conflict
            # that left the skill installed but never running) from
            # getting a subentry that implies it's usable.
            result = await self._wait_for_install(api_url, skill["source"])
            if result is None:
                return self.async_abort(reason="install_timed_out")
            if result.get("status") != "complete":
                return self.async_abort(
                    reason="install_failed",
                    description_placeholders={"error": result.get("error", "unknown error")},
                )

            real_skill_id = result["skill_id"]
            return self.async_create_entry(
                title=skill["name"],
                data={
                    "skill_id": real_skill_id,
                    "source": skill["source"],
                    "package_name": skill.get("package_name", ""),
                },
                unique_id=real_skill_id,
            )

        description = (skill.get("description") or "").strip() or "No description available."
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "name": skill["name"],
                "description": description,
            },
        )

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

    async def _wait_for_install(self, api_url: str, source_url: str) -> dict | None:
        """Poll /skills/install/status until it reports complete/failed,
        or None on timeout. See async_step_confirm for why this matters
        now (the confirmed-real skill_id only exists once this
        finishes).
        """
        deadline = time.monotonic() + INSTALL_POLL_TIMEOUT
        while time.monotonic() < deadline:
            status = await self.hass.async_add_executor_job(
                self._poll_status, api_url, source_url
            )
            if status is not None and status.get("status") in ("complete", "failed"):
                return status
            await asyncio.sleep(INSTALL_POLL_INTERVAL)
        return None

    @staticmethod
    def _poll_status(api_url: str, key: str) -> dict | None:
        try:
            resp = requests.get(
                f"{api_url}/skills/install/status", params={"key": key}, timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                return None
            return resp.json()
        except requests.RequestException:
            return None

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

        mappable = bool(
            meta and meta.get("has_settingsmeta") and meta["fields"]
            and all(f.get("type") == "checkbox" for f in meta["fields"])
        )

        current = await self.hass.async_add_executor_job(
            self._fetch_current_settings, api_url, skill_id
        )

        if mappable:
            fields = meta["fields"]
        else:
            # No settingsmeta, or one with field types not yet confirmed
            # mappable — fall back to settings.json's own shape (see
            # module docstring). If the skill has never loaded, this is
            # legitimately empty; nothing to build a form from either way.
            fields = _infer_fields_from_settings(current)

        if not fields:
            return self.async_abort(reason="no_settings_available")

        return await self.async_step_reconfigure_fields(
            user_input, api_url=api_url, skill_id=skill_id,
            fields=fields, current=current,
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
            # Merge into the FULL current settings, not just what's on
            # this form — skipped/internal keys (nested values, "__"
            # bookkeeping) survive a save instead of being silently
            # dropped by a naive overwrite.
            merged = {**current, **user_input}
            ok = await self.hass.async_add_executor_job(
                self._write_settings, api_url, skill_id, merged
            )
            if not ok:
                return self.async_abort(reason="settings_write_failed")
            return self.async_update_and_abort(self._get_entry(), self._get_reconfigure_subentry())

        schema_dict = {}
        for field in fields:
            name = field["name"]
            ftype = field.get("type", "checkbox")
            existing = current.get(name, field.get("value"))

            if ftype == "checkbox":
                # settingsmeta's own "value" is a string ("false"/"true")
                # when it's the source; settings.json's own bool needs no
                # such normalization — str() first handles both uniformly.
                default = str(existing).strip().lower() == "true"
                schema_dict[vol.Optional(name, default=default)] = bool
            elif ftype == "number":
                try:
                    default = float(existing) if existing not in (None, "") else 0
                except (TypeError, ValueError):
                    default = 0
                schema_dict[vol.Optional(name, default=default)] = vol.Coerce(float)
            elif ftype == "password":
                schema_dict[vol.Optional(name, default=str(existing or ""))] = (
                    selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    )
                )
            else:  # text
                schema_dict[vol.Optional(name, default=str(existing or ""))] = str

        return self.async_show_form(
            step_id="reconfigure_fields", data_schema=vol.Schema(schema_dict)
        )

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
