"""Tests for the query log card: its commands, its file and its texts."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import timedelta
from typing import Any

import pytest
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import (
    ClientSessionGenerator,
    WebSocketGenerator,
)
from sqlalchemy.engine import URL

from custom_components.ha_blocky import db
from custom_components.ha_blocky.const import DOMAIN, MAX_LOG_ROWS
from custom_components.ha_blocky.db import CATEGORIES
from custom_components.ha_blocky.frontend import (
    CARD_PATH,
    CARD_URL,
    FRONTEND_DIR,
    PANEL_URL,
)

from .test_db import add_rows
from .test_lists import LIST_OPTIONS
from .test_stats import DB_OPTIONS, log_row

BASE_URL = "http://blocky.example:4000"
STATUS_URL = f"{BASE_URL}/api/blocking/status"
ENABLED = {"enabled": True, "disabledGroups": [], "autoEnableInSec": 0}

MODULES = sorted(FRONTEND_DIR.glob("*.js"))
SOURCES = {path.name: path.read_text(encoding="utf-8") for path in MODULES}
# Everything the browser runs, as one text.
SOURCE = "\n".join(SOURCES.values())
# The same without the style sheet texts.
CODE = SOURCE
for _style in (
    "ha-blocky-style.js",
    "ha-blocky-style-dashboard.js",
    "ha-blocky-style-more.js",
):
    CODE = CODE.replace(SOURCES[_style], "")
I18N_HELP = SOURCES["ha-blocky-i18n-help.js"]
# The only addresses in the code: the three blocklist sources of the Help tab,
# shown as text, never loaded.
BLOCKLIST_URLS = (
    "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
    "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/wildcard/pro.txt",
    "https://big.oisd.nl/domainswild",
)
I18N = SOURCES["ha-blocky-i18n.js"]


async def _setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    assert await async_setup_component(hass, "http", {})
    aioclient_mock.get(STATUS_URL, json=ENABLED)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_URL: BASE_URL},
        options={**DB_OPTIONS, **LIST_OPTIONS} if options is None else options,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _command(ws: Any, message_id: int, /, **message: Any) -> dict[str, Any]:
    await ws.send_json({"id": message_id, **message})
    return await ws.receive_json()


# --- The file ---------------------------------------------------------------


def test_frontend_directory_holds_only_the_intended_modules() -> None:
    """The whole directory is served: nothing else may sit in it."""
    assert sorted(path.name for path in FRONTEND_DIR.iterdir()) == [
        "ha-blocky-actions.js",
        "ha-blocky-card.js",
        "ha-blocky-chart.js",
        "ha-blocky-controls.js",
        "ha-blocky-dashboard-data.js",
        "ha-blocky-dashboard.js",
        "ha-blocky-dom.js",
        "ha-blocky-format.js",
        "ha-blocky-group.js",
        "ha-blocky-help.js",
        "ha-blocky-i18n-help.js",
        "ha-blocky-i18n.js",
        "ha-blocky-known.js",
        "ha-blocky-log.js",
        "ha-blocky-overview.js",
        "ha-blocky-panel.js",
        "ha-blocky-popover.js",
        "ha-blocky-prefs.js",
        "ha-blocky-requests.js",
        "ha-blocky-settings-options.js",
        "ha-blocky-settings.js",
        "ha-blocky-style-dashboard.js",
        "ha-blocky-style-more.js",
        "ha-blocky-style.js",
        "ha-blocky-switch.js",
        "ha-blocky-toplist.js",
    ]
    assert CARD_PATH in MODULES


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_module_never_interprets_data_as_markup(name: str) -> None:
    """Log values and device names are attacker-controlled; only text sinks."""
    source = SOURCES[name]
    for sink in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
        'setAttribute("on',
        "srcdoc",
        "javascript:",
    ):
        assert sink not in source, (name, sink)


def test_modules_use_text_content() -> None:
    assert "textContent" in SOURCES["ha-blocky-dom.js"]


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_module_loads_nothing_from_outside(name: str) -> None:
    # The one address in the code is the SVG namespace: an identifier that
    # createElementNS needs, never a place anything is loaded from.
    source = SOURCES[name].replace("http://www.w3.org/2000/svg", "")
    if name == "ha-blocky-i18n-help.js":
        # Exactly the three blocklist sources, and nothing else with an address.
        for url in BLOCKLIST_URLS:
            assert source.count(url) == 1, url
            source = source.replace(url, "")
    assert not re.search(r"https?://", source)
    for loader in ("import(", "importScripts", "fetch(", "XMLHttpRequest", "<script"):
        assert loader not in source, (name, loader)


def test_imports_are_relative_and_resolve_to_existing_modules() -> None:
    found = 0
    for name, source in SOURCES.items():
        for statement in re.findall(r"^\s*import\b[^;]*;", source, flags=re.MULTILINE):
            match = re.search(r"""["']([^"']+)["']\s*;""", statement)
            assert match is not None, (name, statement)
            target = match.group(1)
            assert re.fullmatch(r"\./[\w-]+\.js", target), (name, target)
            assert (FRONTEND_DIR / target).is_file(), (name, target)
            found += 1
    assert found >= 30
    # Nothing is imported with a path that leaves the directory.
    assert "../" not in SOURCE


def test_card_modules_stay_small() -> None:
    assert len(SOURCES["ha-blocky-card.js"].splitlines()) <= 300
    assert all(len(source.splitlines()) <= 400 for source in SOURCES.values())


def _texts(language: str) -> dict[str, str]:
    """The texts of a language: the card's table plus the Help tab's."""
    merged: dict[str, str] = {}
    for source in (I18N, I18N_HELP):
        match = re.search(
            rf"/\* i18n:{language} \*/\s*export const \w+ = (\{{.*?\}});\s*"
            r"/\* i18n:end \*/",
            source,
            flags=re.DOTALL,
        )
        assert match is not None, language
        table = json.loads(match.group(1))
        assert not set(table) & set(merged)
        merged.update(table)
    return merged


def test_card_texts_default_to_english_and_translations_mirror_it() -> None:
    english = _texts("en")
    ukrainian = _texts("uk")

    assert english and all(text.strip() for text in english.values())
    assert set(ukrainian) == set(english)
    assert all(text.strip() for text in ukrainian.values())
    # Every key the code asks for exists in English.
    used = set(re.findall(r'\b_?t\("(\w+)"\)', CODE))
    used |= {f"status_{status}" for status in ("all", "blocked", "allowed")}
    used |= {f"hours_{hours}" for hours in (1, 6, 24, 168, 720)}
    used |= {f"tab_{tab}" for tab in ("dashboard", "log", "requests")}
    used |= {f"dash_period_{period}" for period in ("today", "24h", "7d", "30d")}
    used |= {f"cat_{kind}" for kind in CATEGORIES}
    used |= {f"help_tab_{tab}" for tab in ("dashboard", "log", "requests", "settings")}
    used |= {f"tab_{tab}" for tab in ("settings", "help")}
    for name in ("delay", "pause", "name", "nodb", "sidebar"):
        used |= {f"help_faq_{name}_q", f"help_faq_{name}_a"}
    codes = (
        "invalid_color invalid_rows out_of_range invalid_type invalid_list_name "
        "duplicate_list_name too_many_lists unknown_list_name list_in_use "
        "nothing_to_change entry_not_found not_ready"
    )
    used |= {f"serr_{code}" for code in codes.split()}
    used |= set(re.findall(r'"(dash_\w+)"', CODE))
    used |= set(re.findall(r'label: "(\w+)"', CODE))
    used |= set(re.findall(r'_section\("(\w+)"', CODE))
    used |= set(re.findall(r'_domainTable\("(\w+)"', CODE))
    used |= set(re.findall(r'"(ov_\w+|known_\w+|req_none)"', CODE))
    used |= {f"act_{name}" for name in ("approve", "reject", "block", "dismiss")}
    assert used <= set(english)
    assert "TEXT_EN[key]" in I18N


def test_requests_tab_uses_the_commands_and_only_known_actions() -> None:
    requests_js = SOURCES["ha-blocky-requests.js"]
    actions_js = SOURCES["ha-blocky-actions.js"]
    assert "`${DOMAIN}/requests`" in requests_js
    assert "`${DOMAIN}/resolve_request`" in requests_js
    assert '"set_client_phase"' in requests_js
    assert "callService(DOMAIN" in requests_js
    # Dismiss is a rejection; the card sends nothing but these three actions.
    assert 'import { ACTION_OF } from "./ha-blocky-actions.js";' in requests_js
    assert re.search(r"ACTION_OF = \{[^}]*dismiss: \"reject\"", actions_js)
    actions = re.search(r"ACTION_OF = \{([^}]*)\}", actions_js)
    assert actions is not None
    assert set(re.findall(r'"(\w+)"', actions.group(1))) == {
        "approve",
        "reject",
        "block",
    }
    assert 'PHASES = ["learning", "locked"]' in requests_js
    # Buttons of a request in flight are disabled.
    assert "button.disabled = busy" in requests_js


def test_names_come_from_the_server_only() -> None:
    """The browser no longer looks at device trackers."""
    assert "device_tracker" not in SOURCE
    assert "attributes.ip" not in SOURCE
    assert "client_name" in SOURCES["ha-blocky-log.js"]
    assert "client_name" in SOURCES["ha-blocky-requests.js"]
    dom = SOURCES["ha-blocky-dom.js"]
    assert "`${DOMAIN}/set_client_name`" in dom
    assert "maxlength: MAX_NAME_LENGTH" in dom
    assert "MAX_NAME_LENGTH = 64" in dom
    assert '"Escape"' in dom
    assert '"Enter"' in dom


def test_cards_never_build_style_or_links_from_data() -> None:
    for sink in ('setAttribute("style"', "href", "src=", "location", "cssText"):
        assert sink not in CODE, sink
    # The only inline style is the position of the popover: two numbers.
    for name, source in SOURCES.items():
        if name != "ha-blocky-dom.js":
            assert ".style" not in source.replace("ha-blocky-style", ""), name
    dom = SOURCES["ha-blocky-dom.js"]
    assert re.findall(r"\.style\.\w+ = [^;]+;", dom) == [
        ".style.left = `${Math.round(Number(left) || 0)}px`;",
        ".style.top = `${Math.round(Number(top) || 0)}px`;",
    ]
    assert dom.count(".style") == 2


def test_icons_come_from_fixed_tables_only() -> None:
    """No icon name is ever built from data: every name is in one table."""
    actions_js = SOURCES["ha-blocky-actions.js"]
    for name, source in SOURCES.items():
        if name != "ha-blocky-actions.js":
            assert "mdi:" not in source, name
    tables = re.findall(r"export const (\w*ICONS) = \{", actions_js)
    assert tables == ["ICONS", "STATUS_ICONS", "UI_ICONS"]
    names = re.findall(r'"(mdi:[a-z0-9-]+)"', actions_js)
    assert names and len(names) == actions_js.count("mdi:")
    assert 'allow: "mdi:shield-check"' in actions_js
    assert 'block: "mdi:shield-off"' in actions_js
    # The only place an icon is assigned looks the name up in a table.
    assert re.findall(r"\.icon = ([^;]+);", CODE) == ["table[key]"]
    assert "hasOwnProperty.call(table, key)" in actions_js
    assert 'document.createElement("ha-icon")' in actions_js
    # The hover text and the label are the card's own texts.
    assert "host.t(labelKey)" in actions_js
    assert '"aria-label": label' in actions_js


def test_icon_buttons_are_keyboard_buttons() -> None:
    actions_js = SOURCES["ha-blocky-actions.js"]
    assert 'role: "button"' in actions_js
    assert 'tabindex: "0"' in actions_js
    assert 'title: label, "aria-label": label' in actions_js
    assert 'event.key === "Enter" || event.key === " "' in actions_js
    assert "event.preventDefault()" in actions_js
    assert '"aria-disabled"' in actions_js
    # Everything that acts is an icon button or a plain button, never a link.
    assert "<a" not in CODE


def test_log_tab_offers_one_icon_action_per_row() -> None:
    log_js = SOURCES["ha-blocky-log.js"]
    assert 'const BLOCKABLE = ["RESOLVED", "CACHED"];' in log_js
    assert 'if (row.blocked === true) return "allow";' in log_js
    assert 'LIST_TYPE_OF = { allow: "allow", block: "deny" }' in log_js
    assert "iconButton(this._host, action, action" in log_js
    assert "this._picker.open(type, row.domain, {" in log_js
    # The list picker is shared, not copied.
    assert "new ListPicker(" in log_js
    assert "callService" not in log_js
    assert "_openPanel" not in SOURCE
    # The old text buttons are gone.
    assert 'text: this._t("allow")' not in log_js
    assert 'text: this._t("block")' not in log_js


def test_log_tab_groups_repeats_by_default_and_keeps_it_in_memory() -> None:
    log_js = SOURCES["ha-blocky-log.js"]
    assert "this._group = true;" in log_js
    assert 'attrs: { type: "checkbox" }' in log_js
    assert 'this._t("group_repeats")' in log_js
    assert "groupRows(this._sortedRows(), this._group)" in log_js
    assert chr(0xD7) + "${count}" in log_js
    # Only the dashboard's period and rows are remembered (ha-blocky-format.js).
    for sink in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
        for name, source in SOURCES.items():
            if name != "ha-blocky-format.js":
                assert sink not in source, (name, sink)
    assert "sessionStorage" not in SOURCE and "indexedDB" not in SOURCE
    assert "document.cookie" not in SOURCE
    assert 'readChoice("' not in log_js


def test_grouping_function_is_pure() -> None:
    group_js = SOURCES["ha-blocky-group.js"]
    assert "import " not in group_js
    assert "document" not in group_js and "window" not in group_js
    assert "export function groupRows(rows, enabled)" in group_js
    for field in ("client", "domain", "query_type", "response_type"):
        assert f"row.{field}," in group_js, field


GROUPING_SCRIPT = """
const row = (id, client, domain, type, status) =>
  ({ id, client, domain, query_type: type, response_type: status, time: `t${id}` });
