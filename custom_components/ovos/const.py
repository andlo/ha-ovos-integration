"""Constants for the OpenVoiceOS shared config integration."""

DOMAIN = "ovos"

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
