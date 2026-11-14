"""Tests for the validation of list entries, group names, clients and networks."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.ha_blocky.validation import (
    InvalidDomainError,
    InvalidGroupNameError,
    InvalidNetworkError,
    address_in_networks,
    normalize_client,
    normalize_domain,
    parse_networks,
    validate_group_name,
)

# --- Domains ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("example.com", "example.com"),
        ("  Example.COM.  ", "example.com"),
        ("sub.domain.example.co.uk", "sub.domain.example.co.uk"),
        ("*.example.com", "*.example.com"),
        ("*.Example.com.", "*.example.com"),
        ("xn--e1afmkfd.xn--p1ai", "xn--e1afmkfd.xn--p1ai"),
        ("приклад.укр", "xn--80aikifvh.xn--j1amh"),
        ("_dmarc.example.com", "_dmarc.example.com"),
        ("a-b.example.com", "a-b.example.com"),
        ("1.example.com", "1.example.com"),
        ("a" * 63 + ".example.com", "a" * 63 + ".example.com"),
    ],
)
def test_normalize_domain_accepts(value: str, expected: str) -> None:
    assert normalize_domain(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "com",
        "localhost",
        "*",
        "*.",
        "*.com",
        "**.example.com",
        "*.*.example.com",
        "a.*.example.com",
        "example.*",
        "ex*ample.com",
        "/.*/",
        "/example\\.com/",
        "example.com/path",
        "http://example.com",
        "example.com:443",
        "user@example.com",
        "exa mple.com",
        "example.com\nother.example",
        "example.com\x00",
        "example..com",
        ".example.com",
        "-example.com",
        "example-.com",
        "exam!ple.com",
        "example.com # comment",
        "0.0.0.0 example.com",
        "||example.com^",
        "192.0.2.1",
        "2001:db8::1",
        "example.123",
        "a" * 64 + ".example.com",
        ".".join(["a" * 60] * 5) + ".com",
        None,
        42,
        b"example.com",
        ["example.com"],
    ],
)
def test_normalize_domain_rejects(value: Any) -> None:
    with pytest.raises(InvalidDomainError):
        normalize_domain(value)


def test_wildcard_can_be_forbidden() -> None:
    assert normalize_domain("example.com", allow_wildcard=False) == "example.com"
    with pytest.raises(InvalidDomainError):
        normalize_domain("*.example.com", allow_wildcard=False)


def test_normalized_entries_are_safe_for_a_blocky_list() -> None:
    """Nothing that passes can start a comment, a regex or a second column."""
    for value in ("example.com", "*.example.com", "приклад.укр", "_srv.example.com"):
        entry = normalize_domain(value)
        assert entry.isascii()
        assert not any(char in entry for char in " \t\n\r#/|^\\")
        assert entry.count("*") <= 1


# --- Group names ------------------------------------------------------------


@pytest.mark.parametrize(
    "value", ["default", "ads-and-trackers", "a", "Q1", "a.b_c", "x" * 64]
)
def test_validate_group_name_accepts(value: str) -> None:
    assert validate_group_name(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "_leading",
        "-dash",
        "with space",
        "../etc",
        "a/b",
        "x" * 65,
        "name\n",
        'q"uote',
        "a: b",
        "a,b",
        None,
        1,
    ],
)
def test_validate_group_name_rejects(value: Any) -> None:
    with pytest.raises(InvalidGroupNameError):
        validate_group_name(value)


# --- Clients ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("192.0.2.5", "192.0.2.5"),
        (" 192.0.2.5 ", "192.0.2.5"),
        ("2001:DB8::1", "2001:db8::1"),
        ("::ffff:192.0.2.5", "192.0.2.5"),
    ],
)
def test_normalize_client_accepts(value: str, expected: str) -> None:
    assert normalize_client(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "example.com",
        "192.0.2.0/24",
        "fe80::1%eth0",
        "192.0.2.5\n9",
        None,
        5,
        "9" * 65,
    ],
)
def test_normalize_client_rejects(value: Any) -> None:
    assert normalize_client(value) is None


# --- Networks ---------------------------------------------------------------


def test_parse_networks_accepts() -> None:
    networks = parse_networks(["192.0.2.0/24", " 198.51.100.7 ", "2001:db8::/32"])

    assert [str(network) for network in networks] == [
        "192.0.2.0/24",
        "198.51.100.7/32",
        "2001:db8::/32",
    ]
    assert parse_networks([]) == ()


@pytest.mark.parametrize(
    "values",
    [
        ["0.0.0.0/0"],
        ["::/0"],
        ["not-a-network"],
        ["192.0.2.0/33"],
        [""],
        [5],
        "192.0.2.0/24",
        None,
        ["192.0.2.0/24"] * 17,
    ],
)
def test_parse_networks_rejects(values: Any) -> None:
    with pytest.raises(InvalidNetworkError):
        parse_networks(values)


def test_address_in_networks() -> None:
    networks = parse_networks(["192.0.2.0/24", "2001:db8::/32"])

    assert address_in_networks("192.0.2.55", networks)
    assert address_in_networks("2001:db8::7", networks)
    assert address_in_networks("::ffff:192.0.2.55", networks)
    assert not address_in_networks("198.51.100.1", networks)
    assert not address_in_networks("2001:db9::1", networks)
    assert not address_in_networks("192.0.2.55, 198.51.100.1", networks)
    assert not address_in_networks("", networks)
    assert not address_in_networks(None, networks)
    assert not address_in_networks("192.0.2.55", ())
