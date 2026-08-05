# Developer notes — ha-ovos-integration

## The idea

A real HA integration, not a bespoke webpage or per-add-on ingress page, fits how a HAOS user already expects to configure things: entities under Settings → Devices & services. OVOS skills already ship a `settingsmeta.json` describing their configurable fields — structurally the same thing HA integrations already do with their own config/options schemas, reused rather than reinvented.

Talks to the add-ons in [haos-ovos-addons](https://github.com/andlo/haos-ovos-addons). Open items and known gaps are tracked as [GitHub Issues](https://github.com/andlo/ha-ovos-integration/issues), not in this file.

## Shared configuration: polling, not file watching

Entities (language, units, API URLs, ...) read `/share/mycroft/mycroft.conf` via a `DataUpdateCoordinator` on a 30s poll interval, not a file watcher. Deliberate: `watchdog`-style file events fire from an OS thread outside HA's asyncio loop (a real source of subtle bugs to bridge correctly); every add-on writes via atomic rename (`jq > file.tmp && mv file.tmp file`), which a watcher would need to specifically handle; and the data itself (language, location, units) changes a handful of times a year, not something that needs instant reactivity. A `DataUpdateCoordinator` also means one file read per interval serves every entity regardless of count — adding more entities later doesn't change this cost either way.

## Config flow pre-fill sources

The shared-config flow pre-fills from `hass.config` directly: `language`+`country` combine into OVOS's `lang` format (a suggested default, not locked — a household running OVOS in a different working language than HA's own UI is a real case); `time_zone` maps directly (IANA names match); `latitude`/`longitude` copy directly; `unit_system.length` (`"km"` vs `"mi"`) maps to `system_unit`. City/state breakdown isn't available from HA Core and is left blank rather than guessed.

## Skill management: one config subentry per skill

**Two-step add flow**, not one: a name-only dropdown first, then a confirmation step showing the selected skill's full description before install starts. A single dropdown with "Name — description" per option was confirmed, by screenshot, to wrap onto multiple lines and become hard to scan once the catalog had more than a handful of entries.

**A single subentry type**, not two. Splitting into `skill` (no reconfigure) and `skill_advanced` (has settings) was considered, to avoid showing a "Reconfigure" option on skills with no settings — rejected because `strings.json`'s `initiate_flow` key means every registered subentry type gets its own visible "Add [type]" menu entry, with no documented way to register one hidden from that menu. Showing "Skill" and "Skill (advanced)" as two confusing, similarly-named add options was worse than the alternative: a single type, and a clean "no settings available" abort message on skills without any.

**The confirmed-real `skill_id`, not the catalog's guess, is what a subentry gets created with.** The install flow polls the add-on's own job status and waits for the real result — the catalog's own `skill_id` field doesn't reliably match what a skill actually registers as at runtime, and creating a subentry with the wrong one silently broke settings lookups for every skill installed that way.

## Relationship to the other repo

[haos-ovos-addons](https://github.com/andlo/haos-ovos-addons) — the Supervisor add-ons this integration configures. See in particular `ovos-skills`/`ovos-skills-extra` (the skill install APIs this integration's subentries call) and `ovos-persona` (the solver-configuration API).
