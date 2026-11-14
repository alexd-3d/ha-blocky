"""Protection levels of clients and the Blocky configuration they need.

A client (one IP address) has one of four levels. Standard is the absence of an
entry. Home Assistant never writes Blocky's configuration: it renders the
entries to paste and notices, by the ``r`` marker on the list addresses, when
Blocky has fetched the lists of the current revision.

Everything stored is re-validated on every read: nothing stored is trusted.
Free text never reaches the rendered configuration: addresses go through
``ipaddress``, group names through the group name validator.

Live-unverified points (see the ROADMAP, "Live acceptance"), marked here and in
the tests: (a) Blocky fetches the lists again after a restart and keeps the
query string, (b) a Restricted client still resolves an ordinary domain,
(c) an Unfiltered client (an empty deny group) resolves a domain that is on
``deny_default``, (d) a Lockdown client is blocked on an unknown domain and
Approve opens it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from homeassistant.core import HomeAssistant

from .const import (
    CLIENT_LEVELS,
    CONF_BASE_GROUPS,
    CONF_CLIENTS,
    CONF_NOTIFY,
    DEFAULT_BASE_GROUPS,
    DEFAULT_NOTIFY,
    LEVEL_LOCKDOWN,
    LEVEL_RESTRICTED,
    LEVEL_STANDARD,
    LEVEL_UNFILTERED,
    LIST_ALLOW_DEFAULT,
    LIST_DENY_DEFAULT,
    LIST_LOCKDOWN_ALLOW,
    LIST_RESTRICTED_DENY,
    LIST_UNFILTERED_EMPTY,
    MAX_BASE_GROUPS,
    MAX_CLIENTS,
)
from .validation import (
    InvalidGroupNameError,
    normalize_client,
    validate_group_name,
)

_LOGGER = logging.getLogger(__name__)

REV_RE: Final = re.compile(r"[0-9a-f]{8}")
# Group names this integration defines in Blocky; a base group may not use them.
RESERVED_GROUPS: Final = (LEVEL_UNFILTERED, LEVEL_RESTRICTED, LEVEL_LOCKDOWN)


# Which levels each manual list changes the answers for. Derived from the groups
# of client_groups(): a Standard client uses Blocky's base groups (where the
# Always allow / Always block lists belong), a Restricted client the base groups
# plus its own deny list, a Lockdown client only its allow list, an Unfiltered
# client nothing at all. The card reads this to know which log rows an action
# touches and which list to offer first.
LIST_LEVELS: Final[dict[str, tuple[str, ...]]] = {
    LIST_ALLOW_DEFAULT: (LEVEL_STANDARD, LEVEL_RESTRICTED),
    LIST_DENY_DEFAULT: (LEVEL_STANDARD, LEVEL_RESTRICTED),
    LIST_RESTRICTED_DENY: (LEVEL_RESTRICTED,),
    LIST_LOCKDOWN_ALLOW: (LEVEL_LOCKDOWN,),
}


class LevelError(Exception):
    """A change was refused; ``code`` is a short machine-readable reason."""

    def __init__(self, code: str) -> None:
        """Remember the reason."""
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ClientConfig:
    """The level of one client; ``ask`` only matters for Lockdown."""

    level: str
    ask: bool = False


def parse_base_groups(value: object) -> tuple[str, ...]:
    """Validate an ordered list of 1..16 distinct list group names or raise."""
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise LevelError("invalid_base_groups")
    if not 1 <= len(value) <= MAX_BASE_GROUPS:
        raise LevelError("invalid_base_groups")
    names: list[str] = []
    for item in value:
        try:
            name = validate_group_name(item)
        except InvalidGroupNameError:
            raise LevelError("invalid_base_groups") from None
        if name in RESERVED_GROUPS:
            raise LevelError("reserved_group")
        if name in names:
            raise LevelError("duplicate_group")
        names.append(name)
    return tuple(names)


def read_base_groups(options: Mapping[str, Any]) -> tuple[str, ...]:
    """Read the base list groups; anything invalid means the default."""
    raw = options.get(CONF_BASE_GROUPS)
    if raw is None:
        return DEFAULT_BASE_GROUPS
    try:
        return parse_base_groups(raw)
    except LevelError:
        _LOGGER.error("Stored base list groups are invalid; using the default")
        return DEFAULT_BASE_GROUPS


def base_groups_saved(options: Mapping[str, Any]) -> bool:
    """Return whether the base list groups were ever saved (even as the default)."""
    return options.get(CONF_BASE_GROUPS) is not None


def read_clients(options: Mapping[str, Any]) -> dict[str, ClientConfig]:
    """Read the clients from the options, dropping invalid ones. Never raises."""
    raw = options.get(CONF_CLIENTS)
    clients: dict[str, ClientConfig] = {}
    if not isinstance(raw, Mapping):
        return clients
    dropped = 0
    for key, spec in raw.items():
        address = normalize_client(key)
        if (
            address is None
            or address in clients
            or not isinstance(spec, Mapping)
            or spec.get("level") not in CLIENT_LEVELS
            or len(clients) >= MAX_CLIENTS
        ):
            dropped += 1
            continue
        level = spec["level"]
        clients[address] = ClientConfig(
            level=level,
            ask=level == LEVEL_LOCKDOWN and spec.get("ask") is True,
        )
    if dropped:
        # Neither addresses nor values are logged: they are data.
        _LOGGER.error("%d stored clients were ignored as invalid", dropped)
    return clients


def read_notify(options: Mapping[str, Any]) -> dict[str, bool]:
    """Read the notification switches per level, with the defaults."""
    raw = options.get(CONF_NOTIFY)
    notify = dict(DEFAULT_NOTIFY)
    if isinstance(raw, Mapping):
        for level in notify:
            if isinstance(raw.get(level), bool):
                notify[level] = raw[level]
    return notify


def clients_to_options(clients: Mapping[str, ClientConfig]) -> dict[str, Any]:
    """Return the form in which clients are stored in the options."""
    stored: dict[str, Any] = {}
    for address, config in clients.items():
        spec: dict[str, Any] = {"level": config.level}
        if config.level == LEVEL_LOCKDOWN:
            spec["ask"] = config.ask
        stored[address] = spec
    return stored


def client_groups(
    config: ClientConfig, base_groups: tuple[str, ...]
) -> tuple[str, ...]:
    """Return the list groups of a client line in Blocky's configuration."""
    if config.level == LEVEL_RESTRICTED:
        return (*base_groups, LEVEL_RESTRICTED)
    return (config.level,)


