from __future__ import annotations

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import HVACMode, ClimateEntityFeature
from homeassistant.const import UnitOfTemperature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .client import LarnitechClient, DeviceInfo as LarnitechDeviceInfo

SUPPORTED_CLIMATE_TYPES = {"valve-heating", "conditioner"}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    client: LarnitechClient = hass.data[DOMAIN][entry.entry_id]["client"]

    entities: list[ClimateEntity] = []
    for dev in client.devices.values():
        if dev.type == "valve-heating":
            entities.append(LarnitechHeatingValve(client, dev))
        elif dev.type == "conditioner":
            entities.append(LarnitechConditioner(client, dev))

    async_add_entities(entities)


class LarnitechHeatingValve(ClimateEntity):
    """Larnitech valve-heating as HA climate entity."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]

    def __init__(self, client: LarnitechClient, dev: LarnitechDeviceInfo) -> None:
        self._client = client
        self._dev = dev
        self._addr = dev.addr
        self._unsub = None

        # Можно расширять по мере появления новых automation значений
        self._known_presets: set[str] = set()

    @property
    def unique_id(self) -> str:
        return f"larnitech_climate_{self._addr}"

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

    # --- On/Off радиатора (hvac) ---

    @property
    def hvac_mode(self) -> HVACMode:
        state = self._status().get("state")
        if isinstance(state, str) and state.lower() == "on":
            return HVACMode.HEAT
        return HVACMode.OFF

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.HEAT:
            await self._client.status_set(self._addr, {"state": "on"})
        elif hvac_mode == HVACMode.OFF:
            await self._client.status_set(self._addr, {"state": "off"})

    # --- Automation как preset_mode ---

    @property
    def preset_mode(self) -> str | None:
        val = self._status().get("automation")
        if isinstance(val, str):
            return val
        return None

    @property
    def preset_modes(self) -> list[str]:
        # HA любит иметь список возможных preset’ов
        st = self._status()
        cur = st.get("automation")
        if isinstance(cur, str):
            self._known_presets.add(cur)
        # если пока не видели ничего — вернём пусто, UI всё равно покажет текущее
        return sorted(self._known_presets)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        # Позволяем выставлять любой preset (Larnitech может поддерживать разные строки)
        await self._client.status_set(self._addr, {"automation": preset_mode})

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
            a = status.get("automation")
            if isinstance(a, str):
                self._known_presets.add(a)

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

    def __init__(self, client: LarnitechClient, dev: LarnitechDeviceInfo) -> None:
        self._client = client
        self._dev = dev
        self._addr = dev.addr
        self._unsub = None

    @property
    def unique_id(self) -> str:
        return f"larnitech_conditioner_{self._addr}"

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