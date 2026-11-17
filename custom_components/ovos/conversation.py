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

Supports genuine multi-turn dialogs (a skill's own get_response(), e.g.
"what time should the alarm be?"), not just one-shot answers -- see
_ask's own docstring for how ovos-core's /ask signals this, and Home
Assistant's own Conversation API docs (developers.home-assistant.io/
docs/intent_conversation_api) for confirmation that continue_conversation
+ conversation_id is a real, existing HA mechanism for exactly this,
not something invented here. When set, Assist automatically listens
again and forwards the follow-up utterance back through async_process
with the SAME conversation_id -- no special session tracking needed on
this integration's own side, since the follow-up is simply sent
through /ask again like any other utterance: OVOS's own bus (not this
integration) is what actually routes it back to the specific skill
still waiting on its own get_response() call.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

import requests
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event
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

# Follow-up speech (see OvosConversationAgent._async_follow): lines a skill
# speaks after its turn has ended -- a story read aloud by
# ovos-common-reading-pipeline-plugin, a practice quiz -- are long-polled
# from the core's /follow/<request_id> endpoint and announced on the
# satellite that asked. Only when /ask returned a request_id (an
# ovos-ha-bridge host) and the request came from a satellite.
FOLLOW_POLL_WAIT = 25      # seconds the core holds one /follow long-poll
FOLLOW_IDLE_WAIT = 30      # max seconds to wait for the satellite to be idle
# The satellite's own on-device "stop" word cuts the current announcement
# short without telling Home Assistant (and its wake word is not heard during
# an announcement at all), so a line that ends far sooner than it could have
# been said counts as the person stopping it.
SPEECH_CHARS_PER_SEC = 15  # generous speaking rate for the estimate
CUT_SHORT_MIN_SECONDS = 3  # only judge lines expected to last this long
CUT_SHORT_RATIO = 0.5      # ended in under this share of the estimate


def _get_core_api_url() -> str | None:
    return read_shared_config().get(CONF_CORE_API_URL) or None