def sorted_lines(
    clients: Mapping[str, ClientConfig], base_groups: tuple[str, ...]
) -> list[str]:
    """Return the canonical client-to-level lines, sorted."""
    return sorted(
        f"{address}={','.join(client_groups(config, base_groups))}"
        for address, config in clients.items()
    )


def compute_rev(
    base_groups: tuple[str, ...], clients: Mapping[str, ClientConfig]
) -> str:
    """Return the applied marker: 8 hex characters of SHA-256 (not secret)."""
    text = (
        "base="
        + ",".join(base_groups)
        + "\n"
        + "\n".join(sorted_lines(clients, base_groups))
    )
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def valid_rev(value: object) -> str | None:
    """Return ``value`` if it is exactly 8 lower-case hex characters."""
    if isinstance(value, str) and REV_RE.fullmatch(value) is not None:
        return value
    return None


class LevelConfig:
    """The levels of one config entry; swapped as a whole when they change."""

    def __init__(self, options: Mapping[str, Any]) -> None:
        """Read everything from the entry options."""
        self.update(options)

    def update(self, options: Mapping[str, Any]) -> None:
        """Replace the contents with the (re-validated) options."""
        self.clients = read_clients(options)
        self.base_groups = read_base_groups(options)
        self.notify = read_notify(options)

    @property
    def rev(self) -> str:
        """Return the marker of the current configuration."""
        return compute_rev(self.base_groups, self.clients)

    def level_of(self, address: object) -> str | None:
        """Return the non-Standard level of a client address (text), if any."""
        key = normalize_client(address)
        config = self.clients.get(key) if key else None
        return config.level if config else None


def _quote(value: str) -> str:
    """Return a YAML double-quoted scalar (JSON strings are valid YAML)."""
    return json.dumps(value)


