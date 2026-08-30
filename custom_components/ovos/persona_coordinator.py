"""Polls ovos-persona's own API (health, available solvers, current
settings) on a fixed interval -- same shape as OvosSkillSettingsCoordinator,
but for the one persona server rather than a set of installed skills.

Deliberately tolerant of "not configured" and "unreachable" as two of
the normal states this returns, not exceptions -- CONF_PERSONA_API_URL
is entirely optional (see persona entities' own module docstrings for
why: a person can run ovos-persona standalone, or not at all), so every
consumer of this coordinator's data checks data["reachable"] rather
than assuming a successful fetch.
"""
from __future__ import annotations

from datetime import timedelta
import logging

import requests
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_PERSONA_API_URL
from .shared_config import read_shared_config

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)
REQUEST_TIMEOUT = 10


def get_persona_api_url() -> str | None:
    return read_shared_config().get(CONF_PERSONA_API_URL) or None


def _check_health(api_url: str) -> bool:
    try:
        resp = requests.get(f"{api_url}/health", timeout=REQUEST_TIMEOUT)
        return resp.status_code == 200 and resp.json().get("bus_connected") is True
    except requests.RequestException:
        return False


def _fetch_available_solvers(api_url: str) -> list[str]:
    try:
        resp = requests.get(f"{api_url}/available-solvers", timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("solvers", [])
    except requests.RequestException:
        return []


def _fetch_current_settings(api_url: str) -> dict:
    try:
        resp = requests.get(f"{api_url}/settings", timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return {}


def write_persona_settings(api_url: str, settings: dict) -> bool:
    try:
        resp = requests.put(f"{api_url}/settings", json=settings, timeout=REQUEST_TIMEOUT)
        return resp.status_code == 200
    except requests.RequestException:
        return False


class OvosPersonaCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="ovos_persona",
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict:
        return await self.hass.async_add_executor_job(self._fetch)

    @staticmethod
    def _fetch() -> dict:
        api_url = get_persona_api_url()
        if not api_url:
            return {"configured": False, "reachable": False, "available_solvers": [], "current_settings": {}}
        if not _check_health(api_url):
            return {"configured": True, "reachable": False, "available_solvers": [], "current_settings": {}, "api_url": api_url}
        return {
            "configured": True,
            "reachable": True,
            "available_solvers": _fetch_available_solvers(api_url),
            "current_settings": _fetch_current_settings(api_url),
            "api_url": api_url,
        }
