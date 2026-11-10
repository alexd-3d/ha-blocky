"""Tests for the entities, the coordinator and the service action."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import aiohttp
import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_URL,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockUser,
    async_capture_events,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.ha_blocky.const import (
    DOMAIN,
    EVENT_BLOCKING_DISABLED_EXTERNALLY,
    UPDATE_INTERVAL,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

BASE_URL = "http://blocky.example:4000"
STATUS_URL = f"{BASE_URL}/api/blocking/status"
ENABLE_URL = f"{BASE_URL}/api/blocking/enable"
DISABLE_URL = f"{BASE_URL}/api/blocking/disable"
REFRESH_URL = f"{BASE_URL}/api/lists/refresh"
FLUSH_URL = f"{BASE_URL}/api/cache/flush"

SWITCH = "switch.ha_blocky_blocking"
RESUMES_AT = "sensor.ha_blocky_blocking_resumes_at"
CONNECTION = "binary_sensor.ha_blocky_connection"
REFRESH_BUTTON = "button.ha_blocky_refresh_lists"
FLUSH_BUTTON = "button.ha_blocky_flush_cache"
PAUSE_SELECT = "select.ha_blocky_pause_blocking"

ENABLED = {"enabled": True, "disabledGroups": [], "autoEnableInSec": 0}


def _disabled(seconds: int = 300, groups: list[str] | None = None) -> dict[str, Any]:
    return {
        "enabled": False,
        "disabledGroups": groups if groups is not None else ["default"],
        "autoEnableInSec": seconds,
    }


def _set_status(aioclient_mock: AiohttpClientMocker, **kwargs: Any) -> None:
    """Replace the canned status answer, keeping the command endpoints."""
    aioclient_mock.clear_requests()
    aioclient_mock.get(STATUS_URL, **kwargs)
    aioclient_mock.get(ENABLE_URL, text="")
    aioclient_mock.get(DISABLE_URL, text="")
    aioclient_mock.post(REFRESH_URL, text="")
    aioclient_mock.post(FLUSH_URL, text="")


def _calls(aioclient_mock: AiohttpClientMocker, path: str) -> list[dict[str, str]]:
    """Return the query of every recorded call to ``path``."""
    return [
        dict(url.query)
        for _method, url, _data, _headers in aioclient_mock.mock_calls
        if url.path == path
    ]


async def _setup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, **status: Any
) -> MockConfigEntry:
    _set_status(aioclient_mock, **(status or {"json": ENABLED}))
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_URL: BASE_URL})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def _poll(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + UPDATE_INTERVAL)
    await hass.async_block_till_done()


# --- Entities ---------------------------------------------------------------


async def test_entities_are_created(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(hass, aioclient_mock)

    assert hass.states.get(SWITCH).state == STATE_ON
    assert hass.states.get(SWITCH).attributes["disabled_groups"] == []
    assert hass.states.get(RESUMES_AT).state == STATE_UNKNOWN
    assert hass.states.get(CONNECTION).state == STATE_ON
    assert hass.states.get(PAUSE_SELECT).state == "active"
    assert hass.states.get(PAUSE_SELECT).attributes["options"] == [
        "active",
        "5",
        "15",
        "30",
        "60",
        "120",
        "240",
    ]
    assert hass.states.get(REFRESH_BUTTON) is not None
    assert hass.states.get(FLUSH_BUTTON) is not None

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(entities) == 6
    assert all(e.unique_id.startswith(f"{entry.entry_id}_") for e in entities)

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    assert devices[0].name == "HA-Blocky"


async def test_unload_removes_states(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(hass, aioclient_mock)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get(SWITCH).state == STATE_UNAVAILABLE


# --- Switch -----------------------------------------------------------------


async def test_switch_off_pauses_for_default_duration(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    events = async_capture_events(hass, EVENT_BLOCKING_DISABLED_EXTERNALLY)
    _set_status(aioclient_mock, json=_disabled(300))

    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: SWITCH}, blocking=True
    )
    await hass.async_block_till_done()

    assert _calls(aioclient_mock, "/api/blocking/disable") == [{"duration": "300s"}]
    assert hass.states.get(SWITCH).state == STATE_OFF
    assert hass.states.get(SWITCH).attributes["disabled_groups"] == ["default"]
    assert hass.states.get(PAUSE_SELECT).state == "5"
    resumes_at = dt_util.parse_datetime(hass.states.get(RESUMES_AT).state)
    assert resumes_at is not None
    assert abs(resumes_at - (dt_util.utcnow() + timedelta(seconds=300))) < timedelta(
        seconds=5
    )
    assert events == []


async def _select(hass: HomeAssistant, option: str) -> None:
    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: PAUSE_SELECT, "option": option},
        blocking=True,
    )


async def test_select_pauses_immediately(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    events = async_capture_events(hass, EVENT_BLOCKING_DISABLED_EXTERNALLY)
    _set_status(aioclient_mock, json=_disabled(1800))

    await _select(hass, "30")

    assert _calls(aioclient_mock, "/api/blocking/disable") == [{"duration": "1800s"}]
    assert hass.states.get(PAUSE_SELECT).state == "30"
    assert hass.states.get(SWITCH).state == STATE_OFF
    assert hass.states.get(RESUMES_AT).state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)

    # The choice survives polls and unrelated commands while the pause runs.
    await _poll(hass)
    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: FLUSH_BUTTON}, blocking=True
    )
    assert hass.states.get(PAUSE_SELECT).state == "30"
    assert events == []


async def test_select_returns_to_active_when_pause_ends(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    _set_status(aioclient_mock, json=_disabled(300))
    await _select(hass, "5")
    assert hass.states.get(PAUSE_SELECT).state == "5"

    _set_status(aioclient_mock, json=ENABLED)
    await _poll(hass)

    assert hass.states.get(PAUSE_SELECT).state == "active"
    assert hass.states.get(SWITCH).state == STATE_ON


async def test_select_active_resumes_blocking(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    _set_status(aioclient_mock, json=_disabled(3600))
    await _select(hass, "60")

    _set_status(aioclient_mock, json=ENABLED)
    await _select(hass, "active")

    assert _calls(aioclient_mock, "/api/blocking/enable") == [{}]
    assert hass.states.get(PAUSE_SELECT).state == "active"
    assert hass.states.get(SWITCH).state == STATE_ON


async def test_select_is_unknown_for_a_pause_started_elsewhere(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock, json=_disabled(777))
    assert hass.states.get(PAUSE_SELECT).state == STATE_UNKNOWN

    _set_status(aioclient_mock, json=ENABLED)
    await _poll(hass)
    assert hass.states.get(PAUSE_SELECT).state == "active"

    _set_status(aioclient_mock, json=_disabled(90, ["iot"]))
    await hass.services.async_call(
        DOMAIN, "disable_blocking", {"duration": {"seconds": 90}}, blocking=True
    )
    assert hass.states.get(PAUSE_SELECT).state == STATE_UNKNOWN


async def test_select_rejects_unknown_option(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)

    for option in ("99999", "0", "-5", "5; rm -rf /", ""):
        with pytest.raises(ServiceValidationError):
            await _select(hass, option)

    assert hass.states.get(PAUSE_SELECT).state == "active"
    assert _calls(aioclient_mock, "/api/blocking/disable") == []


async def test_select_reports_failure(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    aioclient_mock.clear_requests()
    aioclient_mock.get(STATUS_URL, json=ENABLED)
    aioclient_mock.get(DISABLE_URL, exc=aiohttp.ClientConnectionError())

    with pytest.raises(HomeAssistantError):
        await _select(hass, "15")

    assert hass.states.get(PAUSE_SELECT).state == "active"


async def test_switch_on_enables(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock, json=_disabled(120))
    assert hass.states.get(SWITCH).state == STATE_OFF
    assert hass.states.get(RESUMES_AT).state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)

    _set_status(aioclient_mock, json=ENABLED)
    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: SWITCH}, blocking=True
    )

    assert _calls(aioclient_mock, "/api/blocking/enable") == [{}]
    assert hass.states.get(SWITCH).state == STATE_ON
    assert hass.states.get(RESUMES_AT).state == STATE_UNKNOWN


async def test_switch_reports_failure(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    aioclient_mock.clear_requests()
    aioclient_mock.get(STATUS_URL, json=ENABLED)
    aioclient_mock.get(DISABLE_URL, status=500, text="boom")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_off", {ATTR_ENTITY_ID: SWITCH}, blocking=True
        )

    assert hass.states.get(SWITCH).state == STATE_ON


# --- Buttons ----------------------------------------------------------------


async def test_buttons(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    _set_status(aioclient_mock, json=ENABLED)

    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: REFRESH_BUTTON}, blocking=True
    )
    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: FLUSH_BUTTON}, blocking=True
    )

    posted = [
        url.path
        for method, url, _data, _headers in aioclient_mock.mock_calls
        if method.upper() == "POST"
    ]
    assert posted == ["/api/lists/refresh", "/api/cache/flush"]


async def test_button_reports_failure(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    aioclient_mock.clear_requests()
    aioclient_mock.get(STATUS_URL, json=ENABLED)
    aioclient_mock.post(REFRESH_URL, exc=aiohttp.ClientConnectionError())

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {ATTR_ENTITY_ID: REFRESH_BUTTON}, blocking=True
        )


# --- Polling ----------------------------------------------------------------


async def test_outage_is_visible_and_recovers(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)

    _set_status(aioclient_mock, exc=aiohttp.ClientConnectionError())
    await _poll(hass)

    assert hass.states.get(CONNECTION).state == STATE_OFF
    assert hass.states.get(SWITCH).state == STATE_UNAVAILABLE
    assert hass.states.get(REFRESH_BUTTON).state == STATE_UNAVAILABLE
    assert hass.states.get(PAUSE_SELECT).state == STATE_UNAVAILABLE

    _set_status(aioclient_mock, json=ENABLED)
    await _poll(hass)

    assert hass.states.get(CONNECTION).state == STATE_ON
    assert hass.states.get(SWITCH).state == STATE_ON


async def test_malformed_status_counts_as_outage(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)

    _set_status(aioclient_mock, json={"enabled": "<script>alert(1)</script>"})
    await _poll(hass)

    assert hass.states.get(CONNECTION).state == STATE_OFF
    assert hass.states.get(SWITCH).state == STATE_UNAVAILABLE


async def test_external_disable_fires_event(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _setup(hass, aioclient_mock)
    events = async_capture_events(hass, EVENT_BLOCKING_DISABLED_EXTERNALLY)

    _set_status(aioclient_mock, json=_disabled(0, ["default", "iot"]))
    await _poll(hass)

    assert hass.states.get(SWITCH).state == STATE_OFF
    assert len(events) == 1
    assert events[0].data == {
        "config_entry_id": entry.entry_id,
        "disabled_groups": ["default", "iot"],
    }

    # No repeat while nothing changes.
    await _poll(hass)
    assert len(events) == 1

    # A further group disabled behind our back is reported again.
    _set_status(aioclient_mock, json=_disabled(0, ["default", "iot", "guest"]))
    await _poll(hass)
    assert len(events) == 2


async def test_own_disable_and_timer_expiry_fire_no_event(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    events = async_capture_events(hass, EVENT_BLOCKING_DISABLED_EXTERNALLY)

    _set_status(aioclient_mock, json=_disabled(300))
    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: SWITCH}, blocking=True
    )
    await _poll(hass)

    _set_status(aioclient_mock, json=ENABLED)
    await _poll(hass)

    assert hass.states.get(SWITCH).state == STATE_ON
    assert events == []


async def test_already_disabled_at_startup_fires_no_event(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    events = async_capture_events(hass, EVENT_BLOCKING_DISABLED_EXTERNALLY)

    await _setup(hass, aioclient_mock, json=_disabled(0))
    await _poll(hass)

    assert events == []


async def test_resume_time_does_not_jitter(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, aioclient_mock, json=_disabled(600))
    first = hass.states.get(RESUMES_AT).state
    freezer.tick(UPDATE_INTERVAL)

    # 30 s later Blocky reports 2 s of drift: still the same deadline.
    _set_status(aioclient_mock, json=_disabled(572))
    await _poll(hass)

    assert hass.states.get(RESUMES_AT).state == first


# --- Service action ---------------------------------------------------------


async def test_service_disable_blocking(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)
    events = async_capture_events(hass, EVENT_BLOCKING_DISABLED_EXTERNALLY)
    _set_status(aioclient_mock, json=_disabled(90, ["iot"]))

    await hass.services.async_call(
        DOMAIN,
        "disable_blocking",
        {"duration": {"minutes": 1, "seconds": 30}, "groups": ["iot"]},
        blocking=True,
    )

    assert _calls(aioclient_mock, "/api/blocking/disable") == [
        {"duration": "90s", "groups": "iot"}
    ]
    assert events == []


@pytest.mark.parametrize(
    "data",
    [
        {"duration": {"hours": 25}},
        {"duration": {"seconds": 0}},
        {"duration": {"minutes": 5}, "groups": ["default,quarantine"]},
        {"duration": {"minutes": 5}, "groups": ["bad\nname"]},
        {"duration": {"minutes": 5}, "config_entry_id": "does-not-exist"},
    ],
)
async def test_service_rejects_bad_input(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, data: dict[str, Any]
) -> None:
    await _setup(hass, aioclient_mock)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "disable_blocking", data, blocking=True)

    assert _calls(aioclient_mock, "/api/blocking/disable") == []


async def test_service_requires_duration(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await _setup(hass, aioclient_mock)

    with pytest.raises(Exception, match="duration"):
        await hass.services.async_call(DOMAIN, "disable_blocking", {}, blocking=True)

    assert _calls(aioclient_mock, "/api/blocking/disable") == []


async def test_service_is_admin_only(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_read_only_user: MockUser,
) -> None:
    await _setup(hass, aioclient_mock)

    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            "disable_blocking",
            {"duration": {"minutes": 5}},
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )

    assert _calls(aioclient_mock, "/api/blocking/disable") == []


async def test_service_needs_entry_id_with_two_instances(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    first = await _setup(hass, aioclient_mock)
    other_url = "http://blocky2.example:4000"
    aioclient_mock.get(f"{other_url}/api/blocking/status", json=ENABLED)
    aioclient_mock.get(f"{other_url}/api/blocking/disable", text="")
    second = MockConfigEntry(domain=DOMAIN, data={CONF_URL: other_url})
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "disable_blocking", {"duration": {"minutes": 5}}, blocking=True
        )

    await hass.services.async_call(
        DOMAIN,
        "disable_blocking",
        {"duration": {"minutes": 5}, "config_entry_id": second.entry_id},
        blocking=True,
    )

    hosts = [
        url.host
        for _method, url, _data, _headers in aioclient_mock.mock_calls
        if url.path == "/api/blocking/disable"
    ]
    assert hosts == ["blocky2.example"]
    assert first.state is ConfigEntryState.LOADED
