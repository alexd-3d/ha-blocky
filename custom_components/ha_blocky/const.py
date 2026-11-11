"""Constants for the Blocky DNS integration."""

from dataclasses import dataclass
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

# Default for how often new log rows are counted, and how often top lists
# are rebuilt.
STATS_INTERVAL: Final = timedelta(seconds=60)
TOPS_INTERVAL: Final = timedelta(minutes=5)

# Limits of one query log request from the card.
MAX_LOG_ROWS: Final = 200
MAX_LOG_HOURS: Final = 24 * 30

# Manual lists served to Blocky.
CONF_LISTS: Final = "lists"
CONF_LIST_NETWORKS: Final = "list_networks"
# Fields of the options form that defines the lists.
CONF_ALLOW_LISTS: Final = "allow_lists"
CONF_DENY_LISTS: Final = "deny_lists"
CONF_EXACT_ONLY_LISTS: Final = "exact_only_lists"
LIST_TYPE_ALLOW: Final = "allow"
LIST_TYPE_DENY: Final = "deny"
LIST_TYPES: Final = (LIST_TYPE_ALLOW, LIST_TYPE_DENY)
MAX_LISTS: Final = 20
MAX_LIST_ENTRIES: Final = 5000
# Only these clients may fetch lists. The default is the network Home
# Assistant Supervisor puts apps (add-ons) on; it is the same on every
# Home Assistant OS installation.
DEFAULT_LIST_NETWORKS: Final = ("172.30.32.0/23",)
# Blocky is asked to reload this long after the last change to a list.
REFRESH_DEBOUNCE_SECONDS: Final = 10

# Zones: user-defined client groups, used only to tell which policy applies to
# a client address seen in the query log. Blocky's own config is never changed.
CONF_ZONES: Final = "zones"
ZONE_MODE_FILTER: Final = "filter"
ZONE_MODE_LEARNING: Final = "learning"
ZONE_MODE_ALLOWLIST_ONLY: Final = "allowlist_only"
ZONE_MODES: Final = (ZONE_MODE_FILTER, ZONE_MODE_LEARNING, ZONE_MODE_ALLOWLIST_ONLY)
MAX_ZONES: Final = 16
MAX_ZONE_NETWORKS: Final = 8

EVENT_LIST_CHANGED: Final = f"{DOMAIN}_list_changed"
SERVICE_ALLOW_DOMAIN: Final = "allow_domain"
SERVICE_BLOCK_DOMAIN: Final = "block_domain"
SERVICE_REMOVE_DOMAIN: Final = "remove_domain"
SERVICE_GET_LIST: Final = "get_list"
SERVICE_ROTATE_LIST_TOKEN: Final = "rotate_list_token"  # noqa: S105
ATTR_LIST: Final = "list"
ATTR_DOMAIN: Final = "domain"
ATTR_ACTION: Final = "action"

# Update intervals the user can change in the options, in seconds.
CONF_STATUS_INTERVAL: Final = "status_interval"
CONF_STATS_INTERVAL: Final = "stats_interval"
CONF_TOPS_INTERVAL: Final = "tops_interval"


@dataclass(frozen=True, slots=True)
class IntervalSpec:
    """Default and allowed range of one update interval, in seconds."""

    default: int
    minimum: int
    maximum: int


INTERVALS: Final = {
    CONF_STATUS_INTERVAL: IntervalSpec(
        default=int(UPDATE_INTERVAL.total_seconds()), minimum=10, maximum=600
    ),
    CONF_STATS_INTERVAL: IntervalSpec(
        default=int(STATS_INTERVAL.total_seconds()), minimum=30, maximum=3600
    ),
    CONF_TOPS_INTERVAL: IntervalSpec(
        default=int(TOPS_INTERVAL.total_seconds()), minimum=30, maximum=3600
    ),
}
# The window of the summary and top-list sensors.
STATS_WINDOW: Final = timedelta(hours=24)

# Requests for new domains: what the clients of "learning" and
# "allowlist_only" zones ask for, read from the query log.
CONF_REPORT_EXISTING_DOMAINS: Final = "report_existing_domains"
EVENT_NEW_DOMAIN: Final = f"{DOMAIN}_new_domain"
EVENT_UNEXPECTED_DOMAIN: Final = f"{DOMAIN}_unexpected_domain"
EVENT_ZONE_LEAK: Final = f"{DOMAIN}_zone_leak"
EVENT_NEW_DOMAINS_SUMMARY: Final = f"{DOMAIN}_new_domains_summary"
SERVICE_APPROVE_REQUEST: Final = "approve_request"
SERVICE_REJECT_REQUEST: Final = "reject_request"
SERVICE_BLOCK_REQUEST: Final = "block_request"
SERVICE_GET_REQUESTS: Final = "get_requests"
SERVICE_SET_CLIENT_PHASE: Final = "set_client_phase"
ATTR_REQUEST_ID: Final = "request_id"
ATTR_CLIENT: Final = "client"
ATTR_PHASE: Final = "phase"
REQUEST_ACTION_APPROVE: Final = "approve"
REQUEST_ACTION_REJECT: Final = "reject"
REQUEST_ACTION_BLOCK: Final = "block"
REQUEST_ACTIONS: Final = (
    REQUEST_ACTION_APPROVE,
    REQUEST_ACTION_REJECT,
    REQUEST_ACTION_BLOCK,
)
# A client of an allowlist-only zone is either still being learned (blocked
# domains become requests) or locked (blocked domains are only reported).
PHASE_LEARNING: Final = "learning"
PHASE_LOCKED: Final = "locked"
PHASES: Final = (PHASE_LEARNING, PHASE_LOCKED)

# Hard caps; the state is kept in memory and in one store.
MAX_REQUEST_CLIENTS: Final = 256
MAX_KNOWN_PAIRS_PER_CLIENT: Final = 1000
MAX_PENDING_REQUESTS: Final = 200
MAX_REJECTED_PAIRS_PER_CLIENT: Final = 500
MAX_LEAKS_PER_CLIENT: Final = 200
# Log rows read per statistics round.
REQUEST_WINDOW_ROWS: Final = 5000
# Silent baseline of a new client in a learning zone: its names of this long
# ago are taken as known, for at most this many clients per round.
BASELINE_WINDOW: Final = timedelta(days=7)
MAX_BASELINE_CLIENTS_PER_ROUND: Final = 10
REQUEST_TTL: Final = timedelta(hours=24)
# Per client: at most this many events in the window; the rest is summarised.
EVENT_RATE_LIMIT: Final = 5
EVENT_RATE_WINDOW: Final = timedelta(minutes=10)
# A leak keeps the problem sensor on, and is not reported again, this long.
LEAK_WINDOW: Final = timedelta(hours=1)
