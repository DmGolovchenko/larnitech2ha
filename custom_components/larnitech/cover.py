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

from .const import DOMAIN
from .client import LarnitechClient, DeviceInfo as LarnitechDeviceInfo

SUPPORTED_COVER_TYPES = {"blinds"}  # если у тебя будут roller/jalousie — добавишь сюда


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
):
    client: LarnitechClient = hass.data[DOMAIN][entry.entry_id]["client"]

    entities: list[CoverEntity] = []
    for dev in client.devices.values():
        if dev.type in SUPPORTED_COVER_TYPES:
            entities.append(LarnitechCover(client, dev))

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

    def __init__(self, client: LarnitechClient, dev: LarnitechDeviceInfo) -> None:
        self._client = client
        self._dev = dev
        self._addr = dev.addr
        self._unsub = None

    @property
    def unique_id(self) -> str:
        return f"larnitech_cover_{self._addr}"

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

    @property
    def current_cover_position(self) -> int | None:
        """
        0..100 where 0=closed, 100=open.
        Prefer numeric 'position'. Fallback to textual state.
        """
        st = self._status()

        pos = st.get("position")
        if isinstance(pos, (int, float)):
            return max(0, min(100, int(round(pos))))

        # fallback if position missing
        state = st.get("state")
        if isinstance(state, str):
            s = state.lower()
            if s == "opened":
                return 100
            if s == "closed":
                return 0
            # middle without numeric -> unknown
        return None

    @property
    def is_closed(self) -> bool | None:
        """Let HA know if cover is closed."""
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
            return target > pos

        return None

    @property
    def is_closing(self) -> bool | None:
        st = self._status()
        pos = st.get("position")
        target = st.get("target")

        if isinstance(pos, (int, float)) and isinstance(target, (int, float)):
            return target < pos

        return None

    async def async_open_cover(self, **kwargs):
        # Открыть = 100%
        await self.async_set_cover_position(position=100)

    async def async_close_cover(self, **kwargs):
        # Закрыть = 0%
        await self.async_set_cover_position(position=0)

    async def async_stop_cover(self, **kwargs):
        # Тут есть неопределённость: как именно Larnitech принимает "stop".
        # Часто это либо {"state":"stop"} либо {"command":"stop"} либо {"target": current_position}.
        # Начнём с наиболее вероятного варианта:
        await self._client.status_set(self._addr, {"state": "stop"})

    async def async_set_cover_position(self, **kwargs):
        """Set target position in percent."""
        pos = kwargs.get("position")
        if pos is None:
            return

        # Larnitech обычно понимает target в процентах.
        # Если у тебя окажется, что нужно "position" вместо "target" — просто поменяешь поле.
        await self._client.status_set(self._addr, {"target": float(pos)})

    async def async_added_to_hass(self):
        def _on_status(addr: str, status: dict):
            if addr == self._addr:
                self.async_write_ha_state()

        self._unsub = self._client.add_status_listener(_on_status)

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None