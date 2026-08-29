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

from .const import DOMAIN, CONF_SKILLS_API_URL, CONF_SKILLS_EXTRA_API_URL
from .shared_config import read_shared_config
from .skill_settings import (
    get_skills_api_url as _get_skills_api_url,
    get_skills_extra_api_url as _get_skills_extra_api_url,
    api_url_for_source_type as _api_url_for_source_type,
    resolve_fields,
    write_settings as _write_settings,
    fetch_current_settings as _fetch_current_settings,
)

REQUEST_TIMEOUT = 10  # catalog fetch / kicking off install — not waiting
                       # for pip itself, which the add-on's own API already
                       # doesn't block on (see its /skills/install design)

# A fresh venv + full dependency install can genuinely take 1-2 minutes
# on real hardware (confirmed this session) -- generous but bounded.
INSTALL_POLL_TIMEOUT = 180
INSTALL_POLL_INTERVAL = 3


class SkillSubentryFlowHandler(ConfigSubentryFlow):
    """Handle subentry flow for adding an OVOS skill.

    Two sources, chosen as the very first step -- not two separate
    "Add skill" menu entries. A two-entry split ("Skill" / "Skill
    (Extra)") was considered and rejected the same way persona/voice
    subentries already reject similar splits elsewhere in this
    integration: HA gives every registered subentry type its own
    visible "Add [type]" menu entry, and two near-identical labels for
    what's really one decision (which source?) is worse than asking
    that decision explicitly inside a single flow. Matches
    ovos-skills-extra's own DOCS.md, which already describes this as
    "choose Extra instead of the curated catalog" -- this flow is what
    makes that real.
    """

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        if user_input is not None:
            if user_input["source_type"] == "extra":
                return await self.async_step_extra()
            return await self.async_step_curated()

        schema = vol.Schema({
            vol.Required("source_type", default="curated"): vol.In({
                "curated": "Curated catalog (verified to work here)",
                "extra": "Extra (any PyPI package or git URL, unverified)",
            })
        })
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_curated(
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
        return self.async_show_form(step_id="curated", data_schema=schema)

    async def async_step_extra(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """No catalog, no description, no confirm step -- just install
        whatever was typed, exactly as given (see ovos-skills-extra's
        own DOCS.md: "no PyPI-vs-git preference logic ... installed
        exactly as given"). Uses ovos-skills-extra's own API URL, a
        genuinely separate add-on/setting from the curated one.
        """
        api_url = await self.hass.async_add_executor_job(_get_skills_extra_api_url)
        if not api_url:
            return self.async_abort(reason="no_extra_api_url")

        if user_input is not None:
            source = user_input["source"].strip()

            ok = await self.hass.async_add_executor_job(self._start_install, api_url, source)
            if not ok:
                return self.async_abort(reason="install_request_failed")

            result = await self._wait_for_install(api_url, source)
            if result is None:
                return self.async_abort(reason="install_timed_out")
            if result.get("status") != "complete":
                return self.async_abort(
                    reason="install_failed",
                    description_placeholders={"error": result.get("error", "unknown error")},
                )

            real_skill_id = result["skill_id"]
            return self.async_create_entry(
                title=real_skill_id,  # no catalog "name" to show for an extra install
                data={
                    "skill_id": real_skill_id,
                    "source": source,
                    "package_name": "",
                    "source_type": "extra",
                },
                unique_id=real_skill_id,
            )

        schema = vol.Schema({vol.Required("source"): str})
        return self.async_show_form(step_id="extra", data_schema=schema)

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        skill = self._selected_skill
        api_url = await self.hass.async_add_executor_job(_get_skills_api_url)

        if user_input is not None:
            # Prefer the catalog's own package_name over its source
            # (git URL) when both are given -- confirmed for real, this
            # session: deriving a PyPI candidate FROM the git URL
            # (ovos-skills' own _repo_name_from_git_url) doesn't always
            # match the real PyPI name (skill-ovos-stop's repo name vs.
            # its real package "ovos-skill-stop"), so installing via the
            # bare source URL silently fell back to a git/dev-branch
            # version missing a transitive dependency
            # (ModuleNotFoundError: ovos_plugin_manager). This
            # integration's own catalog already carries the
            # CONFIRMED-correct PyPI name for every curated entry
            # (verified directly while building that list) -- using it
            # here is more reliable than re-deriving one from the URL a
            # second time. Falls back to source if package_name is
            # somehow empty.
            install_source = skill.get("package_name") or skill["source"]

            ok = await self.hass.async_add_executor_job(
                self._start_install, api_url, install_source
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
            result = await self._wait_for_install(api_url, install_source)
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
                    "source_type": "curated",
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
        # "curated" default -- subentries created before source_type
        # existed were always curated-catalog installs (extra didn't
        # exist as an install path yet).
        source_type = subentry.data.get("source_type", "curated")
        api_url = await self.hass.async_add_executor_job(
            _api_url_for_source_type, source_type
        )
        if not api_url:
            return self.async_abort(reason="no_api_url")

        skill_id = subentry.data["skill_id"]
        package_name = subentry.data.get("package_name", "")
        fields, current = await self.hass.async_add_executor_job(
            resolve_fields, api_url, skill_id, package_name
        )

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
                _write_settings, api_url, skill_id, merged
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
