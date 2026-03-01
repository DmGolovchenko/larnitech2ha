from __future__ import annotations

from homeassistant.components.light import LightEntity, ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util.color import color_hs_to_RGB  # не обязателен, если RGB не нужно

from .const import DOMAIN, DATA_CLIENT, DATA_HUB_IDENT
from .client import LarnitechClient, DeviceInfo as LarnitechDeviceInfo

SUPPORTED_LIGHT_TYPES = {"lamp", "dimer-lamp", "dimmer-lamp", "light", "light-scheme", "rgb-lamp"}

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    client: LarnitechClient = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]

    entities = []
    for dev in client.devices.values():
        if dev.type in SUPPORTED_LIGHT_TYPES:
            entities.append(LarnitechLight(hass, entry.entry_id, client, dev))

    async_add_entities(entities)


class LarnitechLight(LightEntity):
    def __init__(self, hass: HomeAssistant, entry_id: str, client: LarnitechClient, dev: LarnitechDeviceInfo) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._client = client
        self._dev = dev
        self._addr = dev.addr
        self._unsub = None

    @property
    def unique_id(self) -> str:
        return f"larnitech_light_{self._addr}"

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
        return {"addr": self._addr, "type": self._dev.type, "area": self._dev.area}

    def _status(self) -> dict:
        return self._client.states.get(self._addr, {})

    @property
    def supported_color_modes(self):
        return {ColorMode.ONOFF}

    @property
    def color_mode(self):
        return ColorMode.ONOFF

    @property
    def is_on(self) -> bool:
        val = self._status().get("state")
        if isinstance(val, str):
            return val.lower() == "on"
        if isinstance(val, (int, float)):
            return val != 0
        return False

    @property
    def supported_color_modes(self):
        # rgb-lamp поддерживает HS+brightness, обычные лампы — только on/off
        if self._dev.type == "rgb-lamp":
            return {ColorMode.HS}
        # dimer-lamp можно сделать BRIGHTNESS, если хочешь
        if self._dev.type in ("dimer-lamp", "dimmer-lamp"):
            return {ColorMode.BRIGHTNESS}
        return {ColorMode.ONOFF}

    @property
    def color_mode(self):
        # Текущий режим можно отдавать как единственный поддерживаемый
        if self._dev.type == "rgb-lamp":
            return ColorMode.HS
        if self._dev.type in ("dimer-lamp", "dimmer-lamp"):
            return ColorMode.BRIGHTNESS
        return ColorMode.ONOFF

    @property
    def brightness(self) -> int | None:
        st = self._status()
        level = st.get("level")
        if isinstance(level, (int, float)):
            # Larnitech 0..100 -> HA 0..255
            return max(0, min(255, int(round(level * 255 / 100))))
        return None

    @property
    def hs_color(self) -> tuple[float, float] | None:
        if self._dev.type != "rgb-lamp":
            return None
        st = self._status()
        hue = st.get("hue")
        sat = st.get("saturation")
        if isinstance(hue, (int, float)) and isinstance(sat, (int, float)):
            # HA HS: hue 0..360, sat 0..100
            return (float(hue), float(sat))
        return None

    async def async_turn_on(self, **kwargs):
        status = {"state": "on"}

        # brightness
        if "brightness" in kwargs and kwargs["brightness"] is not None:
            b = int(kwargs["brightness"])
            level = round(b * 100 / 255, 2)  # 0..100
            status["level"] = level

        # color
        if self._dev.type == "rgb-lamp":
            hs = kwargs.get("hs_color")
            if hs:
                h, s = hs
                status["hue"] = float(h)
                status["saturation"] = float(s)

        await self._client.status_set(self._addr, status)

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