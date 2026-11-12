"""Validation of everything that ends up in a list served to Blocky.

A manual list is fed straight into the DNS filter, so entries are restricted
to plain domain names and, where allowed, a single leading ``*.`` wildcard.
Blocky's regular expressions (``/.../``) and anything broader than a domain
are refused.
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from collections.abc import Iterable
from typing import Final

from .const import MAX_CLIENT_NAME_LENGTH, MAX_ZONE_NETWORKS

MAX_DOMAIN_LENGTH: Final = 253
MAX_LIST_NAME_LENGTH: Final = 32
MAX_NETWORKS: Final = 16

_LABEL_RE: Final = re.compile(r"[a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?")
_LIST_NAME_RE: Final = re.compile(r"[a-z0-9][a-z0-9_]{0,31}")

type IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class InvalidDomainError(ValueError):
    """The value is not an acceptable list entry."""


class InvalidListNameError(ValueError):
    """The value is not an acceptable list name."""


class InvalidZoneNameError(ValueError):
    """The value is not an acceptable zone name."""


class InvalidClientNameError(ValueError):
    """The value is not an acceptable client name."""


class InvalidNetworkError(ValueError):
    """The value is not an acceptable network."""


def normalize_domain(value: object, *, allow_wildcard: bool = True) -> str:
    """Return the canonical form of a list entry or raise InvalidDomainError.

    Accepts ``example.com`` and, if allowed, ``*.example.com``. The result is
    lower-case ASCII (IDNA-encoded) without a trailing dot.
    """
    if not isinstance(value, str):
        raise InvalidDomainError("not a string")
    text = value.strip()
    if not text or len(text) > MAX_DOMAIN_LENGTH + 3:
        raise InvalidDomainError("empty or too long")
    if any(char.isspace() or not char.isprintable() for char in text):
        raise InvalidDomainError("whitespace or control character")

    text = text.lower()
    wildcard = text.startswith("*.")
    if wildcard:
        text = text[2:]
    if "*" in text:
        raise InvalidDomainError("wildcard is only allowed as a leading '*.'")
    if wildcard and not allow_wildcard:
        raise InvalidDomainError("wildcards are not allowed in this list")

    text = text.removesuffix(".")
    if not text.isascii():
        try:
            text = text.encode("idna").decode("ascii")
        except UnicodeError as err:
            raise InvalidDomainError("not a valid internationalized name") from err

    if len(text) > MAX_DOMAIN_LENGTH:
        raise InvalidDomainError("too long")
    try:
        ipaddress.ip_address(text)
    except ValueError:
        pass
    else:
        raise InvalidDomainError("an IP address is not a domain")

    labels = text.split(".")
    if len(labels) < 2:
        raise InvalidDomainError("a bare top-level name is too broad")
    for label in labels:
        if _LABEL_RE.fullmatch(label) is None:
            raise InvalidDomainError("invalid label")
    if labels[-1].isdigit():
        raise InvalidDomainError("numeric top-level label")

    return f"*.{text}" if wildcard else text


def validate_list_name(value: object) -> str:
    """Return a valid list name or raise InvalidListNameError."""
    if not isinstance(value, str) or _LIST_NAME_RE.fullmatch(value) is None:
        raise InvalidListNameError("list name")
    return value


def validate_zone_name(value: object) -> str:
    """Return a valid zone name (same rule as list names) or raise."""
    if not isinstance(value, str) or _LIST_NAME_RE.fullmatch(value) is None:
        raise InvalidZoneNameError("zone name")
    return value


def validate_client_name(value: object) -> str:
    """Return a clean display name for a client or raise InvalidClientNameError.

    The name is stripped, 1 to 64 characters long and free of control,
    format, surrogate, private-use and unassigned characters (every Unicode
    category starting with "C") and of line or paragraph separators. Bad input
    is refused, never repaired.
    """
    if not isinstance(value, str):
        raise InvalidClientNameError("not a string")
    text = value.strip()
    if not 1 <= len(text) <= MAX_CLIENT_NAME_LENGTH:
        raise InvalidClientNameError("empty or too long")
    for char in text:
        category = unicodedata.category(char)
        if category.startswith("C") or category in ("Zl", "Zp"):
            raise InvalidClientNameError("control character")
    return text


def parse_networks(values: object) -> tuple[IPNetwork, ...]:
    """Parse the networks allowed to fetch lists.

    A network that matches every address (prefix length 0) is refused: the
    list of allowed clients is meant to be narrow.
    """
    if isinstance(values, str) or not isinstance(values, Iterable):
        raise InvalidNetworkError("not a list")
    networks: list[IPNetwork] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise InvalidNetworkError("not a string")
        try:
            network = ipaddress.ip_network(value.strip(), strict=False)
        except ValueError as err:
            raise InvalidNetworkError("not a network") from err
        if network.prefixlen == 0:
            raise InvalidNetworkError("matches every address")
        networks.append(network)
        if len(networks) > MAX_NETWORKS:
            raise InvalidNetworkError("too many networks")
    return tuple(networks)


def parse_zone_networks(values: object) -> tuple[IPNetwork, ...]:
    """Parse the networks of a zone: addresses or CIDR, 1 to 8 of them.

    A network that matches every address (prefix length 0) is refused.
    """
    if isinstance(values, str) or not isinstance(values, Iterable):
        raise InvalidNetworkError("not a list")
    networks: list[IPNetwork] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise InvalidNetworkError("not a string")
        if len(networks) >= MAX_ZONE_NETWORKS:
            raise InvalidNetworkError("too many networks")
        try:
            network = ipaddress.ip_network(value.strip(), strict=False)
        except ValueError as err:
            raise InvalidNetworkError("not a network") from err
        if network.prefixlen == 0:
            raise InvalidNetworkError("matches every address")
        networks.append(network)
    if not networks:
        raise InvalidNetworkError("no network")
    return tuple(networks)


def networks_overlap(first: Iterable[IPNetwork], second: Iterable[IPNetwork]) -> bool:
    """Return whether any network of ``first`` overlaps one of ``second``."""
    others = list(second)
    return any(a.version == b.version and a.overlaps(b) for a in first for b in others)


def address_in_networks(address: object, networks: Iterable[IPNetwork]) -> bool:
    """Return whether ``address`` (text) lies in one of ``networks``."""
    if not isinstance(address, str):
        return False
    try:
        parsed: IPAddress = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    return any(
        parsed.version == network.version and parsed in network for network in networks
    )
