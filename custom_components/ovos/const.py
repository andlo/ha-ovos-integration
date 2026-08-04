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
