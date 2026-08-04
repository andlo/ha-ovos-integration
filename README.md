# ha-ovos-integration

![status](https://img.shields.io/badge/status-work%20in%20progress-orange)
![status](https://img.shields.io/badge/status-verified%20on%20real%20hardware-brightgreen)

<img src="logo.png" width="96" height="96" alt="OpenVoiceOS logo">

> 🚧 **Work in progress — v0.0.4, confirmed working end-to-end including two-way sync.**
> Config flow pre-fill, writes from HA, and picking up edits made completely outside HA (a
> direct file edit surfaced within the 30s poll interval, no restart needed) all verified on
> real hardware. Integration display name is **"OpenVoiceOS"** in Add Integration — not
> "OpenVoiceOS shared config" as earlier versions showed, since the same domain will also
> host per-skill settings entities later and the name shouldn't be tied to v1's scope.

A Home Assistant **integration** (HACS-distributed `custom_component`, not a Supervisor
add-on) for configuring OVOS the way HAOS users already configure everything else: as
entities under Settings → Devices & services, not raw JSON fields or a bespoke webpage.

Two things it aims to do:

1. **Shared OVOS configuration** (language, location, units) — v1, implemented and verified:
   reads/writes `/share/mycroft/mycroft.conf` directly (plain JSON, not `ovos-config` yet —
   see `DEVELOPER.md`), pre-filled from `hass.config` where possible, exposed as `text`/
   `number`/`select` entities on a 30s-polling `DataUpdateCoordinator`.
2. **Per-skill management via config subentries** — not started. One subentry per installed
   skill, calling a small API in [haos-ovos-addons/ovos-skills](https://github.com/andlo/haos-ovos-addons/tree/master/ovos-skills)
   to install/remove and generate settings from each skill's `settingsmeta.json`. Replaces
   the earlier standalone-webapp plan (`ovos-skill-browser`, now archived).

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
