"""Sensors (#10): state, last question/answer, and the device's own sensors
(ovos.phal.sensor -- the messages ovos-PHAL-sensors already uses, so any
OVOS with such a plugin shows its sensors without the integration knowing
the device)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity

from ..const import DOMAIN
from .bus import STATES, OvosDevice
from .entity import CAP_BASE, OvosDeviceEntity, setup_capabilities


def _entities(device: OvosDevice, cap: str) -> list:
    if cap == CAP_BASE:
        return [OvosState(device), OvosText(device, "last_question"),
                OvosText(device, "last_answer")]
    if cap.startswith("sensor:"):
        sid = cap.removeprefix("sensor:")
        if sid in device.sensors and not device.sensors[sid]["binary"]:
            return [OvosPhalSensor(device, sid)]
    return []


async def async_setup_entry(hass, entry, add_entities):
    setup_capabilities(hass, entry, add_entities, _entities)


class OvosState(OvosDeviceEntity, SensorEntity):
    """idle / listening / thinking / speaking / sleeping"""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATES

    def __init__(self, device: OvosDevice) -> None:
        super().__init__(device, "state")

    @property
    def native_value(self) -> str:
        return self.device.state


class OvosText(OvosDeviceEntity, SensorEntity):
    """The last question heard and the last answer spoken."""

    @property
    def native_value(self) -> str | None:
        return getattr(self.device, self._attr_translation_key)


class OvosPhalSensorBase(OvosDeviceEntity):
    """One sensor a device announced. Named by the device (it knows best what
    its sensors are, in its own language), so no translation key."""

    _attr_translation_key = None

    def __init__(self, device: OvosDevice, sensor_id: str) -> None:
        super().__init__(device, f"phal_{sensor_id}")
        self._attr_translation_key = None
        self._sensor_id = sensor_id
        self._attr_name = device.sensors[sensor_id]["name"]

    @property
    def _sensor(self) -> dict[str, Any]:
        return self.device.sensors.get(self._sensor_id, {})

    @property
    def icon(self) -> str | None:
        return (self._sensor.get("attributes") or {}).get("icon")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        skip = {"icon", "unit_of_measurement", "device_class", "friendly_name"}
        return {k: v for k, v in (self._sensor.get("attributes") or {}).items()
                if k not in skip}


class OvosPhalSensor(OvosPhalSensorBase, SensorEntity):

    @property
    def native_value(self) -> Any:
        state = self._sensor.get("state")
        return state if isinstance(state, (int, float, str)) or state is None else str(state)

    @property
    def native_unit_of_measurement(self) -> str | None:
        return (self._sensor.get("attributes") or {}).get("unit_of_measurement")

    @property
    def device_class(self) -> SensorDeviceClass | None:
        value = (self._sensor.get("attributes") or {}).get("device_class")
        try:
            return SensorDeviceClass(value) if value else None
        except ValueError:
            return None
