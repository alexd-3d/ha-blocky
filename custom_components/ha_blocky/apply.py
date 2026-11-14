"""Write this integration's entries into the Blocky app's options ("Apply now").

Opt-in (the ``auto_apply`` option, off by default) and only for the Blocky app
that Home Assistant Supervisor runs, without Custom Config Mode. The sequence:
find the app, read its options, merge our list groups and client lines into
them, validate with the Supervisor, write, restart, wait for Blocky's API. When
the API does not come back, the previous options are written back.

The options of the app hold secrets (the query log database password, and the
list token inside our addresses). They pass through memory only: they are never
logged, stored, returned to the card or put into an exception. Every log line
and every error carries a result code or an exception class name, nothing else.
The app is found by comparing the host of the configured Blocky API address
with the host names of the installed apps; no name or slug is ever taken from a
command.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import logging
from collections.abc import Mapping
from typing import Any, Final

from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.hassio import is_hassio
from homeassistant.util import dt as dt_util
from yarl import URL

from .api import BlockyError
from .const import (
    APPLY_MIN_INTERVAL,
    APPLY_POLL_SECONDS,
    APPLY_WAIT_SECONDS,
    CONF_AUTO_APPLY,
    LEVEL_LOCKDOWN,
    LEVEL_RESTRICTED,
    LEVEL_UNFILTERED,
    LIST_LOCKDOWN_ALLOW,
    LIST_RESTRICTED_DENY,
    LIST_UNFILTERED_EMPTY,
)
from .coordinator import BlockyConfigEntry
from .levels import (
    RESERVED_GROUPS,
    ClientConfig,
    client_groups,
    list_urls,
)
from .validation import normalize_client

_LOGGER = logging.getLogger(__name__)

# Results of a run that reached the end.
RESULT_OK: Final = "ok"
RESULT_UNCHANGED: Final = "unchanged"
RESULT_RESTORED: Final = "restored"
RESULT_RESTORE_FAILED: Final = "restore_failed"

# Fixed texts for the refusals (they never contain input or Supervisor words).
APPLY_ERRORS: Final = {
    "apply_off": "Applying to Blocky is switched off.",
    "apply_no_supervisor": "Home Assistant Supervisor is not available.",
    "apply_busy": "An apply is running already.",
    "apply_too_soon": "The previous apply finished a moment ago.",
    "apply_app_not_found": "The Blocky app was not found.",
    "apply_custom_config": "The Blocky app uses Custom Config Mode.",
    "apply_no_url": "Home Assistant has no internal address to give Blocky.",
    "apply_unexpected": "The options of the Blocky app are not as expected.",
    "apply_invalid": "The Supervisor refused the new options of the Blocky app.",
    "apply_failed": "The Supervisor could not be asked.",
}

# The names this integration owns in each of the app's lists.
OWN_DENY: Final = (LEVEL_RESTRICTED, LEVEL_UNFILTERED)
OWN_ALLOW: Final = (LEVEL_LOCKDOWN,)


class ApplyError(Exception):
    """A refusal; ``code`` is one of the keys of APPLY_ERRORS."""

    def __init__(self, code: str) -> None:
        """Remember the code (the only content of the error)."""
        super().__init__(code)
        self.code = code


def with_auto_apply(options: Mapping[str, Any], enabled: bool) -> dict[str, Any]:
    """Return the options with the opt-in switched."""
    new = dict(options)
    new[CONF_AUTO_APPLY] = enabled
    return new


# --- The merge (pure) ----------------------------------------------------------


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _entries(
    blocking: dict[str, Any], key: str, items_key: str
) -> list[dict[str, Any]]:
    """Return the checked list ``blocking[key]`` (a missing one is empty)."""
    value = blocking.get(key, [])
    if not isinstance(value, list):
        raise ApplyError("apply_unexpected")
    for item in value:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not _is_str_list(item.get(items_key))
        ):
            raise ApplyError("apply_unexpected")
    return value


def merge_blocking(
    options: Mapping[str, Any],
    base_groups: tuple[str, ...],
    clients: Mapping[str, ClientConfig],
    urls: Mapping[str, str],
) -> dict[str, Any]:
    """Return a copy of the app's options with this integration's entries.

    Our entries are the same as ``render_block`` renders for the "app" format:
    the deny groups Restricted and Unfiltered, the allow group Lockdown and one
    client line per client. Entries with other names, and every other key, stay
    as they are. Raises ApplyError("apply_unexpected") for any structure that is
    not exactly the documented one; the input is never changed.
    """
    merged = copy.deepcopy(dict(options))
    blocking = merged.get("blocking")
    if not isinstance(blocking, dict):
        raise ApplyError("apply_unexpected")
    deny = _entries(blocking, "denylists", "sources")
    allow = _entries(blocking, "allowlists", "sources")
    groups = _entries(blocking, "client_groups_block", "lists")

    blocking["denylists"] = [item for item in deny if item["name"] not in OWN_DENY] + [
        {"name": LEVEL_RESTRICTED, "sources": [urls[LIST_RESTRICTED_DENY]]},
        {"name": LEVEL_UNFILTERED, "sources": [urls[LIST_UNFILTERED_EMPTY]]},
    ]
    blocking["allowlists"] = [
        item for item in allow if item["name"] not in OWN_ALLOW
    ] + [{"name": LEVEL_LOCKDOWN, "sources": [urls[LIST_LOCKDOWN_ALLOW]]}]

    kept = []
    for item in groups:
        address = normalize_client(item["name"])
        if address is not None and (
            address in clients or any(name in RESERVED_GROUPS for name in item["lists"])
        ):
            continue
        kept.append(item)
    kept.extend(
        {"name": address, "lists": list(client_groups(clients[address], base_groups))}
        for address in sorted(clients)
    )
    blocking["client_groups_block"] = kept
    return merged


# --- The run -------------------------------------------------------------------


def _supervisor(hass: HomeAssistant) -> Any:
    """Return the Supervisor client (imported here: no Supervisor, no import)."""
    from homeassistant.components.hassio import get_supervisor_client

    return get_supervisor_client(hass)


def _hostname(slug: str) -> str:
    from homeassistant.components.hassio import (
        hostname_from_addon_slug,
    )

    return hostname_from_addon_slug(slug)


def _models() -> Any:
    from aiohasupervisor.models import AddonsOptions

    return AddonsOptions


async def _find_app(client: Any, host: str) -> str:
    """Return the slug of the one installed app whose host name is ``host``."""
    slugs = [
        addon.slug
        for addon in await client.addons.list()
        if isinstance(addon.slug, str) and _hostname(addon.slug).lower() == host
    ]
    if len(slugs) != 1:
        raise ApplyError("apply_app_not_found")
    return slugs[0]


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def _wait_for_api(entry: BlockyConfigEntry) -> bool:
    """Poll Blocky's API until it answers or the time is up."""
    for attempt in range(int(APPLY_WAIT_SECONDS // APPLY_POLL_SECONDS) + 1):
        if attempt:
            await _sleep(APPLY_POLL_SECONDS)
        try:
            await entry.runtime_data.coordinator.client.async_get_status()
        except BlockyError:
            continue
        return True
    return False


async def _write_and_restart(
    client: Any, slug: str, config: dict[str, Any], entry: BlockyConfigEntry
) -> bool:
    """Write the options, restart the app and wait for the API. Never raises
    for a Supervisor problem: False then.
    """
    try:
        await client.addons.set_addon_options(slug, _models()(config=config))
        # The restart call has no time limit of its own: a Supervisor that
        # never answers must not hold the apply lock for ever.
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(APPLY_WAIT_SECONDS):
                await client.addons.restart_addon(slug)
    except Exception as err:
        _LOGGER.warning("Blocky apply: the Supervisor failed (%s)", type(err).__name__)
        return False
    return await _wait_for_api(entry)


async def _run(hass: HomeAssistant, entry: BlockyConfigEntry, client: Any) -> str:
    """Do the work; return a result code or raise ApplyError."""
    data = entry.runtime_data
    host = (URL(entry.data[CONF_URL]).host or "").lower()
    slug = await _find_app(client, host)
    info = await client.addons.addon_info(slug)
    options = info.options
    if not isinstance(options, dict):
        raise ApplyError("apply_unexpected")
    if options.get("custom_config") is True:
        raise ApplyError("apply_custom_config")
    base, urls = list_urls(hass, data.lists, data.levels.rev)
    if not base:
        raise ApplyError("apply_no_url")
    merged = merge_blocking(options, data.levels.base_groups, data.levels.clients, urls)
    if merged == options:
        return RESULT_UNCHANGED
    try:
        checked = await client.addons.addon_config_validate(slug, merged)
        valid = checked.valid is True
    except Exception as err:
        _LOGGER.warning("Blocky apply: validation failed (%s)", type(err).__name__)
        valid = False
    if not valid:
        raise ApplyError("apply_invalid")

    previous = copy.deepcopy(options)
    if await _write_and_restart(client, slug, merged, entry):
        return RESULT_OK
    _LOGGER.warning("Blocky apply: Blocky did not come back; restoring the options")
    if await _write_and_restart(client, slug, previous, entry):
        return RESULT_RESTORED
    return RESULT_RESTORE_FAILED


async def async_apply(hass: HomeAssistant, entry: BlockyConfigEntry) -> str:
    """Apply now. Returns a result code or raises ApplyError (nothing written)."""
    data = entry.runtime_data
    if entry.options.get(CONF_AUTO_APPLY) is not True:
        raise ApplyError("apply_off")
    if not is_hassio(hass):
        raise ApplyError("apply_no_supervisor")
    if data.apply_lock.locked():
        raise ApplyError("apply_busy")
    async with data.apply_lock:
        finished = data.apply_finished
        if finished is not None and dt_util.utcnow() - finished < APPLY_MIN_INTERVAL:
            raise ApplyError("apply_too_soon")
        try:
            client = _supervisor(hass)
            result = await _run(hass, entry, client)
        except ApplyError:
            raise
        except Exception as err:
            # Class name only: the Supervisor's words may hold option values.
            _LOGGER.warning(
                "Blocky apply: the Supervisor could not be read (%s)",
                type(err).__name__,
            )
            data.apply_finished = dt_util.utcnow()
            raise ApplyError("apply_failed") from None
        data.apply_finished = dt_util.utcnow()
        data.last_apply = {
            "result": result,
            "at": data.apply_finished.isoformat(timespec="seconds"),
        }
        _LOGGER.info("Blocky apply finished: %s", result)

    if result == RESULT_OK:
        # The same as the card's Check now: ask Blocky to fetch its lists again.
        with contextlib.suppress(BlockyError):
            await data.coordinator.async_refresh_lists()
    return result
