from __future__ import annotations

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import HVACMode, HVACAction, ClimateEntityFeature
from homeassistant.const import UnitOfTemperature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, DATA_CLIENT, DATA_HUB_IDENT
from .client import LarnitechClient, DeviceInfo as LarnitechDeviceInfo

SUPPORTED_CLIMATE_TYPES = {"valve-heating", "conditioner"}

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    client: LarnitechClient = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]

    entities: list[ClimateEntity] = []
    for dev in client.devices.values():
        if dev.type == "valve-heating":
            entities.append(LarnitechHeatingValve(hass, entry.entry_id, client, dev))
        elif dev.type == "conditioner":
            entities.append(LarnitechConditioner(hass, entry.entry_id, client, dev))

    async_add_entities(entities)


class LarnitechHeatingValve(ClimateEntity):
    """Larnitech valve-heating as HA climate entity."""
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]

    # Optional, but recommended for nice UI control
    _attr_min_temp = 5.0
    _attr_max_temp = 40.0
    _attr_target_temperature_step = 0.1

    # _attr_preset_modes = PRESET_MODES

    def __init__(self, hass: HomeAssistant, entry_id: str, client: LarnitechClient, dev: LarnitechDeviceInfo) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._client = client
        self._dev = dev
        self._addr = dev.addr
        self._unsub = None

        # Можно расширять по мере появления новых automation значений
        automations = getattr(dev, "automations", None)
        self._known_presets: set[str] = {
            name for name in (automations or [])
            if isinstance(name, str) and name.lower() != "null" and not self._is_off_automation(name)
        }
        self._last_preset: str | None = None
        self._remember_preset(self._status().get("automation"))

    @staticmethod
    def _is_off_automation(value: object) -> bool:
        return isinstance(value, str) and value.lower().replace(" ", "-") == "always-off"

    def _remember_preset(self, value: object) -> None:
        if isinstance(value, str) and value and value.lower() != "null" and not self._is_off_automation(value):
            self._last_preset = value
            self._known_presets.add(value)

    @property
    def unique_id(self) -> str:
        return f"larnitech_climate_{self._addr}"

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

    # --- Температуры ---

    @property
    def current_temperature(self) -> float | None:
        val = self._status().get("current")
        return float(val) if isinstance(val, (int, float)) else None

    @property
    def target_temperature(self) -> float | None:
        val = self._status().get("target")
        return float(val) if isinstance(val, (int, float)) else None

    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get("temperature")
        if temp is None:
            return
        await self._client.status_set(self._addr, {"target": float(temp)})

    # --- Режим термостата и фактическая работа клапана ---

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.OFF if self._is_off_automation(self._status().get("automation")) else HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction:
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        state = self._status().get("state")
        return HVACAction.HEATING if isinstance(state, str) and state.lower() == "on" else HVACAction.IDLE

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._client.status_set(self._addr, {"automation": "always-off"})
        elif hvac_mode == HVACMode.HEAT:
            preset = self._last_preset
            if preset is None:
                preset = next(iter(sorted(self._known_presets)), "Comfort")
            await self._client.status_set(self._addr, {"automation": preset})

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    # --- Automation как preset_mode ---

    @property
    def preset_mode(self) -> str | None:
        val = self._status().get("automation")
        if isinstance(val, str) and not self._is_off_automation(val):
            return val
        return None

    @property
    def preset_modes(self) -> list[str]:
        # HA любит иметь список возможных preset’ов
        st = self._status()
        cur = st.get("automation")
        if isinstance(cur, str) and cur and cur.lower() != "null" and not self._is_off_automation(cur):
            self._known_presets.add(cur)
        # если пока не видели ничего — вернём пусто, UI всё равно покажет текущее
        return sorted(self._known_presets)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        # Позволяем выставлять любой preset (Larnitech может поддерживать разные строки)
        await self._client.status_set(self._addr, {"automation": preset_mode})
        self._remember_preset(preset_mode)

    # --- Атрибуты для отладки/прозрачности ---

    @property
    def extra_state_attributes(self):
        st = self._status()
        return {
            "addr": self._addr,
            "type": self._dev.type,
            "area": self._dev.area,
            "raw_state": st.get("state"),
            "automation": st.get("automation"),
            "target": st.get("target"),
            "current": st.get("current"),
        }

    # --- Push updates ---

    async def async_added_to_hass(self):
        def _on_status(addr: str, status: dict):
            if addr != self._addr:
                return

            # обновим набор пресетов на лету
            self._remember_preset(status.get("automation"))

            self.async_write_ha_state()

        self._unsub = self._client.add_status_listener(_on_status)

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None


