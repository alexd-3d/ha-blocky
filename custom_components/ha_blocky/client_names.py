"""Names for client addresses.

A name is shown next to a client address in the card, the requests and the
events. Sources, strongest first: a name an administrator typed in (kept in one
store, keyed by the address), then the friendly name of a ``device_tracker``
whose ``ip`` attribute is the address. Both go through the same validator:
tracker names are chosen by devices on the network and are hostile.

Names are private. They never appear in diagnostics or log messages.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN, MAX_CLIENT_NAMES, MAX_NAME_MATCHES
from .requests import normalize_client
from .validation import InvalidClientNameError, validate_client_name

STORAGE_VERSION: Final = 1
STORAGE_KEY: Final = f"{DOMAIN}.client_names"
DATA_CLIENT_NAMES: HassKey[ClientNames] = HassKey(f"{DOMAIN}_client_names")


class ClientNameError(Exception):
    """A name could not be stored; ``code`` is a stable machine-readable reason."""

    def __init__(self, code: str) -> None:
        """Remember the reason."""
        super().__init__(code)
        self.code = code


class ClientNames:
    """Manual names plus the names of device trackers."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize empty; the store is read by async_load."""
        self._hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._manual: dict[str, str] = {}

    async def async_load(self) -> None:
        """Restore the manual names, revalidating every entry."""
        stored = await self._store.async_load()
        raw = stored.get("names") if isinstance(stored, dict) else None
        self._manual = {}
        if not isinstance(raw, dict):
            return
        for raw_address, raw_name in list(raw.items())[:MAX_CLIENT_NAMES]:
            address = normalize_client(raw_address)
            if address is None:
                continue
            try:
                self._manual[address] = validate_client_name(raw_name)
            except InvalidClientNameError:
                continue

    def manual_name(self, address: object) -> str | None:
        """Return the manual name of an address, if any."""
        normalized = normalize_client(address)
        return self._manual.get(normalized) if normalized else None

    def _tracker_names(self) -> dict[str, str]:
        """Map addresses to device tracker names; the lowest entity id wins."""
        chosen: dict[str, str | None] = {}
        for state in sorted(
            self._hass.states.async_all("device_tracker"), key=lambda s: s.entity_id
        ):
            address = normalize_client(state.attributes.get("ip"))
            if address is None or address in chosen:
                continue
            try:
                chosen[address] = validate_client_name(
                    state.attributes.get("friendly_name")
                )
            except InvalidClientNameError:
                # The winner has an unusable name: the address stays unnamed.
                chosen[address] = None
        return {address: name for address, name in chosen.items() if name is not None}

    def manual_names(self) -> dict[str, str]:
        """Return a copy of the address -> manual name map."""
        return dict(self._manual)

    def name_map(self) -> Mapping[str, str]:
        """Return the address -> name map; build it once per answer or batch."""
        names = self._tracker_names()
        names.update(self._manual)
        return names

    async def async_set(self, address: str, name: str | None) -> str | None:
        """Store (or with None, clear) the manual name of a valid address.

        Raises ClientNameError when the cap is reached.
        """
        if name is None:
            self._manual.pop(address, None)
        else:
            if address not in self._manual and len(self._manual) >= MAX_CLIENT_NAMES:
                raise ClientNameError("too_many_names")
            self._manual[address] = name
        await self._store.async_save({"names": dict(self._manual)})
        return name


def get_client_names(hass: HomeAssistant) -> ClientNames | None:
    """Return the shared names, or None before the integration is set up."""
    return hass.data.get(DATA_CLIENT_NAMES)


def client_name_map(hass: HomeAssistant) -> Mapping[str, str]:
    """Return the current name map; empty when nothing is set up."""
    names = get_client_names(hass)
    return names.name_map() if names is not None else {}


def addresses_with_name(names: Mapping[str, str], text: str) -> list[str]:
    """Return the addresses whose name contains ``text``, ignoring case.

    Sorted, so that the answer is deterministic, and cut at MAX_NAME_MATCHES.
    The text is only compared in Python, it never becomes part of a query.
    """
    needle = text.casefold()
    found = sorted(
        address for address, name in names.items() if needle in name.casefold()
    )
    return found[:MAX_NAME_MATCHES]
