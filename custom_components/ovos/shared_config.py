"""Read/write helpers for the shared /share/mycroft/mycroft.conf file.

Deliberately plain json.load/json.dump for this first version — not
ovos-config's Configuration() class. Installing a new pip requirement into
a live Home Assistant Core environment is not something to do as a side
effect of a v1 skeleton; see DEVELOPER.md's "remaining unknown" about
whether ovos-config conflicts with HA Core's own dependencies. The shared
file only has a handful of top-level keys we touch here, so plain JSON is
enough for now. Revisit if/when ovos-config's compatibility is confirmed
by someone deliberately choosing to test it.
"""
from __future__ import annotations

import json
import os

from .const import SHARED_CONFIG_PATH


def read_shared_config() -> dict:
    """Read the shared mycroft.conf, returning {} if it doesn't exist yet."""
    if not os.path.isfile(SHARED_CONFIG_PATH):
        return {}
    try:
        with open(SHARED_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def write_shared_config_key(key: str, value) -> None:
    """Merge a single top-level key into the shared file without clobbering
    the others — same merge-not-overwrite principle haos-ovos-addons uses.
    """
    os.makedirs(os.path.dirname(SHARED_CONFIG_PATH), exist_ok=True)
    data = read_shared_config()
    data[key] = value
    tmp_path = SHARED_CONFIG_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, SHARED_CONFIG_PATH)
