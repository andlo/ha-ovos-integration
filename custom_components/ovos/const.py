"""Constants for the OpenVoiceOS shared config integration."""

DOMAIN = "ovos"

# Device identifier for the one device grouping every global OVOS
# setting entity (language, units, formats, location, confirm-listening,
# API URLs) -- confirmed missing was a real, reported gap: without an
# explicit device, these entities had nowhere to show up as a group on
# the integration's own page, unlike skills which each get their own
# device via a subentry or sensor.py's own hub-device fallback. Created
# once via device_registry.async_get_or_create in __init__.py, same
# pattern sensor.py's own _ensure_hub_device already uses for the
# Skills/Skills Extra hub devices -- entities then just reference it by
# identifiers alone, they don't recreate it.
CORE_SETTINGS_DEVICE_ID = "core_settings"

# Shared config file written and read by both this integration and every
# add-on in haos-ovos-addons. All of them export XDG_CONFIG_HOME=/share,
# which is what makes /share/mycroft/mycroft.conf the common ground —
# see haos-ovos-addons and this repo's DEVELOPER.md for the full story.
SHARED_CONFIG_PATH = "/share/mycroft/mycroft.conf"

CONF_LANG = "lang"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_TIMEZONE = "timezone"
CONF_SYSTEM_UNIT = "system_unit"

UNIT_METRIC = "metric"
UNIT_IMPERIAL = "imperial"

# The rest of ovos-config's own top-level preference settings (see its
# own mycroft.conf's comments, read directly from the installed package
# rather than guessed at) -- everything here is a simple, global
# preference, not a nested plugin config or internal wiring setting
# (contrast e.g. websocket/hivemind/log sections, deliberately NOT
# exposed as entities: editing those wrong risks breaking the shared
# bus every add-on in this project depends on, not just a preference).
CONF_TEMPERATURE_UNIT = "temperature_unit"
CONF_WINDSPEED_UNIT = "windspeed_unit"
CONF_PRECIPITATION_UNIT = "precipitation_unit"
CONF_TIME_FORMAT = "time_format"
CONF_SPOKEN_TIME_FORMAT = "spoken_time_format"
CONF_DATE_FORMAT = "date_format"
CONF_CONFIRM_LISTENING = "confirm_listening"

# Defaults matching ovos-config's own baked-in mycroft.conf exactly
# (confirmed by reading the installed package's own file directly) --
# used as this integration's own fallback when the shared file has no
# explicit override yet, same pattern CONF_SYSTEM_UNIT's own entity
# already uses. Not guessed: a real ovos-core add-on install, asked via
# its own Configuration()-backed /config endpoint, confirmed each of
# these exact values are what's actually in effect on an untouched
# install.
DEFAULT_TEMPERATURE_UNIT = "celsius"
DEFAULT_WINDSPEED_UNIT = "m/s"
DEFAULT_PRECIPITATION_UNIT = "mm"
DEFAULT_TIME_FORMAT = "half"
DEFAULT_SPOKEN_TIME_FORMAT = "full"
DEFAULT_DATE_FORMAT = "MDY"
DEFAULT_CONFIRM_LISTENING = True

TEMP_CELSIUS = "celsius"
TEMP_FAHRENHEIT = "fahrenheit"
WINDSPEED_UNITS = ["km/h", "m/s", "mph", "kn"]
PRECIPITATION_UNITS = ["mm", "inch"]
TIME_FORMATS = ["half", "full"]  # half: "11:37 pm", full: "23:37"
DATE_FORMATS = ["MDY", "DMY"]  # MDY: "11-29-1978", DMY: "29-11-1978"

# The ovos-skills add-on's own base URL (e.g. http://<hostname>:8500) — its
# Supervisor-assigned hostname is repo-hash-specific and not something we
# can guess reliably, so this is a person-provided value, same pattern as
# the other shared-config fields: a text entity, seeded once, editable
# any time. Stored under a top-level key of its own, not nested under
# "skills" (that section is SkillsStore's own, on the ovos-skills side).
CONF_SKILLS_API_URL = "ha_ovos_skills_api_url"

# Same pattern, for ovos-core's own base URL (e.g. http://<hostname>:8500)
# -- needed to call its /autoconfigure endpoint (see voice_subentry.py).
# Same reasoning as CONF_SKILLS_API_URL: repo-hash-specific hostname,
# person-provided, a text entity rather than guessed.
CONF_CORE_API_URL = "ha_ovos_core_api_url"

# Same pattern again, for ovos-persona's own bridge API (e.g.
# http://<hostname>:8338 -- see persona_subentry.py). Deliberately
# independent of CONF_SKILLS_API_URL/CONF_CORE_API_URL, not derived from
# either: a person can genuinely run ovos-persona without ovos-skills,
# ovos-skills without ovos-persona, or both -- raised directly, see
# DEVELOPER.md.
CONF_PERSONA_API_URL = "ha_ovos_persona_api_url"

# Same pattern again, for the ovos-skills-extra add-on's own base URL
# (e.g. http://<hostname>:8502). Deliberately independent, same
# reasoning as the other three -- ovos-skills-extra is entirely
# optional, a person may run only the curated ovos-skills, or neither.
CONF_SKILLS_EXTRA_API_URL = "ha_ovos_skills_extra_api_url"

# Optional base URL for a self-hosted ovos-skill-config-tool instance
# (https://github.com/OscillateLabsLLC/ovos-skill-config-tool) -- a
# separate, third-party, generic settings.json editor with no type
# restrictions (handles nested objects/arrays, which this integration's
# own live settings entities deliberately don't attempt to represent).
# Not one of this project's own add-ons and not auto-discovered via
# Supervisor for that reason -- a person who chooses to self-host it
# points this at wherever they run it. Purely additive: used only to
# set each skill device's own `configuration_url` (see sensor.py) as an
# escape hatch for settings this integration's own entities can't
# cover, never a replacement for them.
CONF_SKILL_CONFIG_TOOL_URL = "ha_ovos_skill_config_tool_url"