def render_block(
    base_groups: tuple[str, ...],
    clients: Mapping[str, ClientConfig],
    urls: Mapping[str, str],
) -> dict[str, str]:
    """Render the entries to add to Blocky's configuration, in two formats.

    ``urls`` maps each served list (restricted_deny, lockdown_allow,
    unfiltered_empty) to its full address including ``?r=<rev>``. Returns
    ``app`` (the option format of the Blocky app, robocopklaus 5.3.0) and
    ``plain`` (Blocky's own YAML). Built only from validated names, addresses
    and the given URLs.
    """
    note = [
        "# Add these entries to your existing blocking section; "
        "do not replace the whole option.",
        "# Each of the three parts goes under the key named in its comment: "
        "merge it with what is already there.",
    ]
    groups = (
        ("denylists", LEVEL_RESTRICTED, LIST_RESTRICTED_DENY),
        ("allowlists", LEVEL_LOCKDOWN, LIST_LOCKDOWN_ALLOW),
        ("denylists", LEVEL_UNFILTERED, LIST_UNFILTERED_EMPTY),
    )
    parts = {
        "denylists": "add these groups to your existing denylists.",
        "allowlists": "add these groups to your existing allowlists.",
    }

    def label(number: int, key: str, what: str) -> str:
        return f"  # Part {number} of 3, blocking.{key}: {what}"

    app = [*note, "blocking:"]
    plain = [*note, "blocking:"]
    for number, key in enumerate(("denylists", "allowlists"), start=1):
        app.extend([label(number, key, parts[key]), f"  {key}:"])
        plain.extend([label(number, key, parts[key]), f"  {key}:"])
        for kind, name, served in groups:
            if kind == key:
                app.append(f"    - name: {_quote(name)}")
                app.append("      sources:")
                app.append(f"        - {_quote(urls[served])}")
                plain.append(f"    {_quote(name)}:")
                plain.append(f"      - {_quote(urls[served])}")
    what = "add these clients with the list groups they use."
    app.extend([label(3, "client_groups_block", what), "  client_groups_block:"])
    plain.extend([label(3, "clientGroupsBlock", what), "  clientGroupsBlock:"])
    for address in sorted(clients):
        names = client_groups(clients[address], base_groups)
        app.append(f"    - name: {_quote(address)}")
        app.append("      lists:")
        app.extend(f"        - {_quote(name)}" for name in names)
        plain.append(f"    {_quote(address)}:")
        plain.extend(f"      - {_quote(name)}" for name in names)
    return {"app": "\n".join(app) + "\n", "plain": "\n".join(plain) + "\n"}


def with_client(
    options: Mapping[str, Any], address: object, level: str, ask: bool
) -> dict[str, Any]:
    """Return the options with one client set to ``level`` (Standard removes it).

    Raises LevelError. At most MAX_CLIENTS clients.
    """
    key = normalize_client(address)
    if key is None:
        raise LevelError("invalid_client")
    if level != "standard" and level not in CLIENT_LEVELS:
        raise LevelError("invalid_level")
    clients = read_clients(options)
    if level == "standard":
        clients.pop(key, None)
    else:
        if key not in clients and len(clients) >= MAX_CLIENTS:
            raise LevelError("too_many_clients")
        clients[key] = ClientConfig(level, ask and level == LEVEL_LOCKDOWN)
    new = dict(options)
    new[CONF_CLIENTS] = clients_to_options(clients)
    return new


def with_base_groups(options: Mapping[str, Any], groups: object) -> dict[str, Any]:
    """Return the options with new base groups, or raise LevelError."""
    new = dict(options)
    new[CONF_BASE_GROUPS] = list(parse_base_groups(groups))
    return new


def with_notify(
    options: Mapping[str, Any], level: object, enabled: object
) -> dict[str, Any]:
    """Return the options with one notification switch changed."""
    if level not in DEFAULT_NOTIFY or not isinstance(enabled, bool):
        raise LevelError("invalid_notify")
    notify = read_notify(options)
    notify[level] = enabled
    new = dict(options)
    new[CONF_NOTIFY] = notify
    return new


def apply_options(hass: HomeAssistant, entry: Any, new_options: dict[str, Any]) -> None:
    """Store new options and swap the levels in memory, without a reload.

    The runtime objects read ``entry.runtime_data.levels`` on every use, so
    nothing else has to be restarted for a level, base group or notification
    change.
    """
    hass.config_entries.async_update_entry(entry, options=new_options)
    entry.runtime_data.levels.update(new_options)
