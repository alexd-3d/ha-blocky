"""Config and options flow for the Blocky DNS integration."""

from __future__ import annotations

from typing import Any, Final

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
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
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
    CONF_REPORT_EXISTING_DOMAINS,
    CONF_SHOW_IN_SIDEBAR,
    CONF_ZONES,
    DEFAULT_DB_PORT,
    DEFAULT_LIST_NETWORKS,
    DOMAIN,
    INTERVALS,
    LIST_TYPE_ALLOW,
    LIST_TYPE_DENY,
    MAX_LISTS,
    MAX_ZONES,
    ZONE_MODES,
)
from .intervals import interval_seconds
from .lists import read_definitions
from .validation import (
    InvalidListNameError,
    InvalidNetworkError,
    parse_networks,
    validate_list_name,
)
from .zones import (
    ZoneDefinition,
    ZoneError,
    build_zone,
    read_zones,
    render_blocky_config,
    zone_to_options,
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

STEP_NEW_DOMAINS_SCHEMA = vol.Schema(
    {vol.Required(CONF_REPORT_EXISTING_DOMAINS, default=False): BooleanSelector()}
)

STEP_SIDEBAR_SCHEMA = vol.Schema(
    {vol.Required(CONF_SHOW_IN_SIDEBAR, default=True): BooleanSelector()}
)

# Fields of the zone forms.
CONF_ZONE: Final = "zone"
CONF_ZONE_NAME: Final = "name"
CONF_ZONE_NETWORKS: Final = "networks"
CONF_ZONE_MODE: Final = "mode"
CONF_ZONE_LISTS: Final = "lists"
CONF_ZONE_DELETE: Final = "delete"
# The "add a new zone" choice. A hyphen can never be part of a zone name.
ZONE_CHOICE_NEW: Final = "add-new"

# Which form field a refused zone belongs to.
_ZONE_ERROR_FIELDS: Final = {
    "invalid_zone_name": CONF_ZONE_NAME,
    "invalid_network": CONF_ZONE_NETWORKS,
    "zone_overlap": CONF_ZONE_NETWORKS,
    "invalid_zone_mode": CONF_ZONE_MODE,
    "unknown_list_name": CONF_ZONE_LISTS,
    "allowlist_only_lists": CONF_ZONE_LISTS,
}

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

    _zone_choice: str = ZONE_CHOICE_NEW

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
            menu_options=[
                "database",
                "intervals",
                "lists",
                "list_urls",
                "zones",
                "zone_config",
                "new_domains",
                "sidebar",
            ],
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
                if not self._zones_stay_valid(definitions):
                    errors["base"] = "list_in_use"
            if not errors:
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

    async def async_step_new_domains(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask whether the existing query log history is reported as new."""
        if user_input is not None:
            report = user_input.get(CONF_REPORT_EXISTING_DOMAINS) is True
            return self.async_create_entry(
                data={
                    **self._options_without((CONF_REPORT_EXISTING_DOMAINS,)),
                    CONF_REPORT_EXISTING_DOMAINS: report,
                }
            )
        current = {
            CONF_REPORT_EXISTING_DOMAINS: (
                self.config_entry.options.get(CONF_REPORT_EXISTING_DOMAINS) is True
            )
        }
        return self.async_show_form(
            step_id="new_domains",
            data_schema=self.add_suggested_values_to_schema(
                STEP_NEW_DOMAINS_SCHEMA, current
            ),
        )

    async def async_step_sidebar(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask whether the query log panel appears in the sidebar."""
        if user_input is not None:
            show = user_input.get(CONF_SHOW_IN_SIDEBAR) is True
            return self.async_create_entry(
                data={
                    **self._options_without((CONF_SHOW_IN_SIDEBAR,)),
                    CONF_SHOW_IN_SIDEBAR: show,
                }
            )
        current = {
            CONF_SHOW_IN_SIDEBAR: (
                self.config_entry.options.get(CONF_SHOW_IN_SIDEBAR, True) is True
            )
        }
        return self.async_show_form(
            step_id="sidebar",
            data_schema=self.add_suggested_values_to_schema(
                STEP_SIDEBAR_SCHEMA, current
            ),
        )

    def _zones_stay_valid(self, new_lists: dict[str, dict[str, Any]]) -> bool:
        """Return whether every stored zone is still valid with new lists."""
        options = self.config_entry.options
        new_definitions = read_definitions({CONF_LISTS: new_lists})
        for zone in read_zones(options, read_definitions(options)).values():
            try:
                build_zone(
                    zone.name,
                    [str(net) for net in zone.networks],
                    zone.mode,
                    list(zone.lists),
                    definitions=new_definitions,
                    others=(),
                )
            except ZoneError:
                return False
        return True

    def _zones(self) -> dict[str, ZoneDefinition]:
        options = self.config_entry.options
        return read_zones(options, read_definitions(options))

    async def async_step_zones(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose a zone to edit, or add a new one."""
        zones = self._zones()
        if user_input is not None:
            choice = user_input.get(CONF_ZONE)
            if choice == ZONE_CHOICE_NEW or choice in zones:
                self._zone_choice = choice
                return await self.async_step_zone_edit()

        schema = vol.Schema(
            {
                vol.Required(CONF_ZONE, default=ZONE_CHOICE_NEW): SelectSelector(
                    SelectSelectorConfig(
                        options=[ZONE_CHOICE_NEW, *zones],
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="zone_choice",
                    )
                )
            }
        )
        return self.async_show_form(step_id="zones", data_schema=schema)

    async def async_step_zone_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a zone, or change or delete one."""
        errors: dict[str, str] = {}
        zones = self._zones()
        definitions = read_definitions(self.config_entry.options)
        choice = self._zone_choice
        editing = choice != ZONE_CHOICE_NEW and choice in zones
        if choice != ZONE_CHOICE_NEW and not editing:
            return await self.async_step_zones()

        if user_input is not None:
            if editing and user_input.get(CONF_ZONE_DELETE) is True:
                remaining = {
                    name: zone_to_options(zone)
                    for name, zone in zones.items()
                    if name != choice
                }
                return self._save_zones(remaining)

            name = (
                choice if editing else str(user_input.get(CONF_ZONE_NAME, "")).strip()
            )
            if not editing and name in zones:
                errors[CONF_ZONE_NAME] = "duplicate_zone_name"
            elif not editing and len(zones) >= MAX_ZONES:
                errors["base"] = "too_many_zones"
            else:
                try:
                    zone = build_zone(
                        name,
                        [
                            str(net).strip()
                            for net in user_input.get(CONF_ZONE_NETWORKS, [])
                        ],
                        user_input.get(CONF_ZONE_MODE),
                        list(user_input.get(CONF_ZONE_LISTS, [])),
                        definitions=definitions,
                        others=[z for key, z in zones.items() if key != name],
                    )
                except ZoneError as err:
                    field = _ZONE_ERROR_FIELDS.get(err.code, "base")
                    if field == CONF_ZONE_NAME and editing:
                        field = "base"
                    if field == CONF_ZONE_LISTS and not definitions:
                        field = "base"
                    errors[field] = err.code
                else:
                    saved = {key: zone_to_options(z) for key, z in zones.items()}
                    saved[zone.name] = zone_to_options(zone)
                    return self._save_zones(saved)
            suggested: dict[str, Any] = dict(user_input)
        elif editing:
            existing = zones[choice]
            suggested = {
                CONF_ZONE_NETWORKS: [str(net) for net in existing.networks],
                CONF_ZONE_MODE: existing.mode,
                CONF_ZONE_LISTS: list(existing.lists),
            }
        else:
            suggested = {}

        fields: dict[Any, Any] = {}
        if not editing:
            fields[vol.Required(CONF_ZONE_NAME)] = TextSelector()
        fields[vol.Required(CONF_ZONE_NETWORKS, default=list)] = TextSelector(
            TextSelectorConfig(multiple=True)
        )
        fields[vol.Required(CONF_ZONE_MODE, default=ZONE_MODES[0])] = SelectSelector(
            SelectSelectorConfig(
                options=list(ZONE_MODES),
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="zone_mode",
            )
        )
        if definitions:
            fields[vol.Optional(CONF_ZONE_LISTS, default=list)] = SelectSelector(
                SelectSelectorConfig(
                    options=list(definitions),
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        if editing:
            fields[vol.Optional(CONF_ZONE_DELETE, default=False)] = BooleanSelector()

        return self.async_show_form(
            step_id="zone_edit",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(fields), suggested
            ),
            errors=errors,
            description_placeholders={CONF_ZONE: choice if editing else "-"},
        )

    def _save_zones(self, zones: dict[str, dict[str, Any]]) -> ConfigFlowResult:
        return self.async_create_entry(
            data={**self._options_without((CONF_ZONES,)), CONF_ZONES: zones}
        )

    async def async_step_zone_config(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the Blocky configuration fragment for the zones."""
        if user_input is not None:
            # Nothing to save; keep the options exactly as they are.
            return self.async_abort(reason="zone_config_closed")

        runtime = getattr(self.config_entry, "runtime_data", None)
        if runtime is None:
            return self.async_abort(reason="not_loaded")
        try:
            base = get_url(
                self.hass, allow_external=False, allow_cloud=False, allow_ip=True
            )
        except NoURLAvailableError:
            base = ""

        urls = {
            name: f"{base}{runtime.lists.path(name)}"
            for name in runtime.lists.definitions
        }
        fragment = render_blocky_config(runtime.zones, urls, runtime.lists.definitions)
        return self.async_show_form(
            step_id="zone_config",
            data_schema=vol.Schema({}),
            description_placeholders={
                "config": f"```yaml\n{fragment}```" if fragment else "-"
            },
        )
