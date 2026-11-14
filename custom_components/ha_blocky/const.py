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

# The dashboard tab of the card: the periods and the top-list lengths it may ask
# for, and how long one answer is reused for every open card.
DASHBOARD_PERIODS: Final = ("today", "24h", "7d", "30d")
DASHBOARD_ROWS: Final = (5, 10, 20)
DASHBOARD_CACHE: Final = timedelta(seconds=30)

# The lists served to Blocky. They are fixed: the user edits their entries
# (rules), never their names.
LIST_TYPE_ALLOW: Final = "allow"
LIST_TYPE_DENY: Final = "deny"
LIST_ALLOW_DEFAULT: Final = "allow_default"
LIST_DENY_DEFAULT: Final = "deny_default"
LIST_RESTRICTED_DENY: Final = "restricted_deny"
LIST_LOCKDOWN_ALLOW: Final = "lockdown_allow"
# The list of the editable rules and the type of each. allow_default and
# deny_default are global (Standard, and through the base list groups also
# Restricted); the other two belong to one level.
RULE_LISTS: Final = {
    LIST_ALLOW_DEFAULT: LIST_TYPE_ALLOW,
    LIST_DENY_DEFAULT: LIST_TYPE_DENY,
    LIST_RESTRICTED_DENY: LIST_TYPE_DENY,
    LIST_LOCKDOWN_ALLOW: LIST_TYPE_ALLOW,
}
# The list that is always served empty: the group of the Unfiltered level.
LIST_UNFILTERED_EMPTY: Final = "unfiltered_empty"
SERVED_LISTS: Final = (*RULE_LISTS, LIST_UNFILTERED_EMPTY)
# Lists that refuse wildcard entries when an entry is added.
EXACT_ONLY_LISTS: Final = (LIST_LOCKDOWN_ALLOW,)
CONF_LIST_NETWORKS: Final = "list_networks"
MAX_LIST_ENTRIES: Final = 5000
# Only these clients may fetch lists. The default is the network Home
# Assistant Supervisor puts apps (add-ons) on; it is the same on every
# Home Assistant OS installation.
DEFAULT_LIST_NETWORKS: Final = ("172.30.32.0/23",)
# Blocky is asked to reload this long after the last change to a list.
REFRESH_DEBOUNCE_SECONDS: Final = 10

# Protection levels of a client. Standard is the absence of an entry.
LEVEL_UNFILTERED: Final = "unfiltered"
LEVEL_STANDARD: Final = "standard"
LEVEL_RESTRICTED: Final = "restricted"
LEVEL_LOCKDOWN: Final = "lockdown"
LEVELS: Final = (LEVEL_UNFILTERED, LEVEL_STANDARD, LEVEL_RESTRICTED, LEVEL_LOCKDOWN)
# The levels that need a client line in Blocky's configuration.
CLIENT_LEVELS: Final = (LEVEL_UNFILTERED, LEVEL_RESTRICTED, LEVEL_LOCKDOWN)
# The levels whose clients are watched for new domains.
TRACKED_LEVELS: Final = (LEVEL_RESTRICTED, LEVEL_LOCKDOWN)
CONF_CLIENTS: Final = "clients"
CONF_BASE_GROUPS: Final = "base_groups"
CONF_NOTIFY: Final = "notify"
# The list groups the Blocky fallback client group ("default") uses.
DEFAULT_BASE_GROUPS: Final = ("default",)
MAX_BASE_GROUPS: Final = 16
MAX_CLIENTS: Final = 64
# Notifications (events for new domains) per level: Restricted off, Lockdown on.
DEFAULT_NOTIFY: Final = {LEVEL_RESTRICTED: False, LEVEL_LOCKDOWN: True}

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

# Requests for new domains: what the Restricted and Lockdown clients ask for,
# read from the query log.
CONF_REPORT_EXISTING_DOMAINS: Final = "report_existing_domains"
EVENT_NEW_DOMAIN: Final = f"{DOMAIN}_new_domain"
EVENT_UNEXPECTED_DOMAIN: Final = f"{DOMAIN}_unexpected_domain"
EVENT_LOCKDOWN_LEAK: Final = f"{DOMAIN}_lockdown_leak"
EVENT_NEW_DOMAINS_SUMMARY: Final = f"{DOMAIN}_new_domains_summary"
SERVICE_APPROVE_REQUEST: Final = "approve_request"
SERVICE_REJECT_REQUEST: Final = "reject_request"
SERVICE_BLOCK_REQUEST: Final = "block_request"
SERVICE_GET_REQUESTS: Final = "get_requests"
SERVICE_SET_CLIENT_ASK: Final = "set_client_ask"
ATTR_REQUEST_ID: Final = "request_id"
ATTR_CLIENT: Final = "client"
ATTR_ASK: Final = "ask"
REQUEST_ACTION_APPROVE: Final = "approve"
REQUEST_ACTION_REJECT: Final = "reject"
REQUEST_ACTION_BLOCK: Final = "block"
REQUEST_ACTIONS: Final = (
    REQUEST_ACTION_APPROVE,
    REQUEST_ACTION_REJECT,
    REQUEST_ACTION_BLOCK,
)
# Hard caps; the state is kept in memory and in one store.
MAX_REQUEST_CLIENTS: Final = 256
MAX_KNOWN_PAIRS_PER_CLIENT: Final = 1000
# How many of a client's known domains one answer lists (newest first).
MAX_KNOWN_DOMAINS_SHOWN: Final = 200
MAX_PENDING_REQUESTS: Final = 200
MAX_REJECTED_PAIRS_PER_CLIENT: Final = 500
MAX_LEAKS_PER_CLIENT: Final = 200
# Log rows read per statistics round.
REQUEST_WINDOW_ROWS: Final = 5000
# Silent baseline of a new Restricted client: its names of this long
# ago are taken as known, for at most this many clients per round.
BASELINE_WINDOW: Final = timedelta(days=7)
MAX_BASELINE_CLIENTS_PER_ROUND: Final = 10
REQUEST_TTL: Final = timedelta(hours=24)
# Per client: at most this many events in the window; the rest is summarised.
EVENT_RATE_LIMIT: Final = 5
EVENT_RATE_WINDOW: Final = timedelta(minutes=10)
# A leak keeps the problem sensor on, and is not reported again, this long.
LEAK_WINDOW: Final = timedelta(hours=1)

# The sidebar panel that hosts the query log card full width.
CONF_SHOW_IN_SIDEBAR: Final = "show_in_sidebar"
PANEL_URL_PATH: Final = "ha-blocky"
PANEL_ELEMENT: Final = "ha-blocky-panel"

# Names for client addresses, kept by hand in one store per Home Assistant.
MAX_CLIENT_NAMES: Final = 512
MAX_CLIENT_NAME_LENGTH: Final = 64
