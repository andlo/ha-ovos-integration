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

## Open questions — status as of tonight's spike

### ✅ Filesystem access across HA Core and add-ons — resolved and implemented

`/share/mycroft/mycroft.conf` is now the shared config path, and `haos-ovos-addons`'s four
add-ons already write there (as of `haos-ovos-addons` commit extending the `/share`
convention to stt/wakeword/persona). Confirmed on real hardware: all four add-ons build,
start cleanly, and merge into the same file without clobbering each other's sections (each
add-on does a read-merge-write of only its own top-level key, e.g. `tts`, `stt`, `hotwords`).

This integration can now assume that path exists and is kept in sync by the add-ons — no
further coordination needed on that side before starting on the integration itself.

### ✅ Does `ovos-config` work standalone? — resolved, yes

Confirmed via spike:
- `Configuration()` loads in ~0.15s with **no messagebus connection** required.
- Dependencies are lightweight and pure-Python (`combo-lock`, `ovos-utils`,
  `python-dateutil`, `PyYAML`, `rich-click`; `ovos-utils` itself adds `json_database`,
  `kthread`, `pexpect`, `pyee`, `requests`, `rich`, `watchdog`) — nothing that looks likely to
  conflict badly with HA Core's own dependency set, though not yet tested installed
  *alongside* HA Core specifically.
- **It already respects `XDG_CONFIG_HOME`**, confirmed by setting it to a custom path and
  seeing `Configuration()` resolve to `<path>/mycroft/mycroft.conf` accordingly. This is what
  makes the shared `/share/mycroft/mycroft.conf` convention above work with zero custom code
  on either side — both the add-ons and this integration just need `XDG_CONFIG_HOME=/share`
  set in their respective environments, and `ovos-config`'s own logic does the rest.

**Remaining unknown**: only whether installing `ovos-config` inside HA Core's actual Python
environment (not an isolated venv) causes any dependency conflicts with HA Core's own
packages. Worth checking directly once there's a HACS-installable custom_component skeleton
to test against, rather than guessing further in isolation.

## Relationship to the other repos

- [haos-ovos-addons](https://github.com/andlo/haos-ovos-addons) — the Supervisor add-ons this
  integration would read shared config from and complement.
- [ovos-skill-browser](https://github.com/andlo/ovos-skill-browser) — installs skills; this
  integration would surface their settings once installed.
- [haos-ovos-skills](https://github.com/andlo/haos-ovos-skills) — deferred; if built, would
  also need to write its config under the same shared `/share/ovos/...` convention.
