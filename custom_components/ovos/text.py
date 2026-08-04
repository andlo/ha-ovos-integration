"""Language as an editable text entity."""
from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN, CONF_LANG
from .shared_config import read_shared_config, write_shared_config_key


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities):
    shared = await hass.async_add_executor_job(read_shared_config)
    current = shared.get(CONF_LANG, entry.data[CONF_LANG])
    add_entities([OvosLanguageText(entry, current)])


class OvosLanguageText(TextEntity):
    """Editable OVOS language code (e.g. en-us), written to the shared file."""

    _attr_has_entity_name = True
    _attr_name = "Language"
    _attr_icon = "mdi:translate"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, current_value: str) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_lang"
        self._attr_native_value = current_value

    async def async_set_value(self, value: str) -> None:
        self._attr_native_value = value
        await self.hass.async_add_executor_job(
            write_shared_config_key, CONF_LANG, value
        )
        self.async_write_ha_state()
