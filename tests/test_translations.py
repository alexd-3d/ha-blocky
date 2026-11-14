"""Every text the integration shows must exist in English.

English is the default language; other languages are additions and must
cover exactly the same keys.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from sqlalchemy.engine import URL

from custom_components.ha_blocky.const import DOMAIN

from .test_lists import LIST_OPTIONS
from .test_stats import DB_OPTIONS

COMPONENT = Path(__file__).resolve().parent.parent / "custom_components" / "ha_blocky"
TRANSLATIONS = COMPONENT / "translations"


def _load(language: str) -> dict[str, Any]:
    return json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))


def _flatten(node: Any, prefix: str = "") -> dict[str, str]:
    if isinstance(node, dict):
        flat: dict[str, str] = {}
        for key, value in node.items():
            flat.update(_flatten(value, f"{prefix}.{key}" if prefix else key))
        return flat
    return {prefix: node}


ENGLISH = _load("en")
OTHER_LANGUAGES = sorted(
    path.stem for path in TRANSLATIONS.glob("*.json") if path.stem != "en"
)


def test_english_exists_and_has_no_empty_text() -> None:
    flat = _flatten(ENGLISH)

    assert flat
    for key, text in flat.items():
        assert isinstance(text, str) and text.strip(), key


@pytest.mark.parametrize("language", OTHER_LANGUAGES)
def test_other_languages_cover_exactly_the_english_keys(language: str) -> None:
    other = _flatten(_load(language))

    assert set(other) == set(_flatten(ENGLISH))
    for key, text in other.items():
        assert isinstance(text, str) and text.strip(), key


@pytest.mark.parametrize("language", ["en", *OTHER_LANGUAGES])
def test_placeholders_match_english(language: str) -> None:
    placeholder = re.compile(r"\{(\w+)\}")
    english = _flatten(ENGLISH)

    for key, text in _flatten(_load(language)).items():
        assert sorted(placeholder.findall(text)) == sorted(
            placeholder.findall(english[key])
        ), key


def test_every_flow_step_error_and_abort_has_english_text() -> None:
    source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")

    steps = set(re.findall(r'step_id="(\w+)"', source))
    assert steps == {"user", "init", "database", "list_networks"}
    known_steps = set(ENGLISH["config"]["step"]) | set(ENGLISH["options"]["step"])
    # Every step has text, and no text is left for a step that is gone.
    assert steps == known_steps

    menu = re.search(r"menu_options=\[([^\]]+)\]", source)
    assert menu is not None
    menu_options = set(re.findall(r'"(\w+)"', menu.group(1)))
    assert menu_options == set(ENGLISH["options"]["step"]["init"]["menu_options"])
    assert menu_options <= set(ENGLISH["options"]["step"])

    errors = set(re.findall(r'errors\[[^\]]+\] = "(\w+)"', source))
    known_errors = set(ENGLISH["config"]["error"]) | set(ENGLISH["options"]["error"])
    assert errors

    # Home Assistant itself aborts a duplicate entry; nothing else aborts.
    assert not re.findall(r"async_abort\(reason=", source)
    assert set(ENGLISH["config"]["abort"]) == {"already_configured"}
    assert "abort" not in ENGLISH["options"]
    # Every error text is used by a form, and every error of a form has text.
    assert errors == known_errors


def test_no_selector_text_is_left_over() -> None:
    assert "selector" not in ENGLISH
    source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    assert "translation_key" not in source


def test_exceptions_match_the_refusal_codes_exactly() -> None:
    from custom_components.ha_blocky.requests import ERROR_MESSAGES

    assert set(ENGLISH["exceptions"]) == set(ERROR_MESSAGES) | {"no_query_log"}
    for code, text in ERROR_MESSAGES.items():
        assert ENGLISH["exceptions"][code]["message"] == text, code


def test_every_data_description_belongs_to_a_form_field() -> None:
    for flow, step in (
        ("config", "user"),
        ("options", "database"),
        ("options", "list_networks"),
    ):
        texts = ENGLISH[flow]["step"][step]
        assert set(texts.get("data_description", {})) <= set(texts["data"]), step


def test_every_form_field_has_an_english_label() -> None:
    from custom_components.ha_blocky import config_flow

    schemas = {
        ("config", "user"): config_flow.STEP_USER_SCHEMA,
        ("options", "database"): config_flow.STEP_DATABASE_SCHEMA,
        ("options", "list_networks"): config_flow.STEP_LIST_NETWORKS_SCHEMA,
    }
    for (flow, step), schema in schemas.items():
        labels = ENGLISH[flow]["step"][step]["data"]
        assert {str(key) for key in schema.schema} == set(labels), (flow, step)


def test_every_action_and_field_has_english_text() -> None:
    services = yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))

    assert set(services) == set(ENGLISH["services"])
    for name, definition in services.items():
        texts = ENGLISH["services"][name]
        assert texts["name"] and texts["description"], name
        assert set(definition.get("fields", {})) == set(texts.get("fields", {})), name
        for field, field_texts in texts.get("fields", {}).items():
            assert field_texts["name"] and field_texts["description"], (name, field)


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_every_entity_has_an_english_name(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, log_url: URL
) -> None:
    assert await async_setup_component(hass, "http", {})
    base_url = "http://blocky.example:4000"
    aioclient_mock.get(
        f"{base_url}/api/blocking/status",
        json={"enabled": True, "disabledGroups": [], "autoEnableInSec": 0},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_URL: base_url},
        options={**DB_OPTIONS, **LIST_OPTIONS},
        minor_version=2,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(entities) == 6 + 15 + 4 + 6 + 2
    for entity in entities:
        assert entity.translation_key, entity.entity_id
        assert entity.translation_key in ENGLISH["entity"][entity.domain], (
            entity.entity_id
        )
        state = hass.states.get(entity.entity_id)
        assert state is not None
        name = state.attributes["friendly_name"]
        assert name.startswith("HA-Blocky ") and len(name) > len("HA-Blocky "), name

    # No entity text is left over: each text belongs to an entity that exists.
    for domain, texts in ENGLISH["entity"].items():
        keys = {e.translation_key for e in entities if e.domain == domain}
        assert set(texts) == keys, domain

    # Every state of the select has a label too.
    select_states = ENGLISH["entity"]["select"]["pause_blocking"]["state"]
    options = hass.states.get("select.ha_blocky_pause_blocking").attributes["options"]
    assert set(options) == set(select_states)
