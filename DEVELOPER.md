# Developer notes — ha-ovos-integration

🚧 Planning stage. This describes the idea and the open questions to resolve before writing
code, not a finished spec.

## The idea

The [haos-ovos-addons](https://github.com/andlo/haos-ovos-addons) plan originally called for
either a shared `mycroft.conf` file, or per-add-on ingress config pages (the same pattern
`ovos-skill-config-tool` uses). A real HA **integration** is a better fit than either:

- It puts configuration where a HAOS user already looks — entities under
  Settings → Devices & services — instead of a bespoke webpage they have to discover.
- For skills specifically, OVOS skills already ship a `settingsmeta.json` describing their
  configurable fields (name, type, default, description). That's structurally the same thing
  HA integrations already do with their own config/options schemas — reusing it beats
  inventing a third config format or wrapping `ovos-skill-config-tool` in ingress.

## Two things this integration aims to do

### 1. Shared OVOS configuration

Language, location, units, and other `mycroft.conf` fields, read/written via `ovos-config`
and exposed as HA entities (select/text/number), so setting language once applies everywhere
instead of every add-on holding its own disconnected copy.

### 2. Per-skill settings from `settingsmeta.json`

For each installed skill, read its `settingsmeta.json` and generate matching HA entities
(number/select/text/switch per setting) automatically. Skills already declare their settings
in this format for OVOS's own UI layers — this integration would just be another consumer of
that same convention, kept in sync with whatever skills are actually installed.

## Open questions (resolve before writing code)

### Filesystem access across HA Core and add-ons

An HA integration runs inside HA Core's own container, not inside a Supervisor add-on's — it
cannot read an add-on's private filesystem directly. `/share` is mounted into Core, Supervisor,
and add-ons alike in HAOS specifically for this kind of cross-component data, so this is
solvable, but it means:

- Every relevant add-on (including a future skills add-on) needs to deliberately store its
  config/settings under a shared path like `/share/ovos/...` for the integration to reach it.
- This is a design decision to lock in **now**, across `haos-ovos-addons` too, not something
  that falls out for free — the existing add-ons currently write `mycroft.conf` inside their
  own container's `~/.config/mycroft/`, not `/share`.

### Does `ovos-config` work standalone?

`ovos-config`'s `Configuration()` class does layered config merging (user + system + default),
which is exactly the merge behavior we want reused rather than reimplemented. Not yet
confirmed:

- Whether it works standalone without a live OVOS messagebus connection (an integration
  running in HA Core has no OVOS bus to connect to).
- Whether HA Core's Python environment can host it cleanly alongside HA's own dependencies
  (version conflicts, unwanted transitive deps — the kind of thing that bit
  `haos-ovos-addons` repeatedly).

Worth a quick spike — install `ovos-config` in isolation and see what it actually needs — before
designing entities around it.

## Relationship to the other repos

- [haos-ovos-addons](https://github.com/andlo/haos-ovos-addons) — the Supervisor add-ons this
  integration would read shared config from and complement.
- [ovos-skill-browser](https://github.com/andlo/ovos-skill-browser) — installs skills; this
  integration would surface their settings once installed.
- [haos-ovos-skills](https://github.com/andlo/haos-ovos-skills) — deferred; if built, would
  also need to write its config under the same shared `/share/ovos/...` convention.
