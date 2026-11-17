"""A satellite's speaker as a media player (#11): HA can play sounds, radio
and music on the device (media_player.play_media, media sources), pause and
stop it, and set its volume.

The device plays the URL itself (Emkay: an audio element on the page, so a
URL on HA needs no CORS) and reports what it's doing with
ovos/satellite/media. The volume is the device's own, over the bus
(mycroft.volume.*), the same as the Volume entity.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    async_process_play_media_url,
)

from .assist_satellite import CAP_SATELLITE
from .bus import OvosDevice
from .entity import OvosDeviceEntity, setup_capabilities

STATES = {"playing": MediaPlayerState.PLAYING, "paused": MediaPlayerState.PAUSED,
          "idle": MediaPlayerState.IDLE}


async def async_setup_entry(hass, entry, add_entities):
    setup_capabilities(hass, entry, add_entities, lambda device, cap:
                       [OvosMediaPlayer(device)] if cap == CAP_SATELLITE else [])


class OvosMediaPlayer(OvosDeviceEntity, MediaPlayerEntity):
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.MEDIA_ANNOUNCE
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
    )

    def __init__(self, device: OvosDevice) -> None:
        super().__init__(device, "media_player")

    @property
    def state(self) -> MediaPlayerState | None:
        if not self.device.available:
            return None
        return STATES.get(self.device.media_state or "idle", MediaPlayerState.IDLE)

    @property
    def volume_level(self) -> float | None:
        return self.device.volume

    @property
    def is_volume_muted(self) -> bool | None:
        return self.device.speaker_muted

    @property
    def media_content_id(self) -> str | None:
        return self.device.media_url

    async def async_play_media(self, media_type: MediaType | str, media_id: str,
                               **kwargs: Any) -> None:
        if media_source.is_media_source_id(media_id):
            item = await media_source.async_resolve_media(self.hass, media_id, self.entity_id)
            media_id = item.url
        # signed when it is on HA; relative, so the device puts its own
        # address for HA in front (it may reach HA by another name)
        url = async_process_play_media_url(self.hass, media_id, allow_relative_url=True)
        self.device.send_event({"type": "media", "command": "play", "url": url,
                                "announce": bool(kwargs.get("announce"))})

    async def async_browse_media(self, media_content_type: MediaType | str | None = None,
                                 media_content_id: str | None = None) -> BrowseMedia:
        return await media_source.async_browse_media(
            self.hass, media_content_id,
            content_filter=lambda item: item.media_content_type.startswith("audio/"))

    async def async_media_play(self) -> None:
        self.device.send_event({"type": "media", "command": "resume"})

    async def async_media_pause(self) -> None:
        self.device.send_event({"type": "media", "command": "pause"})

    async def async_media_stop(self) -> None:
        self.device.send_event({"type": "media", "command": "stop"})

    async def async_set_volume_level(self, volume: float) -> None:
        self.device.send("mycroft.volume.set", {"percent": volume, "play_sound": False})
        self.device.volume = volume
        self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:
        self.device.send("mycroft.volume.mute" if mute else "mycroft.volume.unmute")
        self.device.speaker_muted = mute
        self.async_write_ha_state()
