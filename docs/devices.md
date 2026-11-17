# OpenVoiceOS devices in Home Assistant: entities from the bus

What a device gets in HA ([#10](https://github.com/andlo/ha-ovos-integration/issues/10)).
Everything comes from OVOS bus messages, so it is the same for every kind of
OVOS and every way it connects ([inbound](protocol.md) today, HiveMind with
[#8](https://github.com/andlo/ha-ovos-integration/issues/8)).

What a device can do is found by **asking it over the bus** when it connects:
if it answers `mycroft.volume.get`, it has a volume; if it answers
`ovos.local_only.status`, it has "local only". So the integration never needs
to know what kind of OVOS it is. What was found is remembered, so the entities
are there (unavailable) after a restart until the device is back.

## Every device

| Entity | Bus |
|---|---|
| `sensor` **State**: idle / listening / thinking / speaking / sleeping | `recognizer_loop:wakeword`, `record_begin` → listening; `record_end`, `utterance` → thinking; `audio_output_start` → speaking; `audio_output_end`, `mycroft.stop`, `ovos.utterance.handled` (when nothing was said) → idle; `recognizer_loop:sleep` / `wake_up`. Thinking falls back to idle after 30 s |
| `sensor` **Last question** | `recognizer_loop:utterance` |
| `sensor` **Last answer** | `speak` |
| `notify` **Say** (`notify.send_message`) | → `speak` `{utterance, lang}` |
| `button` **Listen now** | → `mycroft.mic.listen` |
| `button` **Stop** | → `mycroft.stop` |
| action `ovos.ask` | → `recognizer_loop:utterance` `{utterances, lang}` – as if it had been said to the device |
| action `ovos.send_message` | → any bus message |

## When the device answers

| Entity | Asked with | Answer | Set with |
|---|---|---|---|
| `number` **Volume** (0–100 %) | `mycroft.volume.get` | `.response {percent 0–1, muted}` | `mycroft.volume.set {percent, play_sound: false}` |
| `switch` **Mute speaker** | (same) | | `mycroft.volume.mute` / `unmute` |
| `switch` **Listening** (wake word on) | `mycroft.mic.get_status` | `.response {muted}`; also follows `mycroft.mic.mute` / `unmute` / `mute.toggle` | `mycroft.mic.unmute` / `mute` |
| `switch` **Local only** | `ovos.local_only.status` | `.response {enabled}`, `ovos.local_only.changed` | `ovos.local_only {enabled}` (ovos-skill-guardian's contract) |
| `switch` **Keep screen on** | `ovos.kiosk.status` | `.response {keep_awake, supported…}` | `ovos.kiosk.keep_awake {enabled}` (ovos-skill-kiosk's contract) |
| `sensor` / `binary_sensor`, one per sensor | – | `ovos.phal.sensor` / `ovos.phal.binary_sensor` `{sensor_id, name, state, attributes}` – the messages ovos-PHAL-sensors already sends; `attributes.unit_of_measurement`, `device_class` and `icon` are used | – |

Checked against OVOS today: volume in ovos-PHAL-plugin-alsa (it answers
`mycroft.volume.get` with `percent` 0–1 and `muted`, and re-sends that after
every change, so changes by voice show up in HA); mic in ovos-dinkum-listener.

Note: ovos-PHAL-plugin-alsa only obeys messages in the device's own session.
HA sends without a session, which OVOS treats as the default (the device's own).

## The control panel's settings

A device whose link offers its [ovos-control-panel](https://github.com/OpenVoiceOS/ovos-control-panel)
(`panel: true`; ovos-phal-plugin-ha-link does it on an ordinary OVOS) also gets
what the panel can set. The panel itself does the reading and writing (your
own layer of `mycroft.conf` only, a backup on every save), through the
device's connection, so the panel is never opened on the network:

| Entity | Panel |
|---|---|
| `text` **Language** | `lang` |
| `select` **Units**, **Time format**, **Date format** | the Simple tab |
| `select` **Voice**, **Speech to text**, **Wake word**, **Voice activity detection** | the plugins and wake words the device has |
| `switch` per skill | the skill on or off (`skills.blacklisted_skills`) |
| `binary_sensor` **Problem** | the dashboard: the bus or an essential service not answering |
| `sensor` **Updates available** | OVOS packages with a newer version on the device's channel |
| `button` **Restart OVOS**, **Reboot** | the panel's system actions (they need the panel's token) |

## The network log

A device that tells what it sends out on the network, one
`ovos.network.request` per request, gets:

| Entity | |
|---|---|
| `event` **Network request** | fires for every request; the event type is the kind of service (`stt`, `tts`, `wikipedia`, `weather`, `models`, …, `other`), with `host`, `method`, `status`, `bytes`, `who` (the package that asked) and `service` as attributes. It shows in the logbook, and automations can trigger on it |
| `sensor` **Contacted today** | how many requests went out today, with the services and how many times each (`services` attribute); the device's own site files don't count |
| `sensor` **Last contacted** | the last host, with who asked and the service |

The message carries the same fields as a line of
[Emkay's network log](https://github.com/emkay-voice/emkay/blob/main/docs/network-log.md),
never the path, the query or the body:

```json
{"type": "ovos.network.request", "data": {"t": 1794863530091, "host": "stt.openvoiceos.pt", "method": "POST", "status": 200, "bytes": 52, "who": "ovos-stt-plugin-server", "kind": "stt", "service": "speech recognition (OpenVoiceOS server)"}}
```

Emkay sends it from its network log; on an ordinary OVOS,
[ovos-phal-plugin-ha-link](https://github.com/andlo/ovos-phal-plugin-ha-link)
will (#15, #16).

## As an Assist satellite

A device that sends audio (Emkay does) is also an ordinary Assist device:
an `assist_satellite` entity with the *Assistant* (pipeline) and *Finished
speaking detection* selects next to it, `assist_satellite.announce` and
`start_conversation` from automations, timers ("set a timer for ten
minutes" – it says when it's done), the wake word chosen in HA from the ones
the device has, and a `media_player` for its speaker (sounds, radio and
music from HA). See [protocol.md](protocol.md#5-as-an-assist-satellite).

## Night mode

```yaml
automation:
  - alias: "Kitchen OVOS: not listening at night"
    triggers:
      - trigger: time
        at: "23:00:00"
        id: night
      - trigger: time
        at: "07:00:00"
        id: morning
    actions:
      - action: "switch.turn_{{ 'off' if trigger.id == 'night' else 'on' }}"
        target:
          entity_id: switch.kitchen_ovos_listening
```

## Not there yet (missing on the bus)

- **Language, voice, STT, wake word** as `select`s: OVOS has no bus message to
  *read* the configuration, and `configuration.patch` only changes it in memory
  in the process that gets it. Needs a small PHAL plugin ("config get/set over
  the bus"), so it works for every OVOS.
- **Skill settings** per device: as above – over the bus, not install-specific
  APIs. The add-on entry still has them for haos-ovos-addons.
- **Other things a device can switch** (beyond local only and keep screen on):
  a general "announce a capability" message, like `ovos.phal.sensor` but for
  switches/buttons, would let devices add their own without the integration
  knowing them.