const rows = [
  row(5, "a", "x.com", "A", "RESOLVED"),
  row(4, "a", "x.com", "A", "RESOLVED"),
  row(3, "a", "x.com", "AAAA", "RESOLVED"),
  row(2, "b", "x.com", "A", "RESOLVED"),
  row(1, "a", "x.com", "A", "BLOCKED"),
  row(0, "a", "x.com", "A", "RESOLVED"),
];
const shape = (entries) => entries.map((entry) => [entry.row.id, entry.count]);
const frozen = JSON.stringify(rows);
const out = {
  grouped: shape(groupRows(rows, true)),
  reversed: shape(groupRows(rows.slice().reverse(), true)),
  off: shape(groupRows(rows, false)),
  empty: groupRows([], true).length,
  untouched: JSON.stringify(rows) === frozen,
};
console.log(JSON.stringify(out));
"""


def test_grouping_function_merges_repeats_and_keeps_the_latest_row() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        [node, "--input-type=module"],
        input=SOURCES["ha-blocky-group.js"] + GROUPING_SCRIPT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    # Same client, domain, type and status: one line, the latest row, x3.
    assert out["grouped"] == [[5, 3], [3, 1], [2, 1], [1, 1]]
    # A group stands where its first row stood, but still shows its latest row.
    assert out["reversed"] == [[5, 3], [1, 1], [2, 1], [3, 1]]
    assert out["off"] == [[5, 1], [4, 1], [3, 1], [2, 1], [1, 1], [0, 1]]
    assert out["empty"] == 0
    assert out["untouched"] is True


def test_narrow_card_shows_two_lines_per_entry_with_the_same_dom() -> None:
    style = SOURCES["ha-blocky-style.js"]
    assert "container-type: inline-size" in style
    brief = style[style.index("@container") :]
    assert 'grid-template-areas: "client domain domain" "time status actions"' in brief
    assert "table.log td.type, table.log td.ms { display: none; }" in brief
    assert "table.log td.status .statustext { display: none; }" in brief
    assert "ha-icon.statusicon { display: inline-flex; }" in brief
    # One render path: the cells carry the classes the style addresses.
    log_js = SOURCES["ha-blocky-log.js"]
    for name in ("time", "domain", "type", "status", "actions"):
        assert f'className: "{name}"' in log_js, name
    assert 'className: "num ms"' in log_js
    assert 'className: "log"' in log_js
    assert "matchMedia" not in CODE


def test_overview_card_is_registered_through_the_card_module() -> None:
    card = SOURCES["ha-blocky-card.js"]
    overview = SOURCES["ha-blocky-overview.js"]
    assert 'import "./ha-blocky-overview.js";' in card
    assert 'customElements.define("ha-blocky-overview-card"' in overview
    assert 'type: "ha-blocky-overview-card"' in overview
    assert "`${DOMAIN}/overview`" in overview
    assert "`${DOMAIN}/resolve_request`" in overview
    # Same checks and the same shared pieces as the query log card.
    assert "ListPicker" in overview and "clientCell(this" in overview
    assert "ACTION_OF" in overview
    assert "hass.user.is_admin" in overview
    assert 'err.code === "no_query_log"' in overview
    # The timer respects visibility, an open panel and a name being typed.
    assert 'document.visibilityState === "visible"' in overview
    assert "this._picker.busy" in overview and "this.isEditing()" in overview
    # Block on a top domain, Allow on a top blocked domain.
    assert '"ov_top_domains", data.domains, "block"' in overview
    assert '"ov_top_blocked", data.blocked, "allow"' in overview


def test_known_domains_load_on_demand_and_block_only_learning_clients() -> None:
    known = SOURCES["ha-blocky-known.js"]
    assert "`${DOMAIN}/known_domains`" in known
    assert "`${DOMAIN}/block_known`" in known
    assert 'const LEARNING = "learning";' in known
    assert "const canBlock = state.mode === LEARNING;" in known
    assert "if (canBlock) {" in known
    assert "known_readonly" in known
    # Loaded on the first expansion only.
    assert "state.open && !state.loaded" in known
    requests_js = SOURCES["ha-blocky-requests.js"]
    assert "new KnownView(host)" in requests_js
    assert "this._known.update(result.tracked)" in requests_js


def test_texts_exist_in_both_languages() -> None:
    english = _texts("en")
    ukrainian = _texts("uk")
    keys = {f"act_{name}" for name in ("approve", "reject", "block", "dismiss")}
    keys |= {f"phase_{phase}" for phase in ("learning", "locked")}
    keys |= {"tab_log", "tab_requests", "req_none", "req_error", "req_phases"}
    keys |= {"req_client", "req_zone", "req_domain", "req_age", "unit_min", "unit_h"}
    keys |= {"client_edit", "client_name_placeholder", "group_repeats"}
    keys |= {"ov_title", "ov_top_domains", "ov_top_blocked", "ov_top_clients"}
    keys |= {"ov_requests", "ov_none", "ov_error"}
    keys |= {"known_title", "known_error", "known_none", "known_readonly"}
    keys |= {"known_blocked"}
    assert keys <= set(english)
    assert keys <= set(ukrainian)


def test_panel_hosts_the_card() -> None:
    panel = SOURCES["ha-blocky-panel.js"]
    assert 'import "./ha-blocky-card.js";' in panel
    assert 'customElements.define("ha-blocky-panel"' in panel
    assert 'document.createElement("ha-blocky-card")' in panel
    assert "this._card.hass = hass" in panel


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.name)
def test_card_javascript_is_valid(path: Any) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    # The modules are ES modules; they are checked as such, through stdin.
    result = subprocess.run(
        [node, "--input-type=module", "--check"],
        input=path.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# --- Serving ----------------------------------------------------------------


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_card_file_is_served(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    await _setup(hass, aioclient_mock, {})
    client = await hass_client_no_auth()

    response = await client.get(CARD_URL)

    assert response.status == 200
    assert "javascript" in response.content_type
    assert "ha-blocky-card" in await response.text()


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_every_module_is_served_and_nothing_else(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    await _setup(hass, aioclient_mock, {})
    client = await hass_client_no_auth()

    for path in MODULES:
        response = await client.get(f"/{DOMAIN}/{path.name}")
        assert response.status == 200, path.name
        assert "javascript" in response.content_type
        assert await response.text() == SOURCES[path.name]
    assert (await client.get(PANEL_URL)).status == 200
    # No directory listing, no other files, no way out of the directory.
    for url in (
        f"/{DOMAIN}",
        f"/{DOMAIN}/",
        f"/{DOMAIN}/missing.js",
        f"/{DOMAIN}/ha-blocky-card.js.map",
        f"/{DOMAIN}/../const.py",
        f"/{DOMAIN}/%2e%2e/const.py",
        f"/{DOMAIN}/..%2fconst.py",
    ):
        response = await client.get(url)
        assert response.status in (400, 403, 404), url
        assert "DOMAIN" not in await response.text(), url


# --- Commands ---------------------------------------------------------------


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_config_command(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    entry = await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=f"{DOMAIN}/config")
    blocking = er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"{entry.entry_id}_blocking"
    )
    assert blocking is not None and blocking.startswith("switch.")

    assert response["success"]
    assert response["result"] == {
        "entries": [
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "has_query_log": True,
                "blocking_entity": blocking,
                "lists": [
                    {"name": "allow_default", "type": "allow", "exact_only": False},
                    {"name": "deny_default", "type": "deny", "exact_only": False},
                    {"name": "allow_quarantine", "type": "allow", "exact_only": True},
                ],
                "zones": [],
            }
        ]
    }
    # Nothing secret is exposed to the card.
    dumped = json.dumps(response)
    assert entry.runtime_data.lists.token not in dumped
    assert DB_OPTIONS["db_password"] not in dumped
    assert "blocky.example" not in dumped


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_query_log_filters_and_pages(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    add_rows(
        log_url,
        [
            log_row("a.example.com", client="192.0.2.10"),
            log_row(
                "ads.tracker.example", client="192.0.2.10", response_type="BLOCKED"
            ),
            log_row("b.example.com", client="192.0.2.11", duration_ms=42),
            log_row("rebind.example", client="192.0.2.11", response_type="REBIND"),
            log_row("old.example.com", age=timedelta(hours=30)),
        ],
    )
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    kind = f"{DOMAIN}/query_log"

    everything = (await _command(client, 1, type=kind))["result"]
    assert [row["domain"] for row in everything["rows"]] == [
        "rebind.example",
        "b.example.com",
        "ads.tracker.example",
        "a.example.com",
    ]
    assert everything["has_more"] is False
    newest = everything["rows"][0]
    assert newest["blocked"] is True
    assert newest["response_type"] == "REBIND"
    assert newest["time"].endswith("+00:00")
    assert everything["rows"][1]["duration_ms"] == 42

    blocked = (await _command(client, 2, type=kind, status="blocked"))["result"]
    assert [row["domain"] for row in blocked["rows"]] == [
        "rebind.example",
        "ads.tracker.example",
    ]
    allowed = (await _command(client, 3, type=kind, status="allowed"))["result"]
    assert [row["domain"] for row in allowed["rows"]] == [
        "b.example.com",
        "a.example.com",
    ]
    by_client = (await _command(client, 4, type=kind, client="192.0.2.11"))["result"]
    assert len(by_client["rows"]) == 2
    by_domain = (await _command(client, 5, type=kind, domain="example.com"))["result"]
    assert [row["domain"] for row in by_domain["rows"]] == [
        "b.example.com",
        "a.example.com",
    ]
    week = (await _command(client, 6, type=kind, hours=168))["result"]
    assert len(week["rows"]) == 5

    first = (await _command(client, 7, type=kind, limit=2))["result"]
    assert [row["domain"] for row in first["rows"]] == [
        "rebind.example",
        "b.example.com",
    ]
    assert first["has_more"] is True
    second = (
        await _command(client, 8, type=kind, limit=2, before_id=first["next_before_id"])
    )["result"]
    assert [row["domain"] for row in second["rows"]] == [
        "ads.tracker.example",
        "a.example.com",
    ]


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_query_log_search_is_literal(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
) -> None:
    add_rows(
        log_url,
        [
            log_row("plain.example.com"),
            log_row("with_underscore.example"),
            log_row("with%percent.example"),
            log_row("x'; DROP TABLE log_entries; --"),
            log_row("<img src=x onerror=alert(1)>\x00"),
        ],
    )
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    kind = f"{DOMAIN}/query_log"

    async def search(message_id: int, text: str) -> list[str]:
        response = await _command(client, message_id, type=kind, domain=text)
        assert response["success"], response
        return [row["domain"] for row in response["result"]["rows"]]

    # LIKE wildcards in the search text match themselves, not "anything".
    assert await search(1, "%") == ["with%percent.example"]
    assert await search(2, "_") == [
        "x'; DROP TABLE log_entries; --",
        "with_underscore.example",
    ]
    assert await search(3, "' OR '1'='1") == []
    assert await search(4, "DROP TABLE") == ["x'; DROP TABLE log_entries; --"]
    # Hostile names come back as cleaned plain text and the table survives.
    assert await search(5, "onerror") == ["<img src=x onerror=alert(1)>"]
    assert len(await search(6, "example")) == 3


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize(
    "message",
    [
        {"hours": 0},
        {"hours": 100000},
        {"hours": "24"},
        {"limit": 0},
        {"limit": MAX_LOG_ROWS + 1},
        {"status": "everything"},
        {"before_id": 0},
        {"before_id": -5},
        {"domain": "x" * 254},
        {"domain": "bad\x00name"},
        {"client": "y" * 65},
        {"client": ["192.0.2.1"]},
        {"unexpected": True},
    ],
)
async def test_query_log_rejects_bad_requests(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    message: dict[str, Any],
) -> None:
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=f"{DOMAIN}/query_log", **message)

    assert response["success"] is False
    assert response["error"]["code"] == "invalid_format"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_query_log_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    log_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _setup(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    kind = f"{DOMAIN}/query_log"

    unknown = await _command(client, 1, type=kind, entry_id="nope")
    assert unknown["error"]["code"] == "entry_not_found"

    def broken(self: db.QueryLogDatabase, **kwargs: Any) -> list[dict[str, Any]]:
        raise db.BlockyDbError("OperationalError: secret detail")

    monkeypatch.setattr(db.QueryLogDatabase, "query_log", broken)
    failed = await _command(client, 2, type=kind)
    assert failed["error"]["code"] == "database_error"
    assert "secret detail" not in json.dumps(failed)


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_query_log_without_a_database(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
) -> None:
    await _setup(hass, aioclient_mock, {})
    client = await hass_ws_client(hass)

    config = await _command(client, 1, type=f"{DOMAIN}/config")
    assert config["result"]["entries"][0]["has_query_log"] is False
    response = await _command(client, 2, type=f"{DOMAIN}/query_log")
    assert response["error"]["code"] == "no_query_log"


@pytest.mark.usefixtures("enable_custom_integrations")
@pytest.mark.parametrize("kind", ["config", "query_log"])
async def test_commands_are_admin_only(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    hass_admin_user: MockUser,
    log_url: URL,
    kind: str,
) -> None:
    await _setup(hass, aioclient_mock)
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)

    response = await _command(client, 1, type=f"{DOMAIN}/{kind}")

    assert response["success"] is False
    assert response["error"]["code"] == "unauthorized"


# --- The dashboard tab ------------------------------------------------------


def test_dashboard_tab_reads_one_command_and_drives_the_switch_entity() -> None:
    dashboard = SOURCES["ha-blocky-dashboard.js"]
    switch = SOURCES["ha-blocky-switch.js"]
    assert "`${DOMAIN}/dashboard`" in dashboard
    assert dashboard.count("callWS(") == 1
    assert "callService" not in dashboard
    # The switch: the entity id comes from the server and must look like one.
    assert r"SWITCH_ID = /^switch\.[a-z0-9_]+$/" in switch
    assert "entry.blocking_entity" in switch
    assert 'callService("switch", state === "on" ? "turn_off" : "turn_on"' in switch
    assert 'role: "switch"' in switch
    assert switch.count("callService(") == 1
    # The period and the rows are validated against the allowed values.
    assert 'readChoice("period", PERIODS, "24h")' in dashboard
    # The rows: this browser's choice, else the server default, else 10.
    assert 'readChoice("rows", ROW_CHOICES, prefs.rows || 10)' in dashboard
    fmt = SOURCES["ha-blocky-format.js"]
    assert 'PERIODS = ["today", "24h", "7d", "30d"]' in fmt
    assert "ROW_CHOICES = [5, 10, 20]" in fmt
    assert "import " not in fmt


def test_tabs_show_an_icon_and_a_title_and_the_dashboard_comes_first() -> None:
    card = SOURCES["ha-blocky-card.js"]
    style = SOURCES["ha-blocky-style.js"]
    assert 'const TABS = ["dashboard", "log", "requests", "settings", "help"];' in card
    assert 'this._tab = "dashboard";' in card
    assert 'role: "tab", title: label, "aria-label": label' in card
    assert 'haIcon(UI_ICONS, `tab_${id}`, "tabicon")' in card
    assert 'className: "tablabel"' in card
    brief = style[style.index("${DASHBOARD_STYLE}") :]
    assert ".tablabel { display: none; }" in brief
    assert "@container (max-width: 560px)" in brief
    # The dashboard is reloaded by a timer that stops while the tab is hidden
    # or the dashboard is being edited.
    dashboard = SOURCES["ha-blocky-dashboard.js"]
    assert 'document.visibilityState === "visible"' in dashboard
    assert "!this._host.editMode" in dashboard
    assert "set editMode(value)" in card


def test_query_colours_are_custom_properties_used_everywhere() -> None:
    style = SOURCES["ha-blocky-style.js"]
    dash_style = SOURCES["ha-blocky-style-dashboard.js"]
    kinds = ("resolved", "cached", "local", "blocked", "other")
    for kind in kinds:
        # Defined once, with a default; mapped to one class that everything uses.
        assert f'{kind}: "#' in SOURCES["ha-blocky-format.js"], kind
        assert f".c-{kind} {{ --c: var(--hb-color-{kind}); }}" in dash_style, kind
        assert f"--hb-color-{kind}" not in CODE, kind
    # The defaults are one table in ha-blocky-format.js that the style sheet
    # turns into the custom properties; there is no other colour value.
    assert "--hb-color-${kind}: ${DEFAULT_COLORS[kind]};" in style
    values = re.findall(r"#[0-9a-fA-F]{3,8}\b", CODE)
    table = re.findall(r'"(#[0-9a-f]{6})",', SOURCES["ha-blocky-format.js"])
    assert len(table) == 5
    assert set(values) == set(table)
    assert not re.findall(r"rgba?\(|hsla?\(", CODE)
    # Segments, swatches and tiles take their colour from `--c`, never a value.
    for rule in (
        "svg.bars .seg, svg.mbar .seg { fill: var(--c); }",
        "background: var(--c);",
    ):
        assert rule in dash_style
    chart = SOURCES["ha-blocky-chart.js"] + SOURCES["ha-blocky-toplist.js"]
    assert "`seg c-${" in chart
    assert "`sw c-${" in chart


def test_popover_is_one_accessible_element_that_closes_properly() -> None:
    popover = SOURCES["ha-blocky-popover.js"]
    assert 'role: "tooltip"' in popover
    assert '"pointerdown"' in popover and '"keydown"' in popover
    assert 'event.key === "Escape"' in popover
    assert '"scroll"' in popover
    assert "aria-describedby" in popover
    # Hover for a mouse, a tap for touch, Enter or Space for the keyboard.
    assert 'event.pointerType === "mouse"' in popover
    assert 'event.key !== "Enter" && event.key !== " "' in popover
    # The chart bars and the list rows can be focused.
    assert "tabindex: 0" in SOURCES["ha-blocky-chart.js"]
    assert 'tabindex: "0"' in SOURCES["ha-blocky-toplist.js"]
    assert "new Popover(" in SOURCES["ha-blocky-dashboard.js"]


def test_actions_are_coloured_by_effect_and_the_row_flashes() -> None:
    actions_js = SOURCES["ha-blocky-actions.js"]
    style = SOURCES["ha-blocky-style.js"]
    assert 'allow: "good"' in actions_js and 'block: "bad"' in actions_js
    assert "fx-${effect}" in actions_js
    for rule in (
        ".iconbtn.fx-good, .iconbtn.fx-good:hover { color: var(--hb-good); }",
        ".iconbtn.fx-bad, .iconbtn.fx-bad:hover { color: var(--hb-bad); }",
        "tr.flash-good, .knownrow.flash-good",
        "tr.flash-bad, .knownrow.flash-bad",
        "@media (prefers-reduced-motion: reduce)",
    ):
        assert rule in style, rule
    # Every list that offers an action lights the row up.
    for name in ("log", "overview", "requests", "known"):
        assert "flasher." in SOURCES[f"ha-blocky-{name}.js"], name


NODE_SCRIPT = """
import {
  CATEGORIES, PERIODS, ROW_CHOICES, categoryCounts, choose, compact, labelStep,
  percent, readChoice, stackBars, writeChoice,
} from "./ha-blocky-format.js";
import { normalize } from "./ha-blocky-dashboard-data.js";
import { effectOf, flasher } from "./ha-blocky-actions.js";

