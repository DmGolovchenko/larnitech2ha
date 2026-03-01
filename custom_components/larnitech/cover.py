from __future__ import annotations

from homeassistant.components.cover import (
    CoverEntity,
    CoverDeviceClass,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, DATA_CLIENT, DATA_HUB_IDENT
from .client import LarnitechClient, DeviceInfo as LarnitechDeviceInfo

SUPPORTED_COVER_TYPES = {"blinds"}  # если у тебя будут roller/jalousie — добавишь сюда


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
):
    client: LarnitechClient = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]

    entities: list[CoverEntity] = []
    for dev in client.devices.values():
        if dev.type in SUPPORTED_COVER_TYPES:
            entities.append(LarnitechCover(hass, entry.entry_id, client, dev))

    async_add_entities(entities)


class LarnitechCover(CoverEntity):
    """Cover entity for Larnitech blinds with % position."""

    _attr_device_class = CoverDeviceClass.BLIND
    _attr_supported_features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, hass: HomeAssistant, entry_id: str, client: LarnitechClient, dev: LarnitechDeviceInfo) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._client = client
        self._dev = dev
        self._addr = dev.addr
        self._unsub = None

    @property
    def unique_id(self) -> str:
        return f"larnitech_cover_{self._addr}"

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

    @property
    def extra_state_attributes(self):
        st = self._status()
        return {
            "addr": self._addr,
            "type": self._dev.type,
            "area": self._dev.area,
            "raw_state": st.get("state"),
            "target": st.get("target"),
            "position": st.get("position"),
        }

    def _status(self) -> dict:
        return self._client.states.get(self._addr, {})

    def _lt_to_ha_pos(self, lt_pos: float) -> int:
        """Larnitech: 0=open, 100=closed  ->  HA: 0=closed, 100=open"""
        return max(0, min(100, int(round(100 - lt_pos))))

    def _ha_to_lt_pos(self, ha_pos: float) -> float:
        """HA: 0=closed, 100=open  ->  Larnitech: 0=open, 100=closed"""
        return float(max(0, min(100, 100 - ha_pos)))

    @property
    def current_cover_position(self) -> int | None:
        lt_pos = self._status().get("position")
        if isinstance(lt_pos, (int, float)):
            return self._lt_to_ha_pos(lt_pos)

        state = self._status().get("state")
        if isinstance(state, str):
            s = state.lower()
            if s == "opened":
                return 100  # в HA это open
            if s == "closed":
                return 0    # в HA это closed
        return None

    @property
    def is_closed(self) -> bool | None:
        pos = self.current_cover_position
        if pos is not None:
            return pos == 0
        state = self._status().get("state")
        if isinstance(state, str):
            return state.lower() == "closed"
        return None

    @property
    def is_opening(self) -> bool | None:
        st = self._status()
        pos = st.get("position")
        target = st.get("target")

        if isinstance(pos, (int, float)) and isinstance(target, (int, float)):
            return target < pos

        return None

    @property
    def is_closing(self) -> bool | None:
        st = self._status()
        pos = st.get("position")
        target = st.get("target")

        if isinstance(pos, (int, float)) and isinstance(target, (int, float)):
            return target > pos

        return None

    async def async_open_cover(self, **kwargs):
        # Открыть = 100%
        await self.async_set_cover_position(position=100) # HA open

    async def async_close_cover(self, **kwargs):
        # Закрыть = 0%
        await self.async_set_cover_position(position=0) # HA close

    async def async_stop_cover(self, **kwargs):
        # Тут есть неопределённость: как именно Larnitech принимает "stop".
        # Часто это либо {"state":"stop"} либо {"command":"stop"} либо {"target": current_position}.
        # Начнём с наиболее вероятного варианта:
        await self._client.status_set(self._addr, {"state": "stop"})

    async def async_set_cover_position(self, **kwargs):
        ha_pos = kwargs.get("position")
        if ha_pos is None:
            return

        lt_target = self._ha_to_lt_pos(ha_pos)
        await self._client.status_set(self._addr, {"target": lt_target})

    async def async_added_to_hass(self):
        def _on_status(addr: str, status: dict):
            if addr == self._addr:
                self.async_write_ha_state()

        self._unsub = self._client.add_status_listener(_on_status)

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None