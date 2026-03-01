from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .client import LarnitechClient
from .const import DOMAIN, CONF_HOST, CONF_PORT, CONF_API_KEY, PLATFORMS, DATA_CLIENT, DATA_HUB_IDENT

import homeassistant.helpers.device_registry as dr

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    api_key = entry.data[CONF_API_KEY]
    url = f"ws://{host}:{port}/api"

    client = LarnitechClient(hass, url=url, api_key=api_key)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"client": client}

    # Важно: дождаться первого инвентаря, чтобы platform setup увидел devices
    await client.async_start()
    await client.async_wait_ready(timeout=60)

    device_registry = dr.async_get(hass)

    # Уникальный идентификатор хаба (лучше привязать к entry_id или host)
    hub_ident = (DOMAIN, f"hub_{entry.entry_id}")
    hub_name = entry.title or f"Larnitech Hub ({host})"

    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={hub_ident},
        name=hub_name,
        manufacturer="Larnitech",
        model="API2",
        # опционально:
        # sw_version=entry.version,  # если хочешь
    )

    # 3) сохраняем ссылки в hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CLIENT: client,
        DATA_HUB_IDENT: hub_ident,
    }

    # 4) грузим платформы
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if data and DATA_CLIENT in data:
            await data[DATA_CLIENT].async_stop()
    return unload_ok