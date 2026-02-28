from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .client import LarnitechClient
from .const import DOMAIN, CONF_HOST, CONF_PORT, CONF_API_KEY, PLATFORMS

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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if data:
        client: LarnitechClient = data["client"]
        await client.async_stop()
    return unload_ok