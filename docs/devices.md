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
| `switch` / `number` / `text` / `select` per skill setting | the skill's page: one entity per field of its `settingsmeta` |
| `select` **Release channel** | Updates: the channel packages come from (stable, alpha) |
| `binary_sensor` **Problem** | the dashboard: the bus or an essential service not answering |
| `sensor` **Updates available** | OVOS packages with a newer version on the device's channel |
| `button` **Restart OVOS**, **Reboot** | the panel's system actions (they need the panel's token) |
| `button` **Take backup**, `sensor` **Last backup** | the panel's backup archive, kept in HA (below) |

### Backups

**Take backup** asks the panel for its archive (your `mycroft.conf` layer and
the skills' settings, the same file its Backup page downloads) and keeps it in
`/config/ovos_backups/<device>/`, the newest 5. Inside `/config`, so HA's own
backups take them along. **Last backup** says when, and which file. Put it
back with the panel's Restore. The archive has to fit in one of HA's
WebSocket messages, about 3 MB; a settings backup is a few kB.

### Skill settings

Each field of a skill's settingsmeta becomes an entity named after the skill
and the field (*Weather: Units*): a checkbox a `switch`, a number a `number`,
a select a `select` with its choices, the rest a `text`. A skill without a
settingsmeta gets one made from its `settings.json`, the way the panel does
it; those entities start **disabled**, since the skill didn't choose to show
them – enable the ones you want. What's left out: keys starting with `_`
(OVOS' own bookkeeping) and nested values (lists, objects); the panel's raw
editor is for those.

A secret – a password field, or a name with *key*, *token*, *secret* or
*password* in it – can be set from HA but is never read back: the entity's
state stays empty (with `is_set` as an attribute), because a state is kept in
the recorder and shown to anyone who can see the device.

A change is merged into `settings.json` by the panel, so what the skill
itself wrote meanwhile (tokens, counters) is kept. HA reads the settings in
the background, one skill at a time, when the device connects, when a skill
is installed, and every half hour.

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

## A hub and its satellites

An OVOS with hivemind-core – [Emkay Home](https://github.com/emkay-voice/emkay-home),
or any HiveMind master – brings its satellites along when it is linked to HA
(ovos-phal-plugin-ha-link): the kitchen tablet, the bedroom phone, a
hivemind-voice-sat on a Pi. Each becomes its own device, **connected via**
the hub, with its own volume, listening on/off, state and "say" – so an
automation can turn off listening in the bedroom at night without touching
the kitchen.

- A satellite comes in by itself the first time it connects to the hub (no
  "new device found" to accept: the hub was accepted, and it paired the
  satellite). Its name is the one it has in the hub.
- It is unavailable while it isn't connected to the hub, and its device goes
  when it is removed from the hub.
- A satellite has to be allowed to answer: hivemind-core only puts the message
  types a client is allowed on the hub's bus. Emkay Home allows its Emkays the
  answers HA needs (`mycroft.volume.get.response`,
  `mycroft.mic.get_status.response`, …); for another hivemind-core, add them
  with `hivemind-core allow-msg`.

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

- **Language, voice, STT, wake word, skill settings** without the control
  panel: OVOS has no bus message to *read* the configuration. With the panel
  (above) they are there.
- **Other things a device can switch** (beyond local only and keep screen on):
  a general "announce a capability" message, like `ovos.phal.sensor` but for
  switches/buttons, would let devices add their own without the integration
  knowing them.
