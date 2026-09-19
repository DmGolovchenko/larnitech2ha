from __future__ import annotations

from homeassistant.components.light import LightEntity, ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, DATA_CLIENT, DATA_HUB_IDENT
from .client import LarnitechClient, DeviceInfo as LarnitechDeviceInfo

SUPPORTED_LIGHT_TYPES = {"lamp", "dimer-lamp", "dimmer-lamp", "light", "light-scheme", "rgb-lamp"}
LARNITECH_PERCENT_MAX = 100


def _scale(value: float, source_max: float, target_max: float) -> float:
    """Scale and clamp a value between two ranges starting at zero."""
    return max(0.0, min(target_max, float(value) * target_max / source_max))


def _brightness_from_larnitech(value: float) -> int:
    return round(_scale(value, LARNITECH_PERCENT_MAX, 255))


def _brightness_to_larnitech(value: float) -> float:
    return round(_scale(value, 255, LARNITECH_PERCENT_MAX), 2)


def _hs_from_larnitech(hue: float, saturation: float) -> tuple[float, float]:
    return (
        _scale(hue, LARNITECH_PERCENT_MAX, 360),
        _scale(saturation, LARNITECH_PERCENT_MAX, 100),
    )


def _hs_to_larnitech(hue: float, saturation: float) -> tuple[float, float]:
    # API2 exposes V/S/H as percentages, although the device protocol uses
    # byte values internally. In HA, 360 degrees is the same hue as 0 degrees.
    normalized_hue = float(hue) % 360
    return (
        round(_scale(normalized_hue, 360, LARNITECH_PERCENT_MAX), 2),
        round(_scale(saturation, 100, LARNITECH_PERCENT_MAX), 2),
    )


def _is_light_device(dev: LarnitechDeviceInfo) -> bool:
    """Light поддерживаем только если subType отсутствует."""
    return dev.type in SUPPORTED_LIGHT_TYPES and not dev.subType


async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
):
    client: LarnitechClient = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]

    entities = []
    for dev in client.devices.values():
        if _is_light_device(dev):
            entities.append(LarnitechLight(hass, entry.entry_id, client, dev))

    async_add_entities(entities)


class LarnitechLight(LightEntity):
    def __init__(
            self,
            hass: HomeAssistant,
            entry_id: str,
            client: LarnitechClient,
            dev: LarnitechDeviceInfo,
    ) -> None:
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
            via_device=hub_ident,
        )

    @property
    def name(self) -> str:
        return self._dev.name

    @property
    def extra_state_attributes(self):
        attributes = {
            "addr": self._addr,
            "type": self._dev.type,
            "subType": self._dev.subType,
            "area": self._dev.area,
        }
        if self._dev.type == "rgb-lamp":
            status = self._status()
            attributes.update({
                "larnitech_level": status.get("level"),
                "larnitech_hue": status.get("hue"),
                "larnitech_saturation": status.get("saturation"),
            })
        return attributes

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

    @property
    def supported_color_modes(self):
        if self._dev.type == "rgb-lamp":
            return {ColorMode.HS}
        if self._dev.type in ("dimer-lamp", "dimmer-lamp"):
            return {ColorMode.BRIGHTNESS}
        return {ColorMode.ONOFF}

    @property
    def color_mode(self):
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
            return _brightness_from_larnitech(level)
        return None

    @property
    def hs_color(self) -> tuple[float, float] | None:
        if self._dev.type != "rgb-lamp":
            return None
        st = self._status()
        hue = st.get("hue")
        sat = st.get("saturation")
        if isinstance(hue, (int, float)) and isinstance(sat, (int, float)):
            return _hs_from_larnitech(hue, sat)
        return None

    async def async_turn_on(self, **kwargs):
        status = {"state": "on"}

        if "brightness" in kwargs and kwargs["brightness"] is not None:
            status["level"] = _brightness_to_larnitech(kwargs["brightness"])

        if self._dev.type == "rgb-lamp":
            hs = kwargs.get("hs_color")
            if hs:
                h, s = hs
                hue, saturation = _hs_to_larnitech(h, s)
                status["hue"] = hue
                status["saturation"] = saturation

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
