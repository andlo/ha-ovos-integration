# OVOS → Home Assistant: the inbound protocol (version 1)

How an OpenVoiceOS device connects **to** Home Assistant and carries its bus
over HA's WebSocket API ([#9](https://github.com/andlo/ha-ovos-integration/issues/9)).
It is for devices HA can't reach: [Emkay](https://emkay.ai) in a browser (a
browser can't accept connections) and devices behind NAT. Any OVOS client can
use it – [`tools/ovos_ha_bridge.py`](../tools/ovos_ha_bridge.py) is a small
reference client in Python, Emkay has one in JavaScript.

## 0. Allow it in Home Assistant

Add the **OpenVoiceOS** integration and choose **An OpenVoiceOS device**. That
adds one entry, *OpenVoiceOS devices*, which lets devices connect at all. Until
it exists, `ovos/connect` answers `not_enabled`.

## 1. Log in

Use HA's own login – nobody has to copy a token.

**Apps with a web address (Emkay)** use HA's OAuth2/IndieAuth flow, with the
app's address as `client_id`:

1. Send the user to
   `<ha>/auth/authorize?client_id=https://app.example/&redirect_uri=https://app.example/auth.html&state=…`
   The `redirect_uri` must be on the same host as `client_id` (otherwise HA
   fetches the `client_id` page and looks for `<link rel="redirect_uri">`).
2. HA shows its normal login page and sends the user back with `?code=…`.
3. `POST <ha>/auth/token` (form-encoded) `grant_type=authorization_code&code=…&client_id=…`
   → `access_token` (30 min) and `refresh_token`. Keep the refresh token on the
   device; later: `grant_type=refresh_token&refresh_token=…&client_id=…`.

Checked against HA 2026.8.3: a foreign `client_id` is accepted, and
`/auth/token` answers CORS for the app's origin, so a page on another site can
do all of this from the browser.

**Headless devices** can use a long-lived access token (HA profile → Security).

### https

A page served over https can only reach HA over https (`wss://`) – the browser
blocks the rest as mixed content. So for Emkay at `https://app.emkay.ai`, HA must
be on https: Home Assistant Cloud (Nabu Casa), a tunnel (Cloudflare…), or your
own certificate. Or serve Emkay from the house on plain http.

## 2. The WebSocket API

Connect to `<ha>/api/websocket` and authenticate as usual
(`{"type": "auth", "access_token": …}`). Then:

### `ovos/connect` – "I am this device" (a subscription)

```json
{"id": 1, "type": "ovos/connect", "protocol": 1,
 "device_id": "emkay-6f1c…", "name": "Kitchen tablet",
 "model": "Emkay", "manufacturer": "Emkay", "sw_version": "0.9.0", "lang": "da-dk"}
```

| Field | | |
|---|---|---|
| `protocol` | required | the protocol version the client speaks (1) |
| `device_id` | required | stable per device, chosen by the device; 8–64 of `A–Z a–z 0–9 _ . : -`. A random UUID kept on the device is right |
| `name` | required | the name HA gives the device at first |
| `model`, `manufacturer`, `sw_version` | optional | shown on the device page; updated each time |
| `lang` | optional | the device's language; used for `speak` and the *ask* action |

The result comes at once; then **events** on the same `id`:

| Event | Meaning |
|---|---|
| `{"type": "pending"}` | HA doesn't have this device yet, or it is disabled/reloading. A new device is shown under **Settings → Devices & services → Discovered** ("Test OVOS wants to join"); stay connected – `ready` follows when someone adds it |
| `{"type": "ready", "protocol": 1, "entry_id": "…", "device_id": "…", "forward": […]}` | paired. `device_id` is HA's own id for the device (for `assist_pipeline/run`, see 4); `forward` lists the bus message types HA wants from the device (see 3). HA asks the device what it can do right after this |
| `{"type": "bus", "message": {"type": …, "data": {…}, "context": {…}}}` | a bus message for the device – put it on its bus / handle it |
| `{"type": "displaced"}` | another connection took over this `device_id`; stop |
| `{"type": "removed"}` | the device was deleted in HA; stop (connecting again offers it anew) |

