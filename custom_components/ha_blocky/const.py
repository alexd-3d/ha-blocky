"""Constants for the Blocky DNS integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "ha_blocky"
DEVICE_NAME: Final = "HA-Blocky"

UPDATE_INTERVAL: Final = timedelta(seconds=30)

# Choices for how long the blocking switch pauses filtering, in minutes.
PAUSE_OPTIONS_MINUTES: Final = (5, 15, 30, 60, 120, 240)
DEFAULT_PAUSE_MINUTES: Final = 5

EVENT_BLOCKING_DISABLED_EXTERNALLY: Final = f"{DOMAIN}_blocking_disabled_externally"

SERVICE_DISABLE_BLOCKING: Final = "disable_blocking"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_DURATION: Final = "duration"
ATTR_GROUPS: Final = "groups"
ATTR_DISABLED_GROUPS: Final = "disabled_groups"
