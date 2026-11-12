"""Update intervals chosen in the options, read defensively."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from .const import INTERVALS


def parse_interval(value: Any, key: str) -> int | None:
    """Return ``value`` as whole seconds within the bounds of ``key``, else None."""
    spec = INTERVALS[key]
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if not spec.minimum <= value <= spec.maximum:
        return None
    return value


def interval_seconds(options: Mapping[str, Any], key: str) -> int:
    """Return a valid interval in seconds, or the default.

    Stored options are not trusted: a missing, non-numeric or out-of-range
    value falls back to the default instead of producing a tight poll loop.
    """
    value = parse_interval(options.get(key), key)
    return INTERVALS[key].default if value is None else value


def interval(options: Mapping[str, Any], key: str) -> timedelta:
    """Return a valid interval as a timedelta."""
    return timedelta(seconds=interval_seconds(options, key))