const out = {};
out.compact = [compact(25100, "en"), compact(999, "en"), compact(1200000, "en"),
  compact(-5, "en"), compact("x", "en"), compact(undefined, "en")];
out.percent = [percent(1, 3), percent(5, 5), percent(0, 10), percent(1, 0),
  percent("a", 10)];
out.step = [labelStep(24), labelStep(7), labelStep(30), labelStep(1)];

const counts = (values) => categoryCounts(values);
const stack = stackBars([
  { categories: counts({ resolved: 50, blocked: 50 }) },
  { categories: counts({ cached: 25 }) },
  { categories: counts({}) },
]);
out.stack = {
  peak: stack.peak,
  totals: stack.bars.map((bar) => bar.total),
  slots: stack.bars.map((bar) => bar.slot),
  first: stack.bars[0].segments,
  second: stack.bars[1].segments,
  third: stack.bars[2].segments,
};
out.empty = stackBars([]).bars.length;

const data = {};
globalThis.window = {
  localStorage: {
    getItem: (key) => (key in data ? data[key] : null),
    setItem: (key, value) => { data[key] = String(value); },
  },
};
const choices = [];
choices.push(readChoice("rows", ROW_CHOICES, 10), readChoice("period", PERIODS, "24h"));
writeChoice("rows", 20);
writeChoice("period", "7d");
choices.push(readChoice("rows", ROW_CHOICES, 10), readChoice("period", PERIODS, "24h"));
data["ha_blocky.rows"] = "999";
data["ha_blocky.period"] = "<script>alert(1)</script>";
choices.push(readChoice("rows", ROW_CHOICES, 10), readChoice("period", PERIODS, "24h"));
data["ha_blocky.rows"] = "10.0";
data["ha_blocky.period"] = "constructor";
choices.push(readChoice("rows", ROW_CHOICES, 20), readChoice("period", PERIODS, "30d"));
globalThis.window = { localStorage: {
  getItem: () => { throw new Error("blocked"); },
  setItem: () => { throw new Error("blocked"); },
} };
choices.push(readChoice("rows", ROW_CHOICES, 5),
  readChoice("period", PERIODS, "today"));
