"""Config flow for the Blocky DNS integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from yarl import URL

from .api import (
    BlockyClient,
    BlockyConnectionError,
    BlockyInvalidUrlError,
    BlockyResponseError,
    normalize_base_url,
)
from .const import DOMAIN

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        )
    }
)


# Example addresses shown in the form; translations must not embed URLs.
URL_PLACEHOLDERS = {
    "example_url": "http://blocky.example:4000",
    "addon_url": "http://4d2c38a0-blocky:4000",
}


class BlockyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup of a Blocky instance."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the Blocky API URL and verify it."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                url = normalize_base_url(user_input.get(CONF_URL))
            except BlockyInvalidUrlError:
                errors[CONF_URL] = "invalid_url"
            else:
                self._async_abort_entries_match({CONF_URL: url})
                client = BlockyClient(async_get_clientsession(self.hass), url)
                try:
                    await client.async_get_status()
                except BlockyConnectionError:
                    errors["base"] = "cannot_connect"
                except BlockyResponseError:
                    errors["base"] = "invalid_response"
                else:
                    return self.async_create_entry(
                        title=f"Blocky ({URL(url).host})", data={CONF_URL: url}
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input
            ),
            errors=errors,
            description_placeholders=URL_PLACEHOLDERS,
        )
