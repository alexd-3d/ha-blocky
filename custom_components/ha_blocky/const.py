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