writeChoice("rows", 5);
delete globalThis.window;
choices.push(readChoice("rows", ROW_CHOICES, 20));
out.choices = choices;
out.choose = [choose(10, ROW_CHOICES, 5), choose(null, PERIODS, "30d"),
  choose("7d", PERIODS, "x")];

const hostile = normalize({
  state: "ok",
  totals: {
    queries: "12", unique_domains: -4, avg_duration_ms: null,
    categories: {
      resolved: "7", blocked: -1, cached: "NaN", evil: 99, __proto__: { x: 1 },
    },
  },
  buckets: {
    unit: "<b>",
    items: [
      { start: "2026-11-10T10:00:00+00:00", categories: { resolved: 3 } },
      { start: "not a date", categories: { resolved: 5 } },
      null,
    ],
  },
  top_clients: [
    {
      address: "192.0.2.1", client_name: "N".repeat(500), count: "3",
      categories: { blocked: 3 },
    },
    { address: 5, count: 1 },
    { name: "wrong key", count: 1 },
    null,
  ],
  top_domains: [{
    name: "x".repeat(600), count: Infinity, last_seen: 5, reason: "r".repeat(500),
  }],
  top_blocked: "not a list",
  meta: {
    version: "v".repeat(100), blocky_version: null,
    generated_at: "2026-11-10T12:00:00+00:00",
  },
});
out.hostile = {
  queries: hostile.queries, unique: hostile.unique, average: hostile.average ?? null,
  categories: hostile.categories, unit: hostile.unit,
  buckets: hostile.buckets.length,
  clients: hostile.clients.map((item) => [
    item.name, item.client_name.length, item.count, item.categories.blocked,
  ]),
  domainLength: hostile.domains[0].name.length, domainCount: hostile.domains[0].count,
  lastSeen: hostile.domains[0].last_seen, reason: hostile.domains[0].reason.length,
  blocked: hostile.blocked.length, version: hostile.version.length,
  blockyVersion: hostile.blockyVersion, generated: hostile.generated.getTime(),
  keys: Object.keys(hostile.categories),
};

