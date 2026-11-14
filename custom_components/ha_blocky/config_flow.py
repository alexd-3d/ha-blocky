"""Config and options flow for the Blocky DNS integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_URL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from yarl import URL

from . import db
from .api import (
    BlockyClient,
    BlockyConnectionError,
    BlockyInvalidUrlError,
    BlockyResponseError,
    normalize_base_url,
)
from .const import (
    CONF_DB_HOST,
    CONF_DB_NAME,
    CONF_DB_PASSWORD,
    CONF_DB_PORT,
    CONF_DB_USERNAME,
    CONF_LIST_NETWORKS,
    DEFAULT_DB_PORT,
    DEFAULT_LIST_NETWORKS,
    DOMAIN,
)
from .validation import InvalidNetworkError, parse_networks

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        )
    }
)

# All fields optional: leaving the host empty disables the query log.
STEP_DATABASE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_DB_HOST): TextSelector(),
        vol.Optional(CONF_DB_PORT, default=DEFAULT_DB_PORT): NumberSelector(
            NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Optional(CONF_DB_NAME): TextSelector(),
        vol.Optional(CONF_DB_USERNAME): TextSelector(),
        vol.Optional(CONF_DB_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)

# Only the clients that may fetch the lists are set here; clients, levels and
# rules are set in the Settings tab of the card.
STEP_LIST_NETWORKS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_LIST_NETWORKS, default=list): TextSelector(
            TextSelectorConfig(multiple=True)
        ),
    }
)

DB_KEYS = (
    CONF_DB_HOST,
    CONF_DB_PORT,
    CONF_DB_NAME,
    CONF_DB_USERNAME,
    CONF_DB_PASSWORD,
)

# Example addresses shown in the form; translations must not embed URLs.
URL_PLACEHOLDERS = {
    "example_url": "http://blocky.example:4000",
    "addon_url": "http://4d2c38a0-blocky:4000",
}

# Which form field a rejected database setting belongs to.
_SETTING_FIELDS = {
    "host": CONF_DB_HOST,
    "port": CONF_DB_PORT,
    "database": CONF_DB_NAME,
    "username": CONF_DB_USERNAME,
    "password": CONF_DB_PASSWORD,
}


def _test_database(settings: db.DbSettings) -> None:
    """Open the database once to validate it. Executor only."""
    database = db.QueryLogDatabase(db.build_url(settings))
    try:
        database.connect()
    finally:
        database.close()


class BlockyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup of a Blocky instance."""

    VERSION = 1
    # 2: clients with protection levels replace the old grouping and free lists.
    MINOR_VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> BlockyOptionsFlow:
        """Return the options flow."""
        return BlockyOptionsFlow()

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


class BlockyOptionsFlow(OptionsFlowWithReload):
    """Configure the connection and the clients that may download lists."""

    def _options_without(self, keys: tuple[str, ...]) -> dict[str, Any]:
        """Return the stored options minus the keys a step is replacing."""
        return {
            key: value
            for key, value in self.config_entry.options.items()
            if key not in keys
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose what to configure."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["database", "list_networks"],
        )

    async def async_step_database(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the database connection and verify it is usable."""
        errors: dict[str, str] = {}
        other_options = self._options_without(DB_KEYS)

        if user_input is not None:
            host = user_input.get(CONF_DB_HOST)
            if not isinstance(host, str) or not host.strip():
                # No host: the query log is switched off.
                return self.async_create_entry(data=other_options)

            port = user_input.get(CONF_DB_PORT, DEFAULT_DB_PORT)
            if isinstance(port, float) and port.is_integer():
                port = int(port)
            try:
                settings = db.validate_settings(
                    host,
                    port,
                    user_input.get(CONF_DB_NAME),
                    user_input.get(CONF_DB_USERNAME),
                    user_input.get(CONF_DB_PASSWORD),
                )
            except db.BlockyDbSettingsError as err:
                errors[_SETTING_FIELDS.get(str(err), "base")] = "invalid_db_setting"
            else:
                try:
                    await self.hass.async_add_executor_job(_test_database, settings)
                except db.BlockyDbDriverError:
                    errors["base"] = "db_driver_missing"
                except db.BlockyDbSchemaError:
                    errors["base"] = "db_schema"
                except db.BlockyDbNotReadOnlyError:
                    errors["base"] = "db_not_read_only"
                except db.BlockyDbError:
                    errors["base"] = "db_cannot_connect"
                else:
                    return self.async_create_entry(
                        data={
                            **other_options,
                            CONF_DB_HOST: settings.host,
                            CONF_DB_PORT: settings.port,
                            CONF_DB_NAME: settings.database,
                            CONF_DB_USERNAME: settings.username,
                            CONF_DB_PASSWORD: settings.password,
                        }
                    )

        # Never send the stored password back to the browser.
        suggested = {
            key: value
            for key, value in (user_input or self.config_entry.options).items()
            if key in DB_KEYS and key != CONF_DB_PASSWORD
        }
        return self.async_show_form(
            step_id="database",
            data_schema=self.add_suggested_values_to_schema(
                STEP_DATABASE_SCHEMA, suggested
            ),
            errors=errors,
        )

    async def async_step_list_networks(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Say which clients may download the lists."""
        errors: dict[str, str] = {}

        if user_input is not None:
            networks = [
                str(net).strip() for net in user_input.get(CONF_LIST_NETWORKS, [])
            ]
            try:
                parse_networks(networks)
            except InvalidNetworkError:
                errors[CONF_LIST_NETWORKS] = "invalid_network"
            else:
                return self.async_create_entry(
                    data={
                        **self._options_without((CONF_LIST_NETWORKS,)),
                        CONF_LIST_NETWORKS: networks,
                    }
                )
            suggested: dict[str, Any] = user_input
        else:
            stored_networks = self.config_entry.options.get(
                CONF_LIST_NETWORKS, list(DEFAULT_LIST_NETWORKS)
            )
            suggested = {
                CONF_LIST_NETWORKS: (
                    list(stored_networks) if isinstance(stored_networks, list) else []
                ),
            }

        return self.async_show_form(
            step_id="list_networks",
            data_schema=self.add_suggested_values_to_schema(
                STEP_LIST_NETWORKS_SCHEMA, suggested
            ),
            errors=errors,
        )
