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
from homeassistant.const import CONF_URL, UnitOfTime
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url
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
    CONF_ALLOW_LISTS,
    CONF_DB_HOST,
    CONF_DB_NAME,
    CONF_DB_PASSWORD,
    CONF_DB_PORT,
    CONF_DB_USERNAME,
    CONF_DENY_LISTS,
    CONF_EXACT_ONLY_LISTS,
    CONF_LIST_NETWORKS,
    CONF_LISTS,
    DEFAULT_DB_PORT,
    DEFAULT_LIST_NETWORKS,
    DOMAIN,
    INTERVALS,
    LIST_TYPE_ALLOW,
    LIST_TYPE_DENY,
    MAX_LISTS,
)
from .intervals import interval_seconds
from .lists import read_definitions
from .validation import (
    InvalidListNameError,
    InvalidNetworkError,
    parse_networks,
    validate_list_name,
)

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

STEP_INTERVALS_SCHEMA = vol.Schema(
    {
        vol.Required(key): NumberSelector(
            NumberSelectorConfig(
                min=spec.minimum,
                max=spec.maximum,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement=UnitOfTime.SECONDS,
            )
        )
        for key, spec in INTERVALS.items()
    }
)

STEP_LISTS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_ALLOW_LISTS, default=list): TextSelector(
            TextSelectorConfig(multiple=True)
        ),
        vol.Optional(CONF_DENY_LISTS, default=list): TextSelector(
            TextSelectorConfig(multiple=True)
        ),
        vol.Optional(CONF_EXACT_ONLY_LISTS, default=list): TextSelector(
            TextSelectorConfig(multiple=True)
        ),
        vol.Optional(CONF_LIST_NETWORKS, default=list): TextSelector(
            TextSelectorConfig(multiple=True)
        ),
    }
)

LIST_KEYS = (CONF_LISTS, CONF_LIST_NETWORKS)

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
    """Configure the query log database and the update intervals."""

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
            step_id="init", menu_options=["database", "intervals", "lists", "list_urls"]
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

    async def async_step_intervals(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask how often Blocky and the query log are polled."""
        if user_input is not None:
            # The form schema bounds every value; re-read them through the
            # same validation the coordinators use rather than trusting it.
            intervals = {key: interval_seconds(user_input, key) for key in INTERVALS}
            return self.async_create_entry(
                data={**self._options_without(tuple(INTERVALS)), **intervals}
            )

        current = {
            key: interval_seconds(self.config_entry.options, key) for key in INTERVALS
        }
        return self.async_show_form(
            step_id="intervals",
            data_schema=self.add_suggested_values_to_schema(
                STEP_INTERVALS_SCHEMA, current
            ),
        )

    async def async_step_lists(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Define the manual lists and who may fetch them."""
        errors: dict[str, str] = {}

        if user_input is not None:
            allow = [str(name).strip() for name in user_input.get(CONF_ALLOW_LISTS, [])]
            deny = [str(name).strip() for name in user_input.get(CONF_DENY_LISTS, [])]
            exact = [
                str(name).strip() for name in user_input.get(CONF_EXACT_ONLY_LISTS, [])
            ]
            networks = [
                str(net).strip() for net in user_input.get(CONF_LIST_NETWORKS, [])
            ]

            for field, names in ((CONF_ALLOW_LISTS, allow), (CONF_DENY_LISTS, deny)):
                try:
                    for name in names:
                        validate_list_name(name)
                except InvalidListNameError:
                    errors[field] = "invalid_list_name"
            if not errors:
                if (
                    len(set(allow)) != len(allow)
                    or len(set(deny)) != len(deny)
                    or set(allow) & set(deny)
                ):
                    errors["base"] = "duplicate_list_name"
                elif len(allow) + len(deny) > MAX_LISTS:
                    errors["base"] = "too_many_lists"
                elif set(exact) - set(allow) - set(deny):
                    errors[CONF_EXACT_ONLY_LISTS] = "unknown_list_name"
            try:
                parse_networks(networks)
            except InvalidNetworkError:
                errors[CONF_LIST_NETWORKS] = "invalid_network"

            if not errors:
                definitions = {
                    name: {"type": list_type, "exact_only": name in exact}
                    for list_type, names in (
                        (LIST_TYPE_ALLOW, allow),
                        (LIST_TYPE_DENY, deny),
                    )
                    for name in names
                }
                return self.async_create_entry(
                    data={
                        **self._options_without(LIST_KEYS),
                        CONF_LISTS: definitions,
                        CONF_LIST_NETWORKS: networks,
                    }
                )
            suggested = user_input
        else:
            definitions = read_definitions(self.config_entry.options)
            stored_networks = self.config_entry.options.get(
                CONF_LIST_NETWORKS, list(DEFAULT_LIST_NETWORKS)
            )
            suggested = {
                CONF_ALLOW_LISTS: [
                    name
                    for name, definition in definitions.items()
                    if definition.list_type == LIST_TYPE_ALLOW
                ],
                CONF_DENY_LISTS: [
                    name
                    for name, definition in definitions.items()
                    if definition.list_type == LIST_TYPE_DENY
                ],
                CONF_EXACT_ONLY_LISTS: [
                    name
                    for name, definition in definitions.items()
                    if definition.exact_only
                ],
                CONF_LIST_NETWORKS: (
                    list(stored_networks) if isinstance(stored_networks, list) else []
                ),
            }

        return self.async_show_form(
            step_id="lists",
            data_schema=self.add_suggested_values_to_schema(
                STEP_LISTS_SCHEMA, suggested
            ),
            errors=errors,
        )

    async def async_step_list_urls(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the addresses Blocky must fetch the lists from."""
        if user_input is not None:
            # Nothing to save; keep the options exactly as they are.
            return self.async_abort(reason="list_urls_closed")

        runtime = getattr(self.config_entry, "runtime_data", None)
        if runtime is None:
            return self.async_abort(reason="not_loaded")
        try:
            base = get_url(
                self.hass, allow_external=False, allow_cloud=False, allow_ip=True
            )
        except NoURLAvailableError:
            base = ""

        lines = [
            f"- {name} ({definition.list_type}): `{base}{runtime.lists.path(name)}`"
            for name, definition in runtime.lists.definitions.items()
        ]
        return self.async_show_form(
            step_id="list_urls",
            data_schema=vol.Schema({}),
            description_placeholders={"urls": "\n".join(lines) or "-"},
        )
