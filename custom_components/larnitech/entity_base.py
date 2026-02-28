from __future__ import annotations

from homeassistant.helpers.entity import Entity

from .client import LarnitechClient, DeviceInfo


class LarnitechEntity(Entity):
    def __init__(self, client: LarnitechClient, dev: DeviceInfo) -> None:
        self._client = client
        self._dev = dev
        self._addr = dev.addr

        self._unsub = None

    @property
    def unique_id(self) -> str:
        return f"larnitech_{self._addr}"

    @property
    def name(self) -> str:
        return self._dev.name

    @property
    def extra_state_attributes(self):
        return {
            "addr": self._addr,
            "type": self._dev.type,
            "area": self._dev.area,
        }

    async def async_added_to_hass(self):
        def _on_status(addr: str, status: dict):
            if addr == self._addr:
                self.async_write_ha_state()

        self._client.add_status_listener(_on_status)

    def _status(self) -> dict:
        return self._client.states.get(self._addr, {})