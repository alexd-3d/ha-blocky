"""Constants for the Blocky DNS integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "ha_blocky"
DEVICE_NAME: Final = "HA-Blocky"

UPDATE_INTERVAL: Final = timedelta(seconds=30)

# Durations offered by the pause select, in minutes.
PAUSE_OPTIONS_MINUTES: Final = (5, 15, 30, 60, 120, 240)
# How long turning the blocking switch off pauses filtering.
DEFAULT_PAUSE_MINUTES: Final = 5
# Select option shown while blocking is not paused.
PAUSE_OPTION_ACTIVE: Final = "active"

EVENT_BLOCKING_DISABLED_EXTERNALLY: Final = f"{DOMAIN}_blocking_disabled_externally"

SERVICE_DISABLE_BLOCKING: Final = "disable_blocking"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_DURATION: Final = "duration"
ATTR_GROUPS: Final = "groups"
ATTR_DISABLED_GROUPS: Final = "disabled_groups"
ATTR_ITEMS: Final = "items"

# Query log database (optional), stored in the entry options.
CONF_DB_HOST: Final = "db_host"
CONF_DB_PORT: Final = "db_port"
CONF_DB_NAME: Final = "db_name"
CONF_DB_USERNAME: Final = "db_username"
CONF_DB_PASSWORD: Final = "db_password"  # noqa: S105 (an option key)
DEFAULT_DB_PORT: Final = 3306

# How often new log rows are counted, and how often top lists are rebuilt.
STATS_INTERVAL: Final = timedelta(seconds=60)
TOPS_INTERVAL: Final = timedelta(minutes=5)
# The window of the summary and top-list sensors.
STATS_WINDOW: Final = timedelta(hours=24)
