"""Shared skill-settings helpers, used by both skill_subentry.py's
one-off reconfigure flow and the live settings entities (switch.py/
number.py/text.py's per-skill classes).

Field-type inference and the settingsmeta/settings.json fallback logic
live here rather than in skill_subentry.py alone -- see that module's
own docstring for the full reasoning (settingsmeta.json only trusted
when present and exclusively 'checkbox' fields; settings.json's own
value types used otherwise, since it's created the moment a skill loads
at all, with or without any settingsmeta).
"""
from __future__ import annotations

import requests

from .const import CONF_SKILLS_API_URL, CONF_SKILLS_EXTRA_API_URL
from .shared_config import read_shared_config

REQUEST_TIMEOUT = 10

SENSITIVE_NAME_HINTS = ("key", "token", "secret", "password")


def get_skills_api_url() -> str | None:
    return read_shared_config().get(CONF_SKILLS_API_URL) or None


def get_skills_extra_api_url() -> str | None:
    return read_shared_config().get(CONF_SKILLS_EXTRA_API_URL) or None


def api_url_for_source_type(source_type: str) -> str | None:
    """Which add-on's API a given installed skill's subentry belongs to
    -- stored per-subentry as "source_type" -- so a settings read/write
    reaches the add-on that actually installed it, curated or extra,
    without guessing.
    """
    if source_type == "extra":
        return get_skills_extra_api_url()
    return get_skills_api_url()


def infer_fields_from_settings(current: dict) -> list[dict]:
    """Build a settingsmeta-shaped field list directly from settings.json's
    own values. Only top-level primitives are considered safely
    inferable; nested dicts/lists are skipped rather than guessed at
    (see ovos-skill-config-tool for a generic editor that DOES handle
    those, as an escape hatch -- CONF_SKILL_CONFIG_TOOL_URL), and
    "__"-prefixed keys are OVOS's own internal bookkeeping (e.g.
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


def fetch_settingsmeta(api_url: str, skill_id: str, package_name: str) -> dict | None:
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


def fetch_current_settings(api_url: str, skill_id: str) -> dict:
    try:
        resp = requests.get(f"{api_url}/skills/{skill_id}/settings", timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return {}


def write_settings(api_url: str, skill_id: str, settings: dict) -> bool:
    try:
        resp = requests.put(
            f"{api_url}/skills/{skill_id}/settings",
            json=settings,
            timeout=REQUEST_TIMEOUT,
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False


def resolve_fields(api_url: str, skill_id: str, package_name: str) -> tuple[list[dict], dict]:
    """The single shared decision: settingsmeta.json when present and
    exclusively checkbox fields, otherwise infer from settings.json's
    own current values. Returns (fields, current_settings) -- current
    is returned too since callers need it either way (as the merge base
    for a write, or to read live values for display).
    """
    meta = fetch_settingsmeta(api_url, skill_id, package_name)
    mappable = bool(
        meta and meta.get("has_settingsmeta") and meta["fields"]
        and all(f.get("type") == "checkbox" for f in meta["fields"])
    )
    current = fetch_current_settings(api_url, skill_id)
    fields = meta["fields"] if mappable else infer_fields_from_settings(current)
    return fields, current