out.effects = [
  "allow", "approve", "block", "reject", "dismiss", "constructor", "toString", "",
  undefined,
].map((name) => effectOf(name));
const timers = [];
globalThis.setTimeout = (fn, ms) => { timers.push([fn, ms]); };
const log = [];
const node = { classList: {
  add: (name) => log.push(["add", name]),
  remove: (name) => log.push(["remove", name]),
} };
flasher.mark("row:1", "allow", node);
flasher.mark("row:2", "constructor", node);
flasher.apply("row:2", node);
flasher.apply("row:3", node);
flasher.mark("row:4", "block");
flasher.apply("row:4", node);
out.flash = { log, timers: timers.map(([, ms]) => ms > 0 && ms <= 1000) };
timers.forEach(([fn]) => fn());
out.flash.after = log.filter((entry) => entry[0] === "remove").map((entry) => entry[1]);
console.log(JSON.stringify(out));
"""


def test_dashboard_helpers_clean_and_validate(tmp_path: Any) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    for path in MODULES:
        (tmp_path / path.name).write_text(SOURCES[path.name], encoding="utf-8")
    # The modules are ES modules; a package.json says so for the .js files.
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    script = tmp_path / "check.mjs"
    script.write_text(NODE_SCRIPT, encoding="utf-8")

    result = subprocess.run(
        [node, str(script)], capture_output=True, text=True, check=False, cwd=tmp_path
    )

    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["compact"] == ["25.1K", "999", "1.2M", "0", "0", "0"]
    assert out["percent"] == ["33.3%", "100%", "0%", "0%", "0%"]
    assert out["step"] == [4, 2, 5, 1]
    assert out["stack"]["peak"] == 100
    assert out["stack"]["totals"] == [100, 25, 0]
    assert out["stack"]["slots"] == [0, 10, 20]
    assert out["stack"]["first"] == [
        {"category": "resolved", "y": 50, "height": 50},
        {"category": "blocked", "y": 0, "height": 50},
    ]
    assert out["stack"]["second"] == [{"category": "cached", "y": 75, "height": 25}]
    assert out["stack"]["third"] == []
    assert out["empty"] == 0
    # Valid choices are kept; anything else falls back, also without storage.
    assert out["choices"] == [10, "24h", 20, "7d", 10, "24h", 20, "30d", 5, "today", 20]
    assert out["choose"] == [10, "30d", "7d"]

    hostile = out["hostile"]
    assert (hostile["queries"], hostile["unique"], hostile["average"]) == (12, 0, None)
    assert hostile["categories"] == {
        "resolved": 7,
        "cached": 0,
        "local": 0,
        "blocked": 0,
        "other": 0,
    }
    assert hostile["keys"] == ["resolved", "cached", "local", "blocked", "other"]
    assert hostile["unit"] == "hour"
    assert hostile["buckets"] == 1
    assert hostile["clients"] == [["192.0.2.1", 64, 3, 3]]
    assert (hostile["domainLength"], hostile["domainCount"]) == (253, 0)
    assert (hostile["lastSeen"], hostile["reason"]) == ("", 120)
    assert hostile["blocked"] == 0
    assert hostile["version"] == 32
    assert hostile["blockyVersion"] == ""

    assert out["effects"] == ["good", "good", "bad", "bad", "bad", "", "", "", ""]
    flash = out["flash"]
    # Two classes were added at once; each is removed when its timer fires.
    assert flash["log"] == [
        ["add", "flash-good"],
        ["add", "flash-bad"],
        ["remove", "flash-good"],
        ["remove", "flash-bad"],
    ]
    assert flash["timers"] == [True, True]
    assert flash["after"] == ["flash-good", "flash-bad"]


# --- Settings, Live mode and Help --------------------------------------------


def test_settings_tab_writes_through_one_command_with_the_whitelisted_keys() -> None:
    from custom_components.ha_blocky.settings import OPERATIONAL_KEYS

    settings_js = SOURCES["ha-blocky-settings.js"]
    options_js = SOURCES["ha-blocky-settings-options.js"]
    assert "`${DOMAIN}/set_settings`" in settings_js
    assert "`${DOMAIN}/settings`" in settings_js
    # The card offers exactly the options the server accepts, no others.
    in_card = set(re.findall(r'\["(\w+)", "set_\w+"', options_js))
    assert in_card == set(OPERATIONAL_KEYS)
    # The error text and the field label come from the card's own tables.
    assert "FIELD_LABELS" in settings_js
    assert "serr_${code}" in settings_js
    # A colour is validated before it is used, and a preview is not saved.
    assert "validColor(this._inputs[category].value)" in settings_js
    assert 'attrs: { type: "color"' in settings_js


def test_colours_reach_the_page_through_one_validated_style_element() -> None:
    prefs_js = SOURCES["ha-blocky-prefs.js"]
    fmt = SOURCES["ha-blocky-format.js"]
    # One element per card; its text is composed by colorCss from validated
    # values and fixed names only, and written with textContent.
    assert prefs_js.count('document.createElement("style")') == 1
    assert prefs_js.count("textContent") == 1
    assert "this.element.textContent = colorCss(this._preview || prefs.colors);" in (
        prefs_js
    )
    assert "const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;" in fmt
    assert "`--hb-color-${category}: ${color};`" in fmt
    assert "validColor(colors && colors[category])" in fmt
    # Both cards use it; nothing else creates a style element.
    assert "new ColorStyle(root)" in SOURCES["ha-blocky-card.js"]
    assert "new ColorStyle(root)" in SOURCES["ha-blocky-overview.js"]
    for name, source in SOURCES.items():
        if name not in ("ha-blocky-prefs.js",):
            assert 'createElement("style")' not in source, name


def test_live_mode_is_bounded_and_adds_no_command() -> None:
    log_js = SOURCES["ha-blocky-log.js"]
    assert "const LIVE_INTERVAL_MS = 3000;" in log_js
    assert "const LIVE_MAX_MS = 10 * 60 * 1000;" in log_js
    assert 'document.visibilityState === "visible"' in log_js
    assert "if (Date.now() >= this._liveUntil)" in log_js
    # Leaving the tab or the page ends it.
    assert (
        "setActive(active)" in log_js and "if (!active) this.setLive(false);" in log_js
    )
    assert 'this._log.setActive(tab === "log");' in SOURCES["ha-blocky-card.js"]
    assert "this.setLive(false);" in log_js
    # It reads the existing command only, and its new rows light up neutrally.
    assert log_js.count("callWS(") == 1
    assert "`${DOMAIN}/query_log`" in log_js
    assert 'flasher.mark(`log:${row.id}`, "new")' in log_js
    assert 'new: "info"' in SOURCES["ha-blocky-actions.js"]
    assert "live_hint" in log_js
    style = SOURCES["ha-blocky-style-more.js"]
    assert "button.live.on .livedot { background: var(--hb-good); animation:" in style
    assert "button.live.on .livedot { animation: none; }" in style


def test_help_tab_shows_three_blocklists_as_text_with_a_guarded_copy() -> None:
    help_js = SOURCES["ha-blocky-help.js"]
    data = I18N_HELP
    assert re.findall(r'url: "(https://[^"]+)"', data) == list(BLOCKLIST_URLS)
    assert data.count("name:") == 3
    # Plain text, never a link and never fetched.
    for sink in ("<a", "href", "fetch(", "window.open", "target="):
        assert sink not in help_js and sink not in data, sink
    assert 'className: "srcurl"' in help_js
    assert "text: source.url" in help_js
    assert 'typeof clipboard.writeText !== "function"' in help_js
    assert "navigator.clipboard" in help_js
    assert "await clipboard.writeText(text)" in help_js
    # Sections are built with DOM calls.
    assert 'el("details"' in help_js and 'el("summary"' in help_js
    assert "innerHTML" not in help_js


NODE_SCRIPT_PREFS = """
import { colorCss, hasChoice, validColor } from "./ha-blocky-format.js";
import { prefs, setPrefs } from "./ha-blocky-prefs.js";

