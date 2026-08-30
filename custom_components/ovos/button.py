"""One-off action: install skill-ovos-fallback-chatgpt via ovos-skills-
extra, wiring it to point at ovos-persona's own server -- moved here
from persona_subentry.py (removed) as part of the "entity for data,
button for the one-off action, sensor for status" design agreed for
ovos-persona (see const.py's own PERSONA_DEVICE_ID comment).

Same reasoning persona_subentry.py's own module docstring already
covered for WHY this exists: so ovos-core's own skill pipeline gets a
last-resort fallback to the persona server before giving up entirely,
using OVOS's own native fallback-priority mechanism rather than HA's
conversation agent trying to chain two separate systems together
itself. ovos-persona's own run.sh points the skill's settings.json at
this server -- nothing here needs to know or guess persona's own
address.

A BUTTON rather than an automatic side effect of editing the solver
list text entity (the old flow's own behavior) -- raised and agreed
directly: a fresh install can take up to 3 minutes (this module's own
FALLBACK_INSTALL_POLL_TIMEOUT), and a text entity's own "saving..."
state staying up that whole time on every solver-list edit would look
broken even though it isn't. A separate button makes the slow action
explicit and expected, and keeps solver-list edits themselves fast.

Feedback for a one-off button press has no equivalent to a config
flow's own abort dialog -- uses a persistent_notification instead,
same content the old flow's own "persona_success" abort message showed.
"""
from __future__ import annotations

import asyncio
import time

import requests
from homeassistant.components.button import ButtonEntity
from homeassistant.components.persistent_notification import async_create as async_create_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PERSONA_DEVICE_ID, CONF_SKILLS_EXTRA_API_URL
from .persona_coordinator import OvosPersonaCoordinator
from .shared_config import read_shared_config

REQUEST_TIMEOUT = 10
FALLBACK_SKILL_SOURCE = "skill-ovos-fallback-chatgpt"
FALLBACK_SKILL_ID = "skill-ovos-fallback-chatgpt.openvoiceos"
FALLBACK_INSTALL_POLL_TIMEOUT = 180
FALLBACK_INSTALL_POLL_INTERVAL = 3


def _get_skills_extra_api_url() -> str | None:
    return read_shared_config().get(CONF_SKILLS_EXTRA_API_URL) or None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities):
    coordinator: OvosPersonaCoordinator = hass.data[DOMAIN][f"{entry.entry_id}_persona"]
    persona_subentry_id = hass.data[DOMAIN][f"{entry.entry_id}_persona_subentry"]
    add_entities(
        [OvosPersonaFallbackSkillButton(coordinator, entry)],
        config_subentry_id=persona_subentry_id,
    )


class OvosPersonaFallbackSkillButton(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Set up fallback skill"
    _attr_icon = "mdi:puzzle-plus-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_info = DeviceInfo(identifiers={(DOMAIN, PERSONA_DEVICE_ID)})

    def __init__(self, coordinator: OvosPersonaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_persona_fallback_skill_button"

    async def async_press(self) -> None:
        note = await self._wire_up_fallback_skill()
        async_create_notification(
            self.hass,
            note or "ovos-skills-extra isn't configured, or isn't reachable -- nothing to do.",
            title="OVOS persona fallback skill",
        )

    async def _wire_up_fallback_skill(self) -> str:
        extra_url = await self.hass.async_add_executor_job(_get_skills_extra_api_url)
        if not extra_url:
            return ""

        reachable = await self.hass.async_add_executor_job(self._check_health, extra_url)
        if not reachable:
            return ""

        already_installed = await self.hass.async_add_executor_job(
            self._skill_already_installed, extra_url
        )
        if already_installed:
            return "A fallback-to-persona skill is already installed."

        started = await self.hass.async_add_executor_job(
            self._start_fallback_install, extra_url
        )
        if not started:
            return ""

        result = await self._wait_for_fallback_install(extra_url)
        if result is not None and result.get("status") == "complete":
            return "Installed a fallback-to-persona skill, for when no other skill answers."
        return "The install didn't finish within 3 minutes -- check the ovos-skills-extra add-on's log."

    async def _wait_for_fallback_install(self, extra_url: str) -> dict | None:
        deadline = time.monotonic() + FALLBACK_INSTALL_POLL_TIMEOUT
        while time.monotonic() < deadline:
            status = await self.hass.async_add_executor_job(
                self._poll_fallback_install, extra_url
            )
            if status is not None and status.get("status") in ("complete", "failed"):
                return status
            await asyncio.sleep(FALLBACK_INSTALL_POLL_INTERVAL)
        return None

    @staticmethod
    def _check_health(extra_url: str) -> bool:
        try:
            resp = requests.get(f"{extra_url}/health", timeout=REQUEST_TIMEOUT)
            return resp.status_code == 200 and resp.json().get("bus_connected") is True
        except requests.RequestException:
            return False

    @staticmethod
    def _skill_already_installed(extra_url: str) -> bool:
        try:
            resp = requests.get(f"{extra_url}/skills", timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return any(
                s.get("skill_id") == FALLBACK_SKILL_ID for s in resp.json().get("skills", [])
            )
        except requests.RequestException:
            return False

    @staticmethod
    def _start_fallback_install(extra_url: str) -> bool:
        try:
            resp = requests.post(
                f"{extra_url}/skills/install",
                json={"url": FALLBACK_SKILL_SOURCE},
                timeout=REQUEST_TIMEOUT,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    @staticmethod
    def _poll_fallback_install(extra_url: str) -> dict | None:
        try:
            resp = requests.get(
                f"{extra_url}/skills/install/status",
                params={"key": FALLBACK_SKILL_SOURCE},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                return None
            return resp.json()
        except requests.RequestException:
            return None
