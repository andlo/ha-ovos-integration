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

**Pre-fill the config flow from HA Core's own settings** — confirmed available directly on
`hass.config` (checked against real system data, not assumed):

| HA Core field | Example value seen | Maps to `mycroft.conf` | Notes |
|---|---|---|---|
| `language` | `"en"` | `lang` | Needs a region suffix OVOS expects (e.g. `en-us`). HA only gives the bare language code — combine with `country` as a *suggested default*, not a hardcoded truth, and let the user confirm/edit. |
| `country` | `"DK"` | (used to build `lang`) | See above — `f"{language}-{country}".lower()` is a reasonable guess, not guaranteed correct (e.g. `en-dk` isn't a real OVOS locale, just the best guess from what HA exposes). |
| `time_zone` | `"Europe/Copenhagen"` | `location.timezone.code` | Direct IANA tz name match, no translation needed. |
| `latitude` / `longitude` | `55.986...` / `12.497...` | `location.coordinate.latitude/longitude` | Direct copy. |
| `unit_system.length` | `"km"` vs `"mi"` | `system_unit` (`metric`/`imperial`) | Check this one field: `"km"` → `metric`, `"mi"` → `imperial`. HA doesn't expose the whole unit system as a single flat label in the data we could inspect, this field is the reliable proxy. |

**Not available from HA Core**: city/state name breakdown (`location.city.*` in
`mycroft.conf`'s schema). HA only has a user-given `location_name` (e.g. "Hjem" —
Danish for "Home", not a real place name) and raw coordinates, no structured city/country
lookup. Leave that section of the config flow optional/blank rather than guessing from a
freeform name, or reverse-geocode from lat/long if this ever feels worth the added
dependency.

**Design principle**: pre-fill, don't lock. These are suggested defaults in the config flow
form, editable before submit — HA's own settings are a good starting guess, not a source of
truth OVOS must match exactly (a household using OVOS in a different working language than
their HA install's UI language is a real, plausible case).

### 2. Per-skill management via config subentries

Skills are managed as **HA config subentries** — one per installed skill, living under this
integration's main entry (Settings → Devices & services → OpenVoiceOS → Add sub-entry).
Replaces the earlier plan of a standalone web app (`ovos-skill-browser`, now archived): same
place as everything else in HA, and it directly answers that repo's one open question ("does
Install actually reach a live instance?") by construction — the integration calls the API
itself, no ambiguity.

**Add flow**: dropdown of the official OVOS skill catalog (36 skills — confirmed via the
GitHub API, genuinely small enough for a dropdown; see `haos-ovos-addons`'s `ovos-skills/DOCS.md`
for the count and how it was checked). Picking one calls `ovos-skills`'s install API.

**Per-subentry config**: a `reconfigure` step on the subentry. Confirmed for real by
installing multiple skills and reading their actual `settingsmeta.json` (or lack of one):
not every skill has one (`date-time` does, `fallback-chatgpt` doesn't), and the only field
type confirmed against real data is `checkbox` — its `settingsmeta.json` `"value"` is
literally the string `"false"`, not a JSON boolean, which the reconfigure flow normalizes.
Any skill without a settingsmeta, or with field types we haven't confirmed how to map yet
(e.g. `select`, seen mentioned in an OVOS community discussion but not verified against real
data), falls back to a single raw-JSON editor for its `settings.json` — same pattern already
used for TTS/STT plugin config and persona's solver list, rather than guessing at an unseen
schema.

Also surfaced a real gotcha: the catalog's `package_name` field doesn't always match what pip
actually installs a skill as (confirmed: catalog says `ovos-skill-ovos-fallback-chatgpt`,
real installed name is `skill-ovos-fallback-chatgpt`) — `ovos-skills`' settingsmeta lookup
does a normalized fuzzy match against actually-installed packages instead of trusting the
catalog's name literally.

**Remove flow**: deleting the subentry calls the same add-on's uninstall API — currently a
known-broken stub on the `ovos-skills` side (see that repo's `DOCS.md`), not yet wired up
here since there's nothing working to call yet.

**What this explicitly does NOT do**: make the skill respond to voice queries. Installing and
configuring a skill here doesn't wire it into Assist — that needs OVOS's messagebus/HiveMind,
which has no bridge into HA yet. See `ovos-skills`'s DOCS.md in haos-ovos-addons for the full reasoning on
why that's an accepted, separate gap rather than a blocker.

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

## v1 confirmed working end-to-end on real hardware

As of v0.0.3, tested against a real HA Core install (not just syntax-checked):
- Config flow pre-fill and submission works.
- Initial write to the shared file works.
- A restart-persistence bug was found and fixed (see git history on
  `custom_components/ovos/text.py`/`number.py`/`select.py` — entities were reading
  `entry.data`, the original config-flow submission, instead of the current shared file, so
  a restart would silently revert any later edit).
- Rebuilt on a `DataUpdateCoordinator` (30s poll interval) after that fix, so entities also
  pick up external edits (a person editing the file directly, or another add-on writing its
  own section) without needing a restart or manual integration reload.

### Why polling, not file watching

Genuinely considered both. File watching (e.g. via `watchdog`) is more "correct" in the
abstract — instant reaction to the actual write event — but was rejected for three concrete
reasons specific to this data and this environment:

1. **New dependency + thread-safety risk.** `watchdog`'s file-system events fire from an
   OS-level thread outside HA's asyncio event loop; bridging that back in correctly (no
   blocking calls, no dropped events) is a real source of subtle bugs, not just extra code.
2. **The write pattern complicates it further.** Every add-on writes via
   `jq > file.tmp && mv file.tmp file` (atomic rename — correct practice) — a watcher has to
   specifically catch the *rename*, not the more obvious "modified" event on the `.tmp` file.
3. **The data doesn't need instant reactivity.** Language/location/unit settings change a
   handful of times a year, changed by a person or an add-on's startup — not live sensor
   data. The entire value proposition of watching over polling is latency, and here that
   latency genuinely doesn't matter.

**Entity count doesn't favor either approach** — this was floated as a reason to prefer
watching ("more entities are coming, e.g. skill settings") but doesn't hold up: the
`DataUpdateCoordinator` pattern means exactly one file read per interval serves every entity
regardless of count, present or future. Watching would scale the same way. Neither approach's
cost scales with entity count; what matters is how the file is written and how often it
actually changes, and neither of those changes as more entities get added.

## Relationship to the other repos

- [haos-ovos-addons](https://github.com/andlo/haos-ovos-addons) — the Supervisor add-ons this
  integration reads shared config from and complements.
- [haos-ovos-addons/ovos-skills](https://github.com/andlo/haos-ovos-addons/tree/master/ovos-skills) — the API this integration's
  config subentries call to install/list/remove skills and read/write their settings.