const out = {};
out.valid = [
  "#aabbcc", "#AABBCC", "#aabbcc\\n", " #aabbcc", "#aabbc", "#aabbccd", "#aabbcg",
  "red", "#fff", "#aabbcc;}", 5, null, undefined, ["#aabbcc"],
].map((value) => validColor(value));
out.css = [
  colorCss({ blocked: "#AABBCC" }),
  colorCss({ blocked: "#fff}body{display:none", cached: "url(x)" }),
  colorCss({ evil: "#000000" }),
  colorCss({ resolved: "#010203", local: "#040506", other: "#070809" }),
  colorCss(undefined),
  colorCss(null),
  colorCss({}),
];
const seen = [];
const listener = () => seen.push(JSON.stringify([prefs.colors, prefs.rows]));
import { onPrefs, offPrefs } from "./ha-blocky-prefs.js";
onPrefs(listener);
setPrefs({
  colors: { blocked: "#AABBCC", cached: "red; x", resolved: "#12345" },
  rows: 7,
});
setPrefs({ colors: { local: "#0a0b0c", evil: "#000000" }, rows: 20 });
setPrefs("not an object");
offPrefs(listener);
setPrefs({ colors: { other: "#010101" }, rows: 5 });
out.seen = seen;
out.after = [prefs.colors, prefs.rows];

