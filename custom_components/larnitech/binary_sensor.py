from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, DATA_CLIENT, DATA_HUB_IDENT
from .client import LarnitechClient, DeviceInfo as LarnitechDeviceInfo

SUPPORTED_TYPES = {"leak-sensor", "motion-sensor"}

async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
):
    client: LarnitechClient = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]

    entities: list[BinarySensorEntity] = []
    for dev in client.devices.values():
        if dev.type in SUPPORTED_TYPES:
            entities.append(LarnitechBinarySensor(hass, entry.entry_id, client, dev))

    async_add_entities(entities)


class LarnitechBinarySensor(BinarySensorEntity):
    def __init__(self, hass: HomeAssistant, entry_id: str, client: LarnitechClient, dev: LarnitechDeviceInfo) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._client = client
        self._dev = dev
        self._addr = dev.addr
        self._unsub = None

    @property
    def unique_id(self) -> str:
        return f"larnitech_binary_{self._dev.type}_{self._addr}"

    @property
    def device_info(self) -> DeviceInfo:
        hub_ident = self.hass.data[DOMAIN][self._entry_id][DATA_HUB_IDENT]
        return DeviceInfo(
            identifiers={(DOMAIN, self._addr)},
            name=self._dev.name,
            manufacturer="Larnitech",
            model=self._dev.type,
            suggested_area=self._dev.area or None,
            via_device=hub_ident,
        )

    @property
    def name(self) -> str:
        if self._dev.type == "motion-sensor":
            return f"{self._dev.name} Motion"
        return self._dev.name

    @property
    def device_class(self):
        if self._dev.type == "leak-sensor":
            return BinarySensorDeviceClass.MOISTURE
        if self._dev.type == "motion-sensor":
            return BinarySensorDeviceClass.MOTION
        return None

    def _status(self) -> dict:
        return self._client.states.get(self._addr, {})

    @property
    def is_on(self) -> bool:
        state = self._status().get("state")

        if self._dev.type == "leak-sensor":
            # leakage => True, ok => False
            if isinstance(state, str):
                s = state.lower()
                if s == "leakage":
                    return True
                if s == "ok":
                    return False
                if s in ("leak", "alarm", "wet", "on", "true", "1"):
                    return True
                if s in ("dry", "off", "false", "0"):
                    return False

            if isinstance(state, bool):
                return state
            if isinstance(state, (int, float)):
                return state != 0

            return False

        if self._dev.type == "motion-sensor":
            # Любое значение > 0 считаем движением
            if isinstance(state, bool):
                return state

            if isinstance(state, (int, float)):
                return float(state) > 0

            if isinstance(state, str):
                s = state.strip().lower()

                if s in ("on", "true", "motion", "detected", "1"):
                    return True
                if s in ("off", "false", "clear", "idle", "0"):
                    return False

                try:
                    return float(s) > 0
                except ValueError:
                    return False

            return False

        return False

    @property
    def extra_state_attributes(self):
        st = self._status()
        attrs = {
            "addr": self._addr,
            "type": self._dev.type,
            "area": self._dev.area,
            "raw_state": st.get("state"),
        }

        if self._dev.type == "motion-sensor":
            try:
                attrs["motion_level"] = float(st.get("state"))
            except (TypeError, ValueError):
                attrs["motion_level"] = None

        return attrs

    async def async_added_to_hass(self):
        def _on_status(addr: str, status: dict):
            if addr == self._addr:
                self.async_write_ha_state()

        self._unsub = self._client.add_status_listener(_on_status)

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None