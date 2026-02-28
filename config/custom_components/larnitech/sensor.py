from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .client import LarnitechClient, DeviceInfo as LarnitechDeviceInfo

SUPPORTED_SENSOR_TYPES = {"temperature-sensor", "illumination-sensor", "motion-sensor", "humidity-sensor", "co2-sensor"}

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    client: LarnitechClient = hass.data[DOMAIN][entry.entry_id]["client"]

    entities = []
    for dev in client.devices.values():
        if dev.type in SUPPORTED_SENSOR_TYPES:
            entities.append(LarnitechSensor(client, dev))

    async_add_entities(entities)

class LarnitechSensor(SensorEntity):
    def __init__(self, client: LarnitechClient, dev: LarnitechDeviceInfo) -> None:
        self._client = client
        self._dev = dev
        self._addr = dev.addr
        self._unsub = None

    @property
    def unique_id(self) -> str:
        return f"larnitech_sensor_{self._addr}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._addr)},
            name=self._dev.name,
            manufacturer="Larnitech",
            model=self._dev.type,
            suggested_area=self._dev.area or None,
            via_device=(DOMAIN, "larnitech_gateway"),
        )

    @property
    def name(self) -> str:
        return self._dev.name

    def _status(self) -> dict:
        return self._client.states.get(self._addr, {})

    @property
    def native_value(self):
        # у тебя status: {"state": 41.62}
        return self._status().get("state")

    @property
    def device_class(self):
        if self._dev.type == "temperature-sensor":
            return SensorDeviceClass.TEMPERATURE
        if self._dev.type == "illumination-sensor":
            return SensorDeviceClass.ILLUMINANCE
        return None

    @property
    def native_unit_of_measurement(self):
        if self._dev.type == "temperature-sensor":
            return "°C"
        if self._dev.type == "illumination-sensor":
            return "lx"
        return None

    async def async_added_to_hass(self):
        def _on_status(addr: str, status: dict):
            if addr == self._addr:
                self.async_write_ha_state()

        self._unsub = self._client.add_status_listener(_on_status)

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None