const data = {};
const read = (key) => (key in data ? data[key] : null);
globalThis.window = { localStorage: { getItem: read } };
const rows = [5, 10, 20];
const flags = [hasChoice("rows", rows)];
data["ha_blocky.rows"] = "20";
flags.push(hasChoice("rows", rows));
data["ha_blocky.rows"] = "99";
flags.push(hasChoice("rows", rows));
const broken = () => { throw new Error("blocked"); };
globalThis.window = { localStorage: { getItem: broken } };
flags.push(hasChoice("rows", rows));
out.flags = flags;
console.log(JSON.stringify(out));
"""


def test_colour_text_and_preferences_only_ever_hold_validated_values(
    tmp_path: Any,
) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    for path in MODULES:
        (tmp_path / path.name).write_text(SOURCES[path.name], encoding="utf-8")
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    script = tmp_path / "check.mjs"
    script.write_text(NODE_SCRIPT_PREFS, encoding="utf-8")

    result = subprocess.run(
        [node, str(script)], capture_output=True, text=True, check=False, cwd=tmp_path
    )

    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["valid"] == [
        "#aabbcc",
        "#aabbcc",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
    ]
    assert out["css"] == [
        ":host { --hb-color-blocked: #aabbcc; }",
        "",
        "",
        ":host { --hb-color-resolved: #010203; --hb-color-local: #040506; "
        "--hb-color-other: #070809; }",
        "",
        "",
        "",
    ]
    # Only validated colours and allowed rows get in; others are dropped.
    assert out["seen"] == [
        '[{"blocked":"#aabbcc"},null]',
        '[{"local":"#0a0b0c"},20]',
        "[{},null]",
    ]
    assert out["after"] == [{"other": "#010101"}, 5]
    assert out["flags"] == [False, True, False, False]
