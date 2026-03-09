from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, DATA_CLIENT, DATA_HUB_IDENT
from .client import LarnitechClient, DeviceInfo as LarnitechDeviceInfo

SUPPORTED_SWITCH_TYPES = {"switch", "script"}

async def async_setup_entry(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback,
):
    client: LarnitechClient = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]

    entities = []
    for dev in client.devices.values():
        if dev.type in SUPPORTED_SWITCH_TYPES:
            entities.append(LarnitechSwitch(hass, entry.entry_id, client, dev))

    async_add_entities(entities)


class LarnitechSwitch(SwitchEntity):
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

        # Для momentary switch храним разобранное событие отдельно
        self._switch_pressed = False
        self._switch_event_attrs: dict = {}

    @property
    def unique_id(self) -> str:
        return f"larnitech_switch_{self._addr}"

    @property
    def name(self) -> str:
        return f"{self._dev.name} ({self._addr})"
        # return self._dev.name

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

    def _status(self) -> dict:
        return self._client.states.get(self._addr, {})

    def _parse_switch_hex(self, hex_value: str | None) -> dict:
        """
        Разбор hex-статуса для Larnitech switch.

        Наблюдаемая логика:
        - FC00  -> button down
        - FF00  -> short press release
        - FDxx  -> hold in progress
        - FFxx  -> hold release (если xx > 00)
        """
        result = {
            "raw_hex": hex_value,
            "hex_int": None,
            "event": None,
            "phase": None,
            "hold_ticks": 0,
            "hold_seconds_estimate": 0.0,
        }

        if not hex_value or not isinstance(hex_value, str):
            return result

        try:
            value = int(hex_value, 16)
        except ValueError:
            return result

        result["hex_int"] = value

        high = (value >> 8) & 0xFF
        low = value & 0xFF

        result["hold_ticks"] = low
        # По логам похоже примерно на ~0.1 сек на шаг
        result["hold_seconds_estimate"] = round(low * 0.1, 1)

        if high == 0xFC:
            result["event"] = "press"
            result["phase"] = "down"
        elif high == 0xFD:
            result["event"] = "hold"
            result["phase"] = "progress"
        elif high == 0xFF:
            result["phase"] = "release"
            if low == 0:
                result["event"] = "single_press"
            else:
                result["event"] = "hold_release"

        return result

    @property
    def extra_state_attributes(self):
        attrs = {
            "addr": self._addr,
            "type": self._dev.type,
            "area": self._dev.area,
        }

        # Для switch добавляем разобранные события кнопки
        if self._dev.type == "switch":
            attrs.update(self._switch_event_attrs)

            # На всякий случай продублируем "сырое" текущее содержимое status
            status = self._status()
            if "hex" in status:
                attrs["status_hex"] = status.get("hex")

        return attrs

    @property
    def is_on(self) -> bool:
        # Для script оставляем старую логику on/off
        if self._dev.type == "script":
            val = self._status().get("state")
            if isinstance(val, str):
                return val.lower() == "on"
            if isinstance(val, (int, float)):
                return val != 0
            return False

        # Для switch:
        # on  -> кнопка сейчас нажата / удерживается
        # off -> кнопка отпущена
        if self._dev.type == "switch":
            return self._switch_pressed

        return False

    async def async_turn_on(self, **kwargs):
        await self._client.status_set(self._addr, {"state": "on"})

    async def async_turn_off(self, **kwargs):
        await self._client.status_set(self._addr, {"state": "off"})

    async def async_added_to_hass(self):
        # Инициализация текущих атрибутов при старте HA / reload integration
        if self._dev.type == "switch":
            current_hex = self._status().get("hex")
            parsed = self._parse_switch_hex(current_hex)
            self._switch_event_attrs = parsed

            event = parsed.get("event")
            self._switch_pressed = event in {"press", "hold"}

        def _on_status(addr: str, status: dict):
            if addr != self._addr:
                return

            if self._dev.type == "switch":
                parsed = self._parse_switch_hex(status.get("hex"))
                self._switch_event_attrs = parsed

                event = parsed.get("event")
                self._switch_pressed = event in {"press", "hold"}

            self.async_write_ha_state()

        self._unsub = self._client.add_status_listener(_on_status)

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None