# ha-ovos-integration

![status](https://img.shields.io/badge/status-work%20in%20progress-orange)
![status](https://img.shields.io/badge/status-verified%20on%20real%20hardware-brightgreen)

<img src="logo.png" width="96" height="96" alt="OpenVoiceOS logo">

> 🚧 **Work in progress — v0.0.5, both halves confirmed working end-to-end on real hardware.**
> Shared config: two-way sync verified (a direct file edit surfaced via polling with no
> restart needed). Skill management: the full loop verified for real — picked a skill from
> the catalog dropdown in a config subentry, it genuinely installed via `ovos-skills`'
> `SkillsStore` bridge, confirmed present on both the HA subentry side and the add-on's own
> `/skills` list. Integration display name is **"OpenVoiceOS"** in Add Integration.

A Home Assistant **integration** (HACS-distributed `custom_component`, not a Supervisor
add-on) for configuring OVOS the way HAOS users already configure everything else: as
entities under Settings → Devices & services, not raw JSON fields or a bespoke webpage.

Two things it aims to do:

1. **Shared OVOS configuration** (language, location, units) — v1, implemented and verified:
   reads/writes `/share/mycroft/mycroft.conf` directly (plain JSON, not `ovos-config` yet —
   see `DEVELOPER.md`), pre-filled from `hass.config` where possible, exposed as `text`/
   `number`/`select` entities on a 30s-polling `DataUpdateCoordinator`.
2. **Per-skill management via config subentries** — implemented and verified: one subentry
   per installed skill, add flow pulls a dropdown from the real 36-skill catalog, picking one
   calls [haos-ovos-addons/ovos-skills](https://github.com/andlo/haos-ovos-addons/tree/master/ovos-skills)'
   install API. Confirmed on real hardware — the skill genuinely installs, not just the
   subentry getting created. Per-skill settings from `settingsmeta.json` not started yet.
   Replaces the earlier standalone-webapp plan (`ovos-skill-browser`, now archived).

See [DEVELOPER.md](DEVELOPER.md) for the architecture, open questions, and how this relates
to the other HA-OVOS repos.

## About

Part of the **HA-OVOS** project: making it easy for a Home Assistant OS user to discover and
use OpenVoiceOS, through interfaces that feel native to HAOS. See
[haos-ovos-addons](https://github.com/andlo/haos-ovos-addons) for the Supervisor add-ons —
including `ovos-skills`, the skill-management API this integration's config subentries call.

## License

![license](https://img.shields.io/badge/license-Apache--2.0-blue)

Licensed under the [Apache License 2.0](LICENSE), matching OpenVoiceOS's own project license.

The OpenVoiceOS logo is used with attribution to the [OpenVoiceOS project](https://openvoiceos.org); this project is not officially affiliated with or endorsed by OpenVoiceOS.