class LarnitechConditioner(ClimateEntity):
    """Larnitech conditioner (split system)"""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    # Мы умеем: установить температуру, режим HVAC, fan, swing
    _attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.SWING_MODE
    )

    # Маппинг Larnitech mode -> HA HVACMode
    _MODE_TO_HVAC = {
        "cool": HVACMode.COOL,
        "heat": HVACMode.HEAT,
        "dry": HVACMode.DRY,
        "auto": HVACMode.AUTO,
        "fan": HVACMode.FAN_ONLY,
    }
    _HVAC_TO_MODE = {v: k for k, v in _MODE_TO_HVAC.items()}

    # Fan modes (HA строками)
    _FAN_MODES = ["auto", "low", "middle", "high"]

    # vane-ver 0..7 (оставим как строки)
    _SWING_MODES = [str(i) for i in range(0, 8)]

    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.HEAT,
        HVACMode.DRY,
        HVACMode.AUTO,
        HVACMode.FAN_ONLY,
    ]

    # Если хочешь ограничить диапазон (обычно 16..30), можно поставить
    _attr_min_temp = 16
    _attr_max_temp = 30
    _attr_target_temperature_step = 1

    def __init__(self, hass: HomeAssistant, entry_id: str, client: LarnitechClient, dev: LarnitechDeviceInfo) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._client = client
        self._dev = dev
        self._addr = dev.addr
        self._unsub = None

    @property
    def unique_id(self) -> str:
        return f"larnitech_conditioner_{self._addr}"

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

    # --- temperatures ---

    @property
    def target_temperature(self) -> float | None:
        val = self._status().get("target")
        return float(val) if isinstance(val, (int, float)) else None

    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get("temperature")
        if temp is None:
            return
        await self._client.status_set(self._addr, {"target": float(temp)})

    # current_temperature у тебя нет в статусе conditioner -> None
    @property
    def current_temperature(self) -> float | None:
        return None

    # --- HVAC mode (on/off + mode) ---

    @property
    def hvac_mode(self) -> HVACMode:
        st = self._status()

        state = st.get("state")
        if isinstance(state, str) and state.lower() == "off":
            return HVACMode.OFF

        mode = st.get("mode")
        if isinstance(mode, str):
            return self._MODE_TO_HVAC.get(mode.lower(), HVACMode.AUTO)

        # если state=on, но mode нет — пусть будет AUTO
        return HVACMode.AUTO

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._client.status_set(self._addr, {"state": "off"})
            return

        # Для включения обязательно ставим state=on + mode
        lt_mode = self._HVAC_TO_MODE.get(hvac_mode)
        if lt_mode is None:
            lt_mode = "auto"

        await self._client.status_set(self._addr, {"state": "on", "mode": lt_mode})

    # --- Fan ---

    @property
    def fan_mode(self) -> str | None:
        val = self._status().get("fan")
        if isinstance(val, str):
            return val.lower()
        return None

    @property
    def fan_modes(self) -> list[str]:
        return self._FAN_MODES

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        # принимаем только известные, чтобы не слать мусор
        fm = fan_mode.lower()
        if fm not in self._FAN_MODES:
            return
        await self._client.status_set(self._addr, {"fan": fm})

    # --- Swing (vane-ver) ---

    @property
    def swing_mode(self) -> str | None:
        val = self._status().get("vane-ver")
        if isinstance(val, (int, float)):
            v = int(val)
            if 0 <= v <= 7:
                return str(v)
        if isinstance(val, str) and val.isdigit():
            return val
        return None

    @property
    def swing_modes(self) -> list[str]:
        return self._SWING_MODES

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        if swing_mode not in self._SWING_MODES:
            return
        await self._client.status_set(self._addr, {"vane-ver": int(swing_mode)})

    # --- extra attrs ---

    @property
    def extra_state_attributes(self):
        st = self._status()
        return {
            "addr": self._addr,
            "type": self._dev.type,
            "area": self._dev.area,
            "raw_state": st.get("state"),
            "mode": st.get("mode"),
            "fan": st.get("fan"),
            "vane-ver": st.get("vane-ver"),
            "target": st.get("target"),
        }

    # --- push updates ---

    async def async_added_to_hass(self):
        def _on_status(addr: str, status: dict):
            if addr == self._addr:
                self.async_write_ha_state()

        self._unsub = self._client.add_status_listener(_on_status)

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None
