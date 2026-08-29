"""Auto-discover OVOS add-on API URLs via the Supervisor API.

See https://github.com/andlo/ha-ovos-integration/issues/4 -- removes the
"chicken and egg" problem where the autoconfigure/skill-management flows
required these URLs to already be typed in by hand into their text
entities, with nothing else able to bootstrap that first value.

Uses the SUPERVISOR_TOKEN env var + the internal http://supervisor API
directly -- the same pattern many community custom_components use for
Supervisor access from outside HA Core's own codebase. No special
manifest.json permission is needed for this (that's only required for
core-shipped integrations using hassio's own internal Python helpers,
not for a plain HTTP call with this token). Only meaningful on a
Supervisor-managed install (HAOS/Supervised) -- silently returns {} with
no token present, which is the correct signal for the caller to fall
back to manual entry, not an error condition.

Confirmed via Home Assistant's own Supervisor API docs: /addons/{slug}/info
returns a "hostname" field directly (e.g. "b8e040e3-ovos-core" for slug
"b8e040e3_ovos_core") -- used as-is rather than deriving it ourselves by
replacing underscores with hyphens in the slug. That transform is
documented as correct too, but reading the field Supervisor already
computed avoids relying on it continuing to hold for every possible slug
shape.
"""
from __future__ import annotations

import logging
import os

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_CORE_API_URL,
    CONF_PERSONA_API_URL,
    CONF_SKILLS_API_URL,
    CONF_SKILLS_EXTRA_API_URL,
)

_LOGGER = logging.getLogger(__name__)

SUPERVISOR_API = "http://supervisor"
_TIMEOUT = aiohttp.ClientTimeout(total=10)

# Each haos-ovos-addons add-on's own internal config.yaml "slug" (the
# part after the repo-hash prefix Supervisor adds at install time, e.g.
# "b8e040e3_ovos_core") -> (shared-config key to fill, the add-on's own
# fixed API port). Ports confirmed from each add-on's own config.yaml/
# DOCS.md -- ovos-persona's bridge API runs on a different port than the
# others (see persona_subentry.py), ovos-skills-extra on a different one
# again (see its own DOCS.md).
_ADDON_SLUG_SUFFIX_MAP: dict[str, tuple[str, int]] = {
    "_ovos_core": (CONF_CORE_API_URL, 8500),
    "_ovos_skills": (CONF_SKILLS_API_URL, 8500),
    "_ovos_persona": (CONF_PERSONA_API_URL, 8338),
    "_ovos_skills_extra": (CONF_SKILLS_EXTRA_API_URL, 8502),
}


async def async_discover_addon_api_urls(hass: HomeAssistant) -> dict[str, str]:
    """Returns {shared_config_key: url} for every OVOS add-on Supervisor
    currently reports as installed. Best-effort throughout: any failure
    (no token, unreachable, unexpected response shape, a slug matching
    more than one suffix -- shouldn't happen but not worth crashing
    setup over) just omits that entry rather than raising, so a caller
    always gets a (possibly empty or partial) dict back, never an
    exception, and falls through to manual entry for whatever wasn't
    found.
    """
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return {}

    headers = {"Authorization": f"Bearer {token}"}
    session = async_get_clientsession(hass)

    try:
        async with session.get(
            f"{SUPERVISOR_API}/addons", headers=headers, timeout=_TIMEOUT
        ) as resp:
            if resp.status != 200:
                _LOGGER.debug("Supervisor /addons returned %s", resp.status)
                return {}
            payload = await resp.json()
    except (aiohttp.ClientError, TimeoutError) as exc:
        _LOGGER.debug("Supervisor /addons unreachable: %s", exc)
        return {}

    addons = payload.get("data", {}).get("addons", [])

    discovered: dict[str, str] = {}
    for addon in addons:
        slug = addon.get("slug", "")
        match = next(
            (v for suffix, v in _ADDON_SLUG_SUFFIX_MAP.items() if slug.endswith(suffix)),
            None,
        )
        if match is None:
            continue
        key, port = match
        hostname = await _async_fetch_hostname(session, headers, slug)
        if hostname:
            discovered[key] = f"http://{hostname}:{port}"

    return discovered


async def _async_fetch_hostname(
    session: aiohttp.ClientSession, headers: dict, slug: str
) -> str | None:
    try:
        async with session.get(
            f"{SUPERVISOR_API}/addons/{slug}/info", headers=headers, timeout=_TIMEOUT
        ) as resp:
            if resp.status != 200:
                return None
            payload = await resp.json()
    except (aiohttp.ClientError, TimeoutError) as exc:
        _LOGGER.debug("Supervisor /addons/%s/info unreachable: %s", slug, exc)
        return None
    return payload.get("data", {}).get("hostname")
