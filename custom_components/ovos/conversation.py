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

from typing import Literal

import requests
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CORE_API_URL
from .shared_config import read_shared_config

REQUEST_TIMEOUT = 25  # ovos-core's own /ask waits up to 20s for a skill
                       # to answer before giving up -- this needs to be
                       # a little longer than that, not shorter, or we'd
                       # cut it off before ovos-core's own timeout fires


def _get_core_api_url() -> str | None:
    return read_shared_config().get(CONF_CORE_API_URL) or None


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

        answer = await self.hass.async_add_executor_job(
            self._ask, api_url, user_input.text, user_input.language
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
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            return None
        return resp.json().get("utterance")
