"""An OVOS device as an Assist satellite (issue #11).

For devices that send audio (they say `satellite: true` in ovos/connect):
the device is an ordinary Assist device in HA -- its pipeline and "finished
speaking" sensitivity are chosen in HA, automations can announce on it and
start a conversation, and it can run timers. HA's pipeline is the brain;
the OVOS device is the ears, the mouth and the face.

This is the other way round from haos-ovos-addons, where OVOS sits *inside*
HA's pipeline as the conversation agent.

How the audio gets here: the device keeps its own wake word ("hey emkay" on
Emkay), then streams the recording over its WebSocket connection to HA
(ovos/satellite/run, satellite.py), and this entity runs the pipeline
through HA's own async_accept_pipeline_from_satellite. Pipeline events go
back on that run; announcements and timers go as events on the device's
ovos/connect subscription.

The idea of a browser as an `assist_satellite` over HA's WebSocket API comes
from Voice Satellite (jxlarrea/voice-satellite-card-integration), with
thanks; the code here is written on HA's own AssistSatelliteEntity API.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, Callable
import logging
from typing import Any

from homeassistant.components.assist_pipeline import PipelineEvent, PipelineStage
from homeassistant.components.assist_satellite import (
    AssistSatelliteAnnouncement,
    AssistSatelliteConfiguration,
    AssistSatelliteEntity,
    AssistSatelliteEntityFeature,
)
from homeassistant.components.intent import (
    TimerEventType,
    TimerInfo,
    async_register_timer_handler,
)
from homeassistant.core import Context
from homeassistant.helpers import entity_registry as er

from ..const import DOMAIN
from .bus import OvosDevice
from .entity import OvosDeviceEntity, setup_capabilities

_LOGGER = logging.getLogger(__name__)

CAP_SATELLITE = "satellite"
ANNOUNCE_TIMEOUT = 120   # seconds a device may take to play an announcement


async def async_setup_entry(hass, entry, add_entities):
    setup_capabilities(hass, entry, add_entities, lambda device, cap:
                       [OvosSatellite(device)] if cap == CAP_SATELLITE else [])


def media_url(url: str | None) -> str | None:
    """HA's TTS audio through the integration's CORS path, so a page on
    another site can fetch it (inbound.OvosTtsView)."""
    if url and "/api/tts_proxy/" in url:
        return "/api/ovos/tts/" + url.split("/api/tts_proxy/", 1)[1]
    return url


class OvosSatellite(OvosDeviceEntity, AssistSatelliteEntity):
    _attr_supported_features = (
        AssistSatelliteEntityFeature.ANNOUNCE
        | AssistSatelliteEntityFeature.START_CONVERSATION
    )

    def __init__(self, device: OvosDevice) -> None:
        super().__init__(device, "satellite")
        self._attr_translation_key = None
        self._attr_name = None          # the device's own name
        self._announce_id = 0
        self._announce_done: asyncio.Future | None = None
        # the run whose pipeline events go back to the device
        self._run_sink: Callable[[dict], None] | None = None

    # --- the select entities next to it (select.py) ----------------------

    def _sibling(self, suffix: str) -> str | None:
        return er.async_get(self.hass).async_get_entity_id(
            "select", DOMAIN, f"{self.device.device_id}-{suffix}")

    @property
    def pipeline_entity_id(self) -> str | None:
        return self._sibling("pipeline")

    @property
    def vad_sensitivity_entity_id(self) -> str | None:
        return self._sibling("vad_sensitivity")

    # --- setup -------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.device.satellite = self
        self.async_on_remove(lambda: setattr(self.device, "satellite", None))
        if self.device_entry is not None:
            self.async_on_remove(async_register_timer_handler(
                self.hass, self.device_entry.id, self._on_timer))

    def async_get_configuration(self) -> AssistSatelliteConfiguration:
        # the wake word is on the device, not chosen in HA (yet)
        return AssistSatelliteConfiguration(
            available_wake_words=[], active_wake_words=[], max_active_wake_words=0)

    async def async_set_configuration(self, config: AssistSatelliteConfiguration) -> None:
        """Nothing to set: see async_get_configuration."""

    # --- pipeline runs (satellite.py's ovos/satellite/run) -------------------

    async def async_run_audio(self, audio: AsyncIterable[bytes], sink: Callable[[dict], None],
                              wake_word_phrase: str | None = None) -> None:
        """A recording from the device (16 kHz mono 16-bit), from speech-to-text on."""
        self._run_sink = sink
        try:
            await self.async_accept_pipeline_from_satellite(
                audio, start_stage=PipelineStage.STT, end_stage=PipelineStage.TTS,
                wake_word_phrase=wake_word_phrase)
        finally:
            if self._run_sink is sink:
                self._run_sink = None

    async def async_run_text(self, text: str, sink: Callable[[dict], None]) -> None:
        """A typed question: the same pipeline from the conversation agent on.

        HA's satellite helper only takes audio, so this builds the run the
        way assist_pipeline itself does for text input.
        """
        from homeassistant.components.assist_pipeline import async_get_pipeline
        from homeassistant.components.assist_pipeline.pipeline import (
            PipelineInput,
            PipelineRun,
        )
        from homeassistant.helpers import chat_session

        self._run_sink = sink
        try:
            pipeline = async_get_pipeline(self.hass, self._resolve_pipeline())
            with chat_session.async_get_chat_session(self.hass, self._conversation_id) as session:
                self._conversation_id = session.conversation_id
                run = PipelineRun(
                    hass=self.hass, context=Context(), pipeline=pipeline,
                    start_stage=PipelineStage.INTENT, end_stage=PipelineStage.TTS,
                    event_callback=self._internal_on_pipeline_event,
                    tts_audio_output=self.tts_options,
                )
                await PipelineInput(
                    run=run, session=session, intent_input=text,
                    device_id=self.device_entry.id if self.device_entry else None,
                    satellite_id=self.entity_id,
                ).execute(validate=True)
        finally:
            if self._run_sink is sink:
                self._run_sink = None

    def on_pipeline_event(self, event: PipelineEvent) -> None:
        if self._run_sink is None:
            return
        # the shape assist_pipeline/run sends its events in
        data = {"type": str(event.type), "data": dict(event.data or {}),
                "timestamp": event.timestamp}
        if data["type"] == "tts-end":
            out = dict(data["data"].get("tts_output") or {})
            if out.get("url"):
                out["url"] = media_url(out["url"])
            data["data"]["tts_output"] = out
        self._run_sink(data)

    def device_done(self, what: str, announce_id: int | None = None) -> None:
        """The device finished playing: an answer (tts) or an announcement."""
        if what == "tts":
            self.tts_response_finished()
        elif (what == "announce" and self._announce_done is not None
              and announce_id == self._announce_id and not self._announce_done.done()):
            self._announce_done.set_result(None)

    # --- announcements -------------------------------------------------------

    async def _announce(self, announcement: AssistSatelliteAnnouncement,
                        start_conversation: bool) -> None:
        if not self.device.available:
            raise RuntimeError(f"{self.device.entry.title} is not connected")
        self._announce_id += 1
        self._announce_done = self.hass.loop.create_future()
        self.device.send_event({
            "type": "announce",
            "id": self._announce_id,
            "message": announcement.message or "",
            "media_url": media_url(announcement.media_id),
            "preannounce_url": media_url(getattr(announcement, "preannounce_media_id", None)),
            "start_conversation": start_conversation,
        })
        try:
            await asyncio.wait_for(self._announce_done, ANNOUNCE_TIMEOUT)
        except TimeoutError:
            _LOGGER.warning("%s: announcement not finished after %ss",
                            self.device.entry.title, ANNOUNCE_TIMEOUT)
        finally:
            self._announce_done = None

    async def async_announce(self, announcement: AssistSatelliteAnnouncement) -> None:
        await self._announce(announcement, start_conversation=False)

    async def async_start_conversation(self, start_announcement: AssistSatelliteAnnouncement) -> None:
        # after it, the device listens without its wake word and sends the
        # answer as an ordinary run
        await self._announce(start_announcement, start_conversation=True)

    # --- timers --------------------------------------------------------------

    def _on_timer(self, event_type: TimerEventType, timer: TimerInfo) -> None:
        self.device.send_event({
            "type": "timer",
            "event": str(event_type),
            "timer": {
                "id": timer.id,
                "name": timer.name or "",
                "seconds_left": timer.seconds_left,
                "is_active": timer.is_active,
                "total_seconds": (timer.start_hours or 0) * 3600
                + (timer.start_minutes or 0) * 60 + (timer.start_seconds or 0),
            },
        })