Errors: `unsupported_protocol` (the message says which versions HA speaks),
`not_enabled` (step 0), `unauthorized` (the device belongs to another HA user –
only the user it first connected as, or an admin, can connect as it).

Unsubscribing (`unsubscribe_events`) or closing the WebSocket makes the device
unavailable in HA. Connect again the same way; nothing else to restore.

### `ovos/bus` – a bus message from the device

```json
{"id": 7, "type": "ovos/bus", "device_id": "emkay-6f1c…",
 "message": {"type": "mycroft.volume.get.response", "data": {"percent": 0.6, "muted": false}, "context": {}}}
```

Only on the WebSocket that holds the device's `ovos/connect`; otherwise
`not_connected`. Messages before `ready` are dropped.

## 3. Which messages go which way

HA → device: ordinary OVOS bus messages, as any OVOS understands them
(`mycroft.volume.set`, `mycroft.mic.mute`, `speak`, `recognizer_loop:utterance`,
…). Their `context.source` is `homeassistant`. They are meant for the device
itself: a client bridging a real OVOS bus puts them on it as they are (no
session, so OVOS treats them as the device's own).

Device → HA: the types in `ready.forward` – state (`recognizer_loop:*`,
`speak`, `ovos.utterance.handled`), the answers to HA's questions
(`*.response`), and the device's own sensors (`ovos.phal.sensor`,
`ovos.phal.binary_sensor`). Sending more is harmless but wasted. A device that
*is* the bus (Emkay with the Home Assistant brain) answers HA's questions
itself. [devices.md](devices.md) has what each message does in HA.

## 4. Voice: Home Assistant's Assist as the brain

A device that sends audio can use HA's Assist directly with HA's own
`assist_pipeline/run` on the same WebSocket. That's how Emkay with the Home Assistant
brain works:

- `start_stage: "stt"`, `input: {sample_rate: 16000}`: send the recording
  as binary frames, each prefixed with the `stt_binary_handler_id` byte from
  `run-start`, then that byte alone to end it. With `start_stage: "intent"`,
  `input: {text}` for typed questions.
- Give `device_id` from the `ready` event, so Assist knows which device
  (and so which area) the question came from, and keep `conversation_id`
  from `intent-end` for follow-ups (`continue_conversation`).
- Turn the pipeline's events into the device's own bus messages
  (`recognizer_loop:record_end`, `utterance`, `speak`,
  `audio_output_start/end`) and send them with `ovos/bus`. Then the device's
  state in HA follows, and an OVOS face reacts as it does with its own OVOS.
- **TTS audio**: `tts-end` gives `tts_output.token`. HA's own
  `/api/tts_proxy/<token>` has no CORS headers, so a page on another site
  can't fetch it. The integration serves the same audio with CORS at
  **`/api/ovos/tts/<token>`**. Use that one from a browser.

## 5. As an Assist satellite

A device that sends `"satellite": true` in `ovos/connect` becomes an Assist
satellite in HA ([#11](https://github.com/andlo/ha-ovos-integration/issues/11)):
an `assist_satellite` entity, and the *Assistant* (pipeline) and *Finished
speaking detection* selects next to it. HA then runs the pipeline chosen
for the device. Automations can announce on it and start a conversation,
and it can run timers. `ready.features` contains `"satellite"` when the
integration can do this; a client then uses these commands instead of
`assist_pipeline/run`:

### `ovos/satellite/run` – one question (a subscription)

```json
{"id": 9, "type": "ovos/satellite/run", "device_id": "…", "start_stage": "stt"}
{"id": 9, "type": "ovos/satellite/run", "device_id": "…", "start_stage": "intent", "text": "what time is it"}
```

The first event is `{"type": "init", "handler_id": n}`. With `"stt"`, send
the recording as binary frames: the `handler_id` byte, then 16 kHz mono
16-bit PCM. Send that byte alone to end it. The wake word is the device's
own. Then the pipeline's events follow, in `assist_pipeline/run`'s shape
(`run-start`, `stt-end`, `intent-end`, `tts-end` with `tts_output.url`
already on the CORS path, `run-end`, `error`).

### `ovos/satellite/done` – finished playing

`{"type": "ovos/satellite/done", "device_id": "…", "what": "tts"}` after
playing an answer, so the satellite goes back to idle;
`"what": "announce", "announce_id": n` after an announcement.

### Events on the `ovos/connect` subscription

| Event | |
|---|---|
| `{"type": "announce", "id": n, "message": "…", "media_url": "/api/ovos/tts/…", "preannounce_url": …, "start_conversation": false}` | play it (or say `message`), then `ovos/satellite/done` with `what: "announce"`. With `start_conversation: true`, listen right after it without the wake word, and send the answer as a normal run |
| `{"type": "timer", "event": "started" \| "updated" \| "cancelled" \| "finished", "timer": {id, name, seconds_left, is_active, total_seconds}}` | timers set on this device; on `finished`, let the user know |
| `{"type": "wake_word", "id": "hey_jarvis"}` | the wake word was chosen in HA (one of the device's `wake_words`); switch to it and use it from now on |
| `{"type": "media", "command": "play", "url": "/api/…", "announce": false}` / `"pause"` / `"resume"` / `"stop"` | the satellite's media player (`media_player.play_media`, media sources). A relative `url` is on HA; it's already signed where needed. Report the state with `ovos/satellite/media` |

### Wake words

In `ovos/connect`, a satellite can list the wake words it can listen for and
the one in use: `"wake_words": [{"id": "hey_emkay", "wake_word": "Hey Emkay"}, …],
"wake_word": "hey_emkay"`. HA shows them in the satellite's configuration
(one at a time) and sends `wake_word` when another is chosen.

### `ovos/satellite/media` – what the media player is doing

`{"type": "ovos/satellite/media", "device_id": "…", "state": "playing" | "paused" | "idle", "url": "…"}`
whenever it changes. The volume is the device's own, set over the bus
(`mycroft.volume.*`).

The idea of a browser as an Assist satellite over HA's WebSocket API comes
from [Voice Satellite](https://github.com/jxlarrea/voice-satellite-card-integration).

## 6. The control panel through the connection

A device that has [ovos-control-panel](https://github.com/OpenVoiceOS/ovos-control-panel)
says `"panel": true` in `ovos/connect` (and, optionally, `"panel_url"`: where
a browser can open it, for "Open control panel" on the device page). HA then
reads and sets its settings through the connection, never over the network:

- HA sends `{"type": "panel", "id": n, "method": "GET" | "POST" | "PUT", "path": "/config/quick", "body": …}`
  on the `ovos/connect` subscription. `path` is the panel's API path without `/api`.
- The device makes that call to its own panel (`http://127.0.0.1:8500/api` + `path`,
  with the panel's access token) and answers with
  `{"type": "ovos/panel/response", "device_id": "…", "request_id": n, "status": 200, "body": {…}}`.
- When the answer is a file (the panel's backup), the event has `"binary": true`,
  and `body` is `{"content_type": "…", "filename": "…", "data": "<base64>"}`.
  It goes in one WebSocket message, and HA takes 4 MB, so a bigger file is
  answered with status 413 instead.

What HA uses today: `GET /config/quick`, `POST /config/quick`, `GET /health`,
`GET /skills`, `GET /skills/{id}`, `PUT /skills/{id}`, `GET /config/merged`,
`PUT /skills/{id}/enabled`, `GET /updates`, `GET`/`POST /updates/channel`,
`GET /backup` (binary), `POST /system/{restart_services|reboot}`.
[ovos-phal-plugin-ha-link](https://github.com/andlo/ovos-phal-plugin-ha-link)
does the device's side on an ordinary OVOS.

## Versions

The protocol number goes up only for changes an older client can't live with.
New events and new message types are added without a bump; a client ignores
events it doesn't know.
