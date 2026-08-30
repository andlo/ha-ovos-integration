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

# Same idea, for the one device grouping ovos-persona's own live
# entities (solver list, reachability, fallback-skill setup) -- moved
# here from a one-off "Add sub-entry" flow (persona_subentry.py,
# removed) after direct agreement: entity for data, button for the
# one-off fallback-skill action, sensor for status, no flow left. Its
# own auto-created "persona" subentry, same pattern as
# CORE_SETTINGS_DEVICE_ID's own "core_settings" subentry.
PERSONA_DEVICE_ID = "persona"

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

# Declarative tables for ovos-config's own deeper intent-pipeline
# settings (intents.adapt/padatious/common_query/OCP -- see each
# add-on's own DOCS.md/DEVELOPER.md for the full mycroft.conf
# investigation this is based on). Raised directly: build this so a
# FUTURE setting is one row here, not a new class/new add_entities
# call -- these tables are the single thing that needs editing to
# expose one more leaf value. Each generic entity class (OvosNested*
# in its own platform file) takes a row from the matching table
# directly as its constructor arguments, in the same order as that
# class's own __init__ signature.
#
# Deliberately NOT ovos-config's own intents.pipeline (the ordered
# 13-stage matching sequence): that's a list defining ORDER, not a
# leaf value, and doesn't fit any of these simple entity types --
# raised and settled directly, not attempted here.
#
# Each row: (path_parts, name, icon, default, min, max, step)
CORE_NUMBER_SETTINGS = [
    (["intents", "adapt", "conf_high"], "Adapt confidence (high)", "mdi:gauge", 0.65, 0.0, 1.0, 0.01),
    (["intents", "adapt", "conf_med"], "Adapt confidence (medium)", "mdi:gauge", 0.45, 0.0, 1.0, 0.01),
    (["intents", "adapt", "conf_low"], "Adapt confidence (low)", "mdi:gauge", 0.25, 0.0, 1.0, 0.01),
    (["intents", "padatious", "conf_high"], "Padatious confidence (high)", "mdi:gauge", 0.95, 0.0, 1.0, 0.01),
    (["intents", "padatious", "conf_med"], "Padatious confidence (medium)", "mdi:gauge", 0.8, 0.0, 1.0, 0.01),
    (["intents", "padatious", "conf_low"], "Padatious confidence (low)", "mdi:gauge", 0.5, 0.0, 1.0, 0.01),
    (["intents", "common_query", "max_response_wait"], "Common Query max wait", "mdi:timer-sand", 6, 1, 60, 1),
    (["intents", "common_query", "extension_time"], "Common Query extension time", "mdi:timer-sand", 3, 0, 30, 1),
    (["intents", "OCP", "classifier_threshold"], "OCP classifier threshold", "mdi:gauge", 0.4, 0.0, 1.0, 0.01),
    (["intents", "OCP", "min_score"], "OCP minimum score", "mdi:gauge", 40, 0, 100, 1),
    (["skills", "converse", "timeout"], "Converse timeout", "mdi:timer-outline", 300, 5, 3600, 5),
    (["skills", "converse", "max_activations"], "Converse max activations/min", "mdi:counter", -1, -1, 100, 1),
]

