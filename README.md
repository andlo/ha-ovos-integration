# ha-ovos-integration

<img src="logo.png" width="96" height="96" alt="OpenVoiceOS logo">

A Home Assistant **integration** (HACS-distributed `custom_component`, not a Supervisor add-on) for configuring [OpenVoiceOS](https://openvoiceos.org) the way HAOS users already configure everything else: as entities and config flows under Settings → Devices & services, not raw JSON files or a bespoke webpage.

Talks to the add-ons in [haos-ovos-addons](https://github.com/andlo/haos-ovos-addons) — install those first.

## What it does

Adds one integration entry, **"OpenVoiceOS"**, with:

- **Shared configuration** — language and each add-on's API URL, as ordinary `text` entities, kept in sync with the shared `mycroft.conf` on `/share`.
- **Guided voice setup** — a subentry flow that runs `ovos-core`'s own autoconfigure, picking sensible TTS/STT plugins for your language.
- **Skill management** — one config subentry per installed skill:
  - *Add a skill* from `ovos-skills`' curated catalog (a picklist), or from `ovos-skills-extra` (type a PyPI name or git URL directly).
  - Each skill gets its own device in HA's device registry, with a live "installed version" sensor.
  - *Reconfigure a skill's settings* from its own `settingsmeta.json`, or inferred directly from its `settings.json` when it doesn't ship one.
- **Persona configuration** — a subentry flow to choose which question-solver plugins `ovos-persona` uses, and in what order.

## Setup

1. Install and start the relevant [haos-ovos-addons](https://github.com/andlo/haos-ovos-addons) add-ons first.
2. Add the **OpenVoiceOS** integration in HA.
3. Fill in each add-on's API URL under the integration's own entities (e.g. `http://<hostname>:8500` for `ovos-skills`).
4. Use **Add sub-entry** on the integration to add skills, run voice setup, or configure persona.

## License

![license](https://img.shields.io/badge/license-Apache--2.0-blue)

Licensed under the [Apache License 2.0](LICENSE), matching OpenVoiceOS's own project license.

The OpenVoiceOS logo is used with attribution to the [OpenVoiceOS project](https://openvoiceos.org); this project is not officially affiliated with or endorsed by OpenVoiceOS.
