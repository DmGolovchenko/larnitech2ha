from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .client import LarnitechClient, DeviceInfo as LarnitechDeviceInfo


SUPPORTED_TYPES = {"leak-sensor"}


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
):
    client: LarnitechClient = hass.data[DOMAIN][entry.entry_id]["client"]

    entities: list[BinarySensorEntity] = []
    for dev in client.devices.values():
        if dev.type in SUPPORTED_TYPES:
            entities.append(LarnitechLeakSensor(client, dev))

    async_add_entities(entities)


class LarnitechLeakSensor(BinarySensorEntity):
    """Larnitech leak sensor: ok/leakage -> binary_sensor.moisture"""

    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(self, client: LarnitechClient, dev: LarnitechDeviceInfo) -> None:
        self._client = client
        self._dev = dev
        self._addr = dev.addr
        self._unsub = None

    @property
    def unique_id(self) -> str:
        return f"larnitech_leak_{self._addr}"

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
    def is_on(self) -> bool:
        state = self._status().get("state")

        # leakage => True, ok => False
        if isinstance(state, str):
            s = state.lower()
            if s == "leakage":
                return True
            if s == "ok":
                return False

            # небольшой запас на вариации
            if s in ("leak", "alarm", "wet", "on", "true", "1"):
                return True
            if s in ("dry", "off", "false", "0"):
                return False

        if isinstance(state, bool):
            return state
        if isinstance(state, (int, float)):
            return state != 0

        return False

    @property
    def extra_state_attributes(self):
        st = self._status()
        return {
            "addr": self._addr,
            "type": self._dev.type,
            "area": self._dev.area,
            "raw_state": st.get("state"),
        }

    async def async_added_to_hass(self):
        def _on_status(addr: str, status: dict):
            if addr == self._addr:
                self.async_write_ha_state()

        self._unsub = self._client.add_status_listener(_on_status)

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None