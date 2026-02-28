from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_HOST, CONF_PORT, CONF_API_KEY, DEFAULT_PORT
from .client import LarnitechClient, LarnitechAuthError, LarnitechConnectionError


class LarnitechConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is None:
            schema = vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                    vol.Required(CONF_API_KEY): str,
                }
            )
            return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

        host = user_input[CONF_HOST]
        port = user_input[CONF_PORT]
        api_key = user_input[CONF_API_KEY]

        await self.async_set_unique_id(f"{host}:{port}")
        self._abort_if_unique_id_configured()

        url = f"ws://{host}:{port}/api"

        # Пробуем подключиться/авторизоваться в рамках flow
        try:
            client = LarnitechClient(self.hass, url=url, api_key=api_key)
            await client.async_test_connection()
        except LarnitechAuthError:
            errors["base"] = "invalid_auth"
        except LarnitechConnectionError:
            errors["base"] = "cannot_connect"
        except Exception:
            errors["base"] = "cannot_connect"

        if errors:
            schema = vol.Schema(
                {
                    vol.Required(CONF_HOST, default=host): str,
                    vol.Optional(CONF_PORT, default=port): int,
                    vol.Required(CONF_API_KEY, default=api_key): str,
                }
            )
            return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

        return self.async_create_entry(title=f"Larnitech {host}", data=user_input)