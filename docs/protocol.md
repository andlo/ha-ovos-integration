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
| `{"type": "ready", "protocol": 1, "entry_id": "…", "forward": […]}` | paired. `forward` lists the bus message types HA wants from the device (see 3) |
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

## Versions

The protocol number goes up only for changes an older client can't live with.
New events and new message types are added without a bump; a client ignores
events it doesn't know.
