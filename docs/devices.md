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
