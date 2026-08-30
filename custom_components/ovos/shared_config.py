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


def write_nested_config_key(path_parts: list[str], value) -> None:
    """Write-side helper for a setting more than one level deep
    (location's own sub-fields) -- write_shared_config_key's own flat
    top-level-only merge isn't enough for those. Merges into the
    existing nested structure without disturbing sibling keys at any
    level -- e.g. writing location.city.name doesn't touch location.
    coordinate or location.timezone, same principle write_shared_
    config_key already applies at the top level, extended to work at
    any depth (OvosCoordinateNumber's own _write_value in number.py
    did this by hand for exactly one case, location.coordinate.*; this
    is the same idea made reusable for the rest of location's own
    sub-fields).

    No read-side counterpart here deliberately -- confirmed the hard
    way (a real "Detected blocking call to open... inside the event
    loop" warning on an actual Home Assistant instance): entity state
    getters (native_value etc.) run synchronously in HA Core's own
    event loop and must never do their own file I/O. Reads always go
    through the coordinator's own cached data (self.coordinator.data),
    populated by read_shared_config() running inside
    async_add_executor_job in _async_update_data -- never called
    directly from a property. See text.py's own OvosNestedText for the
    correct pattern (walking self.coordinator.data by hand, not a
    helper that opens the file itself).
    """
    os.makedirs(os.path.dirname(SHARED_CONFIG_PATH), exist_ok=True)
    data = read_shared_config()
    node = data
    for part in path_parts[:-1]:
        if part not in node or not isinstance(node[part], dict):
            node[part] = {}
        node = node[part]
    node[path_parts[-1]] = value
    tmp_path = SHARED_CONFIG_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, SHARED_CONFIG_PATH)
