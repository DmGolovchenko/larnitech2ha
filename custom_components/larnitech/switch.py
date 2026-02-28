from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .client import LarnitechClient, DeviceInfo as LarnitechDeviceInfo

SUPPORTED_SWITCH_TYPES = {"switch", "relay", "socket", "script", "unknown"}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    client: LarnitechClient = hass.data[DOMAIN][entry.entry_id]["client"]

    entities = []
    for dev in client.devices.values():
        if dev.type in SUPPORTED_SWITCH_TYPES:
            entities.append(LarnitechSwitch(client, dev))

    async_add_entities(entities)


class LarnitechSwitch(SwitchEntity):
    def __init__(self, client: LarnitechClient, dev: LarnitechDeviceInfo) -> None:
        self._client = client
        self._dev = dev
        self._addr = dev.addr
        self._unsub = None

    @property
    def unique_id(self) -> str:
        return f"larnitech_switch_{self._addr}"

    @property
    def name(self) -> str:
        return self._dev.name

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
    def extra_state_attributes(self):
        return {"addr": self._addr, "type": self._dev.type, "area": self._dev.area}

    def _status(self) -> dict:
        return self._client.states.get(self._addr, {})

    @property
    def is_on(self) -> bool:
        val = self._status().get("state")
        if isinstance(val, str):
            return val.lower() == "on"
        if isinstance(val, (int, float)):
            return val != 0
        return False

    async def async_turn_on(self, **kwargs):
        await self._client.status_set(self._addr, {"state": "on"})

    async def async_turn_off(self, **kwargs):
        await self._client.status_set(self._addr, {"state": "off"})

    async def async_added_to_hass(self):
        def _on_status(addr: str, status: dict):
            if addr == self._addr:
                self.async_write_ha_state()

        self._unsub = self._client.add_status_listener(_on_status)

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None