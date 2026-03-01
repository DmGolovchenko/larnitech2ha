from __future__ import annotations

from homeassistant.components.valve import (
    ValveEntity,
    ValveEntityFeature,
    ValveDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, DATA_CLIENT, DATA_HUB_IDENT
from .client import LarnitechClient, DeviceInfo as LarnitechDeviceInfo

SUPPORTED_VALVE_TYPES = {"valve"}


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
):
    client: LarnitechClient = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]

    entities: list[ValveEntity] = []
    for dev in client.devices.values():
        if dev.type in SUPPORTED_VALVE_TYPES:
            entities.append(LarnitechValve(hass, entry.entry_id, client, dev))

    async_add_entities(entities)


class LarnitechValve(ValveEntity):
    """Larnitech valve: opened/closed (no position)."""

    # Если знаешь, что это водяной/газовый — поставь WATER/GAS
    _attr_device_class = ValveDeviceClass.WATER

    # Поддерживаем только open/close (без STOP, без SET_POSITION)
    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE

    # У тебя нет процента открытия -> False
    _attr_reports_position = False

    def __init__(self, hass: HomeAssistant, entry_id: str, client: LarnitechClient, dev: LarnitechDeviceInfo) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._client = client
        self._dev = dev
        self._addr = dev.addr
        self._unsub = None

    @property
    def unique_id(self) -> str:
        return f"larnitech_valve_{self._addr}"

    @property
    def device_info(self) -> DeviceInfo:
        hub_ident = self.hass.data[DOMAIN][self._entry_id][DATA_HUB_IDENT]
        return DeviceInfo(
            identifiers={(DOMAIN, self._addr)},
            name=self._dev.name,
            manufacturer="Larnitech",
            model=self._dev.type,
            suggested_area=self._dev.area or None,
            via_device=hub_ident
        )

    @property
    def name(self) -> str:
        return self._dev.name

    def _status(self) -> dict:
        return self._client.states.get(self._addr, {})

    @property
    def is_closed(self) -> bool | None:
        """
        Для valves без position HA определяет состояние по is_closed / is_opening / is_closing.  [oai_citation:1‡Home Assistant](https://developers.home-assistant.io/docs/core/entity/valve/)
        """
        state = self._status().get("state")
        if isinstance(state, str):
            s = state.lower()
            if s == "closed":
                return True
            if s == "opened":
                return False
        return None

    async def async_open_valve(self) -> None:
        # Larnitech ожидает opened/closed
        await self._client.status_set(self._addr, {"state": "opened"})

    async def async_close_valve(self) -> None:
        await self._client.status_set(self._addr, {"state": "closed"})

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