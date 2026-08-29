# ha-ovos-integration

<img src="logo.png" width="96" height="96" alt="OpenVoiceOS logo">

**This is the companion Home Assistant integration for [haos-ovos-addons](https://github.com/andlo/haos-ovos-addons).** It has no purpose on its own — every entity and flow it offers talks directly to that repo's own add-ons over their own HTTP APIs (`ovos-core`, `ovos-skills`, `ovos-skills-extra`, `ovos-persona`). It is **not** a general-purpose OVOS integration: it won't do anything useful against a different OVOS install (`ovos-installer`, `raspOVOS`, a manual venv install, etc.), since those don't expose the same bespoke APIs this integration was built against. Install [haos-ovos-addons](https://github.com/andlo/haos-ovos-addons) first — this repo only makes sense alongside it.

A Home Assistant **integration** (HACS-distributed `custom_component`, not a Supervisor add-on) for configuring those add-ons the way HAOS users already configure everything else: as entities and config flows under Settings → Devices & services, not raw JSON files or a bespoke webpage.

## What it does

Adds one integration entry, **"OpenVoiceOS"**, with:

- **Shared configuration** — language and each add-on's API URL, as ordinary `text` entities, kept in sync with the shared `mycroft.conf` on `/share`.
- **Guided voice setup** — a subentry flow that runs `ovos-core`'s own autoconfigure, picking sensible TTS/STT plugins for your language.
- **Skill management** — one config subentry per installed skill:
  - *Add a skill* from `ovos-skills`' curated catalog (a picklist), or from `ovos-skills-extra` (type a PyPI name or git URL directly).
  - Each skill gets its own device in HA's device registry, with a live "installed version" sensor.
  - Non-sensitive settings (booleans, numbers, plain strings) show up as live, editable entities on that same device — no separate flow needed to see or change them.
  - *Reconfigure a skill's other settings* from its own `settingsmeta.json`, or inferred directly from its `settings.json` when it doesn't ship one — still the way to change anything not shown as a live entity.
  - An optional link to a self-hosted [ovos-skill-config-tool](https://github.com/OscillateLabsLLC/ovos-skill-config-tool) instance, for editing secrets or nested settings this integration deliberately keeps off its own live entities.
- **Persona configuration** — a subentry flow to choose which question-solver plugins `ovos-persona` uses, and in what order.

## Setup

1. Install and start the relevant [haos-ovos-addons](https://github.com/andlo/haos-ovos-addons) add-ons first.
2. Add the **OpenVoiceOS** integration in HA.
3. On Home Assistant OS / Supervised, each add-on's API URL is filled in automatically by querying Supervisor — nothing to do here. On a non-Supervisor install (or if an add-on isn't found), fill in the missing URL(s) under the integration's own entities (e.g. `http://<hostname>:8500` for `ovos-skills`).
4. Use **Add sub-entry** on the integration to add skills, run voice setup, or configure persona.

## License

![license](https://img.shields.io/badge/license-Apache--2.0-blue)

Licensed under the [Apache License 2.0](LICENSE), matching OpenVoiceOS's own project license.

The OpenVoiceOS logo is used with attribution to the [OpenVoiceOS project](https://openvoiceos.org); this project is not officially affiliated with or endorsed by OpenVoiceOS.