# Each row: (path_parts, name, icon, default)
CORE_SWITCH_SETTINGS = [
    (["intents", "padatious", "stem"], "Padatious stemming", "mdi:alphabetical-variant", False),
    (["intents", "padatious", "cast_to_ascii"], "Padatious cast to ASCII", "mdi:translate", False),
    (["intents", "padatious", "disable_padaos"], "Padatious disable exact-match regex", "mdi:regex", False),
    (["intents", "padatious", "domain_engine"], "Padatious domain engine", "mdi:sitemap", False),
    (["intents", "padatious", "single_thread"], "Padatious single-threaded", "mdi:thread-lock", True),
    (["intents", "OCP", "experimental_media_classifier"], "OCP experimental media classifier", "mdi:flask", False),
    (["intents", "OCP", "experimental_binary_classifier"], "OCP experimental binary classifier", "mdi:flask", False),
    (["intents", "OCP", "legacy"], "OCP legacy audio service", "mdi:history", False),
    (["intents", "OCP", "filter_media"], "OCP filter wrong media type", "mdi:filter", True),
    (["intents", "OCP", "filter_SEI"], "OCP filter unplayable results", "mdi:filter", True),
    (["intents", "OCP", "search_fallback"], "OCP fall back to generic search", "mdi:magnify", True),
    (["skills", "converse", "cross_activation"], "Converse cross-activation", "mdi:swap-horizontal", True),
    (["skills", "converse", "cross_deactivation"], "Converse cross-deactivation", "mdi:swap-horizontal", True),
]

# Each row: (path_parts, name, icon, default, options) -- default
# kept as its real native type (int 0, not string "0") -- see
# OvosNestedSelect's own docstring in select.py for why this matters.
CORE_SELECT_SETTINGS = [
    (["intents", "OCP", "playback_mode"], "OCP playback mode", "mdi:play-circle-outline", 0, ["0", "10", "20"]),
    (["skills", "converse", "converse_mode"], "Converse mode", "mdi:forum-outline", "accept_all", ["accept_all", "whitelist", "blacklist"]),
    (["skills", "converse", "converse_activation"], "Converse activation mode", "mdi:forum-outline", "accept_all", ["accept_all", "priority", "whitelist", "blacklist"]),
    (["skills", "fallbacks", "fallback_mode"], "Fallback mode", "mdi:arrow-decision-outline", "accept_all", ["accept_all", "whitelist", "blacklist"]),
]

# Each row: (path_parts, name, icon, default) -- reuses text.py's own
# already-generic OvosNestedText directly, no new class needed.
CORE_TEXT_SETTINGS = [
    (["intents", "common_query", "reranker"], "Common Query reranker", "mdi:sort", "ovos-choice-solver-bm25"),
]

# Each row: (path_parts, name, icon, default_list) -- lists of names
# ovos-config itself stores as a JSON array, edited here as a plain
# comma-separated text field (OvosNestedList in text.py). Deliberately
# NO validation against a fixed set of known-valid names -- raised
# directly: intents.pipeline's own valid stage names (and skill_ids
# for the others) are not a closed set this integration can hardcode
# a check against; OVOS itself can add/remove/rename pipeline stages
# over time, and skills are installed/removed freely. Only whitespace
# trimming and dropping empty entries (from a stray leading/trailing/
# double comma) happens here -- real validation of the CONTENT is left
# to OVOS itself at the point it actually reads this config, the same
# as if it had been hand-edited in mycroft.conf directly.
#
# intents.pipeline's own default here is ovos-config's own real
# baked-in default order, confirmed by reading its own default
# mycroft.conf directly -- not reordering it, just making the existing
# default editable.
CORE_LIST_SETTINGS = [
    (["intents", "pipeline"], "Intent pipeline order", "mdi:sort-variant", [
        "stop_high", "converse", "ocp_high", "padatious_high", "adapt_high",
        "ocp_medium", "fallback_high", "stop_medium", "adapt_medium", "adapt_low",
        "common_qa", "fallback_medium", "fallback_low",
    ]),
    (["skills", "blacklisted_skills"], "Blacklisted skills", "mdi:cancel", ["skill-ovos-stop.openvoiceos"]),
    (["skills", "converse", "converse_whitelist"], "Converse whitelist", "mdi:check-circle-outline", []),
    (["skills", "converse", "converse_blacklist"], "Converse blacklist", "mdi:cancel", []),
    (["skills", "fallbacks", "fallback_whitelist"], "Fallback whitelist", "mdi:check-circle-outline", []),
    (["skills", "fallbacks", "fallback_blacklist"], "Fallback blacklist", "mdi:cancel", []),
]