def _get_lang_fallback() -> str:
    return read_shared_config().get(CONF_LANG) or DEFAULT_LANG


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, add_entities: AddEntitiesCallback
) -> None:
    if entry.data.get("entry_type") == "device":  # issue #7: nothing here for devices
        return
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
        # satellite entity_id -> running follow-up task (one per satellite)
        self._followers: dict[str, asyncio.Task] = {}

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

        answer, expect_response, request_id = await self.hass.async_add_executor_job(
            self._ask, api_url, user_input.text, lang,
            getattr(user_input, "satellite_id", None),
        )

        # Anything this satellite was still reading out belongs to an older
        # request: the person has spoken again, so stop announcing it.
        satellite_id = getattr(user_input, "satellite_id", None)
        if satellite_id and (old := self._followers.pop(satellite_id, None)):
            old.cancel()
        # Not after a question (expect_response): the satellite is about to
        # listen for the answer, which is not an interruption, and whatever
        # the skill says next arrives with that answer's own request.
        if request_id and satellite_id and not expect_response:
            self._followers[satellite_id] = self.hass.async_create_background_task(
                self._async_follow(api_url, request_id, satellite_id, lang),
                name=f"ovos follow-up {satellite_id}",
            )

        if answer is None:
            # No skill matched, ovos-core unreachable, or it timed out --
            # all treated the same way a real "nothing understood" case
            # would be, not surfaced as a hard error.
            response.async_set_speech("Sorry, I don't understand that.")
        else:
            response.async_set_speech(answer)

        return conversation.ConversationResult(
            response=response,
            conversation_id=user_input.conversation_id,
            continue_conversation=expect_response,
        )

    @staticmethod
    def _ask(
        api_url: str, utterance: str, lang: str, satellite_id: str | None = None
    ) -> tuple[str | None, bool, str | None]:
        try:
            resp = requests.post(
                f"{api_url}/ask",
                json={
                    "utterance": utterance,
                    "lang": lang,
                    "satellite_id": satellite_id,
                },
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
            return None, False, None
        if resp.status_code != 200:
            LOG.debug(
                "%s/ask returned %s: %s", api_url, resp.status_code, resp.text
            )
            return None, False, None
        data = resp.json()
        return (
            data.get("utterance"),
            bool(data.get("expect_response", False)),
            data.get("request_id"),
        )

    async def _async_wait_idle(
        self, satellite_id: str, interrupted: asyncio.Event
    ) -> None:
        """Wait (bounded) until the satellite has finished what it is doing --
        e.g. still speaking this turn's own answer -- before announcing."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + FOLLOW_IDLE_WAIT
        while loop.time() < deadline and not interrupted.is_set():
            state = self.hass.states.get(satellite_id)
            if state is None or state.state == "idle":
                return
            await asyncio.sleep(0.5)

    async def _async_follow(
        self, api_url: str, request_id: str, satellite_id: str, lang: str
    ) -> None:
        """Announce lines the core speaks after the turn ended, one at a
        time, on the satellite that asked; report each as played so the
        core paces the next one (recognizer_loop:audio_output_end).

        Waking the satellite while it reads (it goes to "listening") counts
        as an interruption: announcing stops and "stop" is sent to OVOS.
        Needed because whatever the person then says may never reach this
        agent at all -- with "prefer local intents" on, Home Assistant's own
        stop intent answers a bare "stop" itself, so the story would
        otherwise carry on reading from OVOS's side.
        """
        session = async_get_clientsession(self.hass)
        follow_url = f"{api_url}/follow/{request_id}"
        interrupted = asyncio.Event()

        def _on_state(event) -> None:
            new = event.data.get("new_state")
            if new is not None and new.state == "listening":
                interrupted.set()

        unsub = async_track_state_change_event(
            self.hass, [satellite_id], _on_state
        )
        try:
            while not interrupted.is_set():
                async with session.get(
                    follow_url,
                    params={"wait": FOLLOW_POLL_WAIT},
                    timeout=FOLLOW_POLL_WAIT + 10,
                ) as resp:
                    if resp.status != 200:
                        LOG.debug("%s returned %s", follow_url, resp.status)
                        return
                    data = await resp.json()
                for item in data.get("speak") or []:
                    # str from older bridges, dict with expect_response now
                    if isinstance(item, dict):
                        line = item.get("utterance")
                        asks = bool(item.get("expect_response"))
                    else:
                        line, asks = item, False
                    if not line:
                        continue
                    await self._async_wait_idle(satellite_id, interrupted)
                    if interrupted.is_set():
                        break
                    if asks:
                        # A question (e.g. "is it that one?"): say it and
                        # listen. The answer comes back through this agent
                        # as a new request, which picks up from here, so
                        # this follow-up is done -- and the listening that
                        # follows is not an interruption.
                        await self.hass.services.async_call(
                            "assist_satellite",
                            "start_conversation",
                            {
                                "entity_id": satellite_id,
                                "start_message": line,
                                "preannounce": False,
                            },
                            blocking=True,
                        )
                        return
                    started = asyncio.get_running_loop().time()
                    try:
                        await self.hass.services.async_call(
                            "assist_satellite",
                            "announce",
                            {
                                "entity_id": satellite_id,
                                "message": line,
                                "preannounce": False,
                            },
                            blocking=True,
                        )
                    except Exception as err:  # noqa: BLE001
                        LOG.debug("announce on %s failed: %s", satellite_id, err)
                    took = asyncio.get_running_loop().time() - started
                    expected = len(line) / SPEECH_CHARS_PER_SEC
                    LOG.debug(
                        "%s announced %d chars in %.1fs (estimate %.1fs)",
                        satellite_id, len(line), took, expected,
                    )
                    if (
                        expected >= CUT_SHORT_MIN_SECONDS
                        and took < expected * CUT_SHORT_RATIO
                    ):
                        LOG.info(
                            "%s: line cut short (%.1fs of ~%.1fs), treating "
                            "as stop", satellite_id, took, expected,
                        )
                        interrupted.set()
                    async with session.post(
                        f"{follow_url}/played", timeout=10
                    ) as played:
                        await played.read()
                    if interrupted.is_set():
                        break
                if data.get("done"):
                    return
            if interrupted.is_set():
                LOG.debug("%s interrupted, stopping OVOS reading", satellite_id)
                await self._async_send_stop(session, api_url, lang)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            LOG.debug("follow-up for %s stopped: %s", satellite_id, err)
        finally:
            unsub()
            if self._followers.get(satellite_id) is asyncio.current_task():
                self._followers.pop(satellite_id, None)

    @staticmethod
    async def _async_send_stop(session, api_url: str, lang: str) -> None:
        """Say "stop" to OVOS in the bridge's shared session, silently (the
        confirmation it answers with is not announced)."""
        try:
            async with session.post(
                f"{api_url}/ask",
                json={"utterance": "stop", "lang": lang},
                timeout=REQUEST_TIMEOUT,
            ) as resp:
                await resp.read()
        except Exception as err:  # noqa: BLE001
            LOG.debug("sending stop to %s failed: %s", api_url, err)
