"""Display preferences of the card, kept per Home Assistant.

Two things are stored: the colour of each kind of query (only the ones that
differ from the default) and the default number of rows of the dashboard top
lists. Every value is validated when it is set and again when it is loaded,
because the store is not trusted either. A colour is exactly "#rrggbb": the
card writes it into a style sheet, so nothing else may ever get through.
"""

from __future__ import annotations

import re
from typing import Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util.hass_dict import HassKey

from .const import DASHBOARD_ROWS, DOMAIN
from .db import CATEGORIES

STORAGE_VERSION: Final = 1
STORAGE_KEY: Final = f"{DOMAIN}.display"
DATA_DISPLAY: HassKey[DisplaySettings] = HassKey(f"{DOMAIN}_display")
_COLOR_RE: Final = re.compile(r"#[0-9a-fA-F]{6}")


def valid_color(value: object) -> str | None:
    """Return the colour in lower case if it is exactly #rrggbb, else None."""
    if isinstance(value, str) and _COLOR_RE.fullmatch(value) is not None:
        return value.lower()
    return None


def valid_rows(value: object) -> int | None:
    """Return the row count if it is one of the allowed choices, else None."""
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value in DASHBOARD_ROWS
    ):
        return value
    return None


class DisplaySettings:
    """The colours and the default row count."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize with the defaults; the store is read by async_load."""
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.colors: dict[str, str] = {}
        self.rows: int | None = None

    async def async_load(self) -> None:
        """Restore the saved preferences, revalidating every value."""
        stored = await self._store.async_load()
        self.colors = {}
        self.rows = None
        if not isinstance(stored, dict):
            return
        raw = stored.get("colors")
        if isinstance(raw, dict):
            for category in CATEGORIES:
                color = valid_color(raw.get(category))
                if color is not None:
                    self.colors[category] = color
        self.rows = valid_rows(stored.get("rows"))

    def describe(self) -> dict[str, Any]:
        """Return what the card needs: the overridden colours and the rows."""
        return {"colors": dict(self.colors), "rows": self.rows}

    async def async_update(
        self,
        colors: dict[str, str | None] | None,
        rows: int | None,
        *,
        set_rows: bool,
    ) -> None:
        """Apply validated changes: a colour of None clears it, rows None clears."""
        for category, color in (colors or {}).items():
            if color is None:
                self.colors.pop(category, None)
            else:
                self.colors[category] = color
        if set_rows:
            self.rows = rows
        await self._store.async_save({"colors": dict(self.colors), "rows": self.rows})


def get_display(hass: HomeAssistant) -> DisplaySettings | None:
    """Return the shared preferences, or None before the integration is set up."""
    return hass.data.get(DATA_DISPLAY)
