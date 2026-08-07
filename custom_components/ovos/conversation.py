"""Conversation agent that answers via ovos-core's own installed skills.

Deliberately skills-only, no persona fallback -- raised and agreed
directly: chaining to ovos-persona when nothing matched would stack a
second wait on top of /ask's own (up to 20s) timeout, and today's
default persona solvers often produce a worse answer than a quick "I
don't understand" (the DuckDuckGo solver rarely answers a natural
question, falling through to ovos-solver-failure-plugin, whose entire
response is the literal string "404" -- see ovos-persona/DOCS.md).
Persona-fallback chaining, as an opt-in setting once solver quality is
better, is a separate, later piece of work.

Selectable in Settings -> Voice assistants -> Assist -> [pipeline], same
place as HA's own built-in agent or Ollama.
"""
from __future__ import annotations

import logging
from typing import Literal

import requests
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CORE_API_URL, CONF_LANG
from .shared_config import read_shared_config

REQUEST_TIMEOUT = 40  # ovos-core's own /ask (ASK_TIMEOUT) waits up to 35s
                       # for a skill to answer before giving up -- this
                       # needs to be a little longer than that, not
                       # shorter, or we'd cut it off before ovos-core's
                       # own timeout fires. (Corrected from 25s/"up to
                       # 20s" -- both stale relative to ovos-core's real,
                       # confirmed ASK_TIMEOUT = 35; see ovos-core/DOCS.md.)

DEFAULT_LANG = "en-us"

LOG = logging.getLogger(__name__)


def _get_core_api_url() -> str | None:
    return read_shared_config().get(CONF_CORE_API_URL) or None


def _get_lang_fallback() -> str:
    return read_shared_config().get(CONF_LANG) or DEFAULT_LANG


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, add_entities: AddEntitiesCallback
) -> None:
    add_entities([OvosConversationAgent(entry)])


class OvosConversationAgent(conversation.ConversationEntity):
    """Forwards an utterance to ovos-core's /ask, speaks back whatever a
    real, installed skill answered. No skill matching -> a plain "I
    don't understand", the same shape HA's own built-in agent gives for
    an unmatched utterance, not an error.
    """

    _attr_has_entity_name = True
    _attr_name = "OpenVoiceOS"

    def __init__(self, entry: ConfigEntry) -> None:
        self._attr_unique_id = f"{entry.entry_id}_conversation"

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        # ovos-core itself is multilingual and the actual set of
        # working languages depends entirely on which skills/plugins
        # someone has installed -- not something this integration can
        # enumerate up front, so this claims all of them rather than
        # guessing a fixed list HA would otherwise filter this agent
        # out for in a non-English pipeline.
        return "*"

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        response = intent.IntentResponse(language=user_input.language)
        api_url = await self.hass.async_add_executor_job(_get_core_api_url)

        if not api_url:
            response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                "The OpenVoiceOS Core API URL isn't configured yet.",
            )
            return conversation.ConversationResult(
                response=response, conversation_id=user_input.conversation_id
            )

        # user_input.language can genuinely be falsy -- confirmed on real
        # hardware: calling conversation.process without an explicit
        # language produced None here, which ovos-core's /ask (a
        # Pydantic model requiring `lang: str`) rejects with an
        # immediate 422 -- previously silently swallowed below and
        # reported as "Sorry, I don't understand that.", indistinguishable
        # from a genuine no-skill-matched case. Falls back to the shared
        # config's own configured lang (the same value ovos-core itself
        # uses), then a hardcoded default, rather than forwarding
        # whatever HA gives us unchecked.
        lang = user_input.language or await self.hass.async_add_executor_job(
            _get_lang_fallback
        )

        answer = await self.hass.async_add_executor_job(
            self._ask, api_url, user_input.text, lang
        )

        if answer is None:
            # No skill matched, ovos-core unreachable, or it timed out --
            # all treated the same way a real "nothing understood" case
            # would be, not surfaced as a hard error.
            response.async_set_speech("Sorry, I don't understand that.")
        else:
            response.async_set_speech(answer)

        return conversation.ConversationResult(
            response=response, conversation_id=user_input.conversation_id
        )

    @staticmethod
    def _ask(api_url: str, utterance: str, lang: str) -> str | None:
        try:
            resp = requests.post(
                f"{api_url}/ask",
                json={"utterance": utterance, "lang": lang},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as err:
            # Previously swallowed with no logging at all -- confirmed on
            # real hardware this made a real bug (see the lang-fallback
            # comment above) indistinguishable from a genuine "nothing
            # matched" case, from HA's own logs, with no error entry
            # anywhere to find. Always log at debug (not warning/error):
            # ovos-core being briefly unreachable or slow to answer isn't
            # exceptional for every deployment (e.g. right after boot,
            # see ovos-core/DOCS.md's first-boot startup time), but it
            # should be visible when someone goes looking.
            LOG.debug("Request to %s/ask failed: %s", api_url, err)
            return None
        if resp.status_code != 200:
            LOG.debug(
                "%s/ask returned %s: %s", api_url, resp.status_code, resp.text
            )
            return None
        return resp.json().get("utterance")
