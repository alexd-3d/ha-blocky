# ruff: noqa: E501
"""Tests of the card parts added with the query log client filters (BLO-018).

The pure functions run in Node (skipped when it is missing); the rest is
checked on the source of the modules, like the other card tests.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

import pytest

from .test_card import SOURCES

LOGIC = SOURCES["ha-blocky-log-logic.js"]
FORMAT = SOURCES["ha-blocky-format.js"]


def _run(source: str, script: str) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        [node, "--input-type=module"],
        input=source + script,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_logic_module_is_pure() -> None:
    assert "import " not in LOGIC
    assert "document" not in LOGIC and "window" not in LOGIC


LOGIC_SCRIPT = """
const lists = [
  { name: "allow_default", type: "allow", levels: ["standard", "restricted"] },
  { name: "deny_default", type: "deny", levels: ["standard", "restricted"] },
  { name: "restricted_deny", type: "deny", levels: ["restricted"] },
  { name: "lockdown_allow", type: "allow", levels: ["lockdown"] },
];
const row = (id, domain, level) => ({ id, domain, level });
const rows = [
  row(1, "x.example.com", "lockdown"),
  row(2, "x.example.com", "standard"),
  row(3, "X.Example.com", "lockdown"),
  row(4, "y.example.com", "lockdown"),
  row(5, "x.example.com", undefined),
  row(6, "x.example.com", "restricted"),
  row(7, "x.example.com", "bogus"),
];
const pl = (...args) => preferredList(...args) ?? null;
const out = {
  ipOk: ["", "192.0.2.1", "2001:DB8::1", "db8:", " 192.0.2.1 ", "a".repeat(45)].map(ipFilterOk),
  ipBad: ["%", "_", "1.2.3.x", "a".repeat(46), "1 2", null, 5].map(ipFilterOk),
  levels: {
    lockdown: listLevels(lists, "lockdown_allow"),
    unknown: listLevels(lists, "nope"),
    notAList: listLevels(undefined, "x"),
    hostile: listLevels([{ name: "a", levels: ["lockdown", "<b>", 3] }], "a"),
  },
  preferred: {
    allowLockdown: pl(lists, "allow", "lockdown"),
    denyLockdown: pl(lists, "deny", "lockdown"),
    allowStandard: pl(lists, "allow", "standard"),
    denyRestricted: pl(lists, "deny", "restricted"),
    denyStandard: pl(lists, "deny", "standard"),
    allowUnfiltered: pl(lists, "allow", "unfiltered"),
    noLevel: pl(lists, "allow", undefined),
    noLists: pl(undefined, "allow", "lockdown"),
  },
  // Allow on the Lockdown list: only rows of Lockdown clients, same domain.
  affectedLockdown: affectedRowIds(rows, "x.example.com", ["lockdown"]),
  affectedDefault: affectedRowIds(rows, "x.example.com", ["standard", "restricted"]),
  affectedNone: affectedRowIds(rows, "x.example.com", []),
  affectedBadDomain: [affectedRowIds(rows, "", ["lockdown"]), affectedRowIds(rows, 5, ["lockdown"])],
  affectedNoRows: affectedRowIds(undefined, "x.example.com", ["lockdown"]),
  levelOfRow: [levelOfRow({ level: "lockdown" }), levelOfRow({}), levelOfRow({ level: "x" }), levelOfRow(null)],
};
console.log(JSON.stringify(out));
"""


def test_logic_functions() -> None:
    out = _run(LOGIC, LOGIC_SCRIPT)
    assert out["ipOk"] == [True] * 6
    assert out["ipBad"] == [False] * 7
    assert out["levels"] == {
        "lockdown": ["lockdown"],
        "unknown": [],
        "notAList": [],
        "hostile": ["lockdown"],
    }
    # The list that actually changes the client's level comes first, and the
    # most specific one wins over the shared Always lists.
    assert out["preferred"] == {
        "allowLockdown": "lockdown_allow",
        "denyLockdown": None,
        "allowStandard": "allow_default",
        "denyRestricted": "restricted_deny",
        "denyStandard": "deny_default",
        "allowUnfiltered": None,
        "noLevel": None,
        "noLists": None,
    }
    # Only the rows of the affected levels, of that domain (any case).
    assert out["affectedLockdown"] == [1, 3]
    # A row without a (known) level is a Standard client's.
    assert out["affectedDefault"] == [2, 5, 6, 7]
    assert out["affectedNone"] == []
    assert out["affectedBadDomain"] == [[], []]
    assert out["affectedNoRows"] == []
    assert out["levelOfRow"] == ["lockdown", "standard", "standard", "standard"]


STACK_SCRIPT = """
const empty = () => Object.fromEntries(CATEGORIES.map((kind) => [kind, 0]));
const full = (n) => ({ ...empty(), [CATEGORIES[0]]: n });
// "Today" at 13:00: thirteen hours with data, eleven still to come.
const buckets = Array.from({ length: 24 }, (_, hour) => ({
  categories: hour < 13 ? full(hour + 1) : empty(),
}));
const { bars } = stackBars(buckets);
console.log(JSON.stringify({
  count: bars.length,
  slots: bars.map((bar) => bar.slot),
  empty: bars.slice(13).every((bar) => bar.total === 0 && bar.segments.length === 0),
  width: SLOT,
  inside: bars.every((bar) => bar.x >= bar.slot && bar.x + bar.width <= bar.slot + SLOT),
}));
"""


def test_an_empty_future_hour_keeps_its_slot() -> None:
    out = _run(FORMAT, STACK_SCRIPT)
    assert out["count"] == 24
    assert out["slots"] == [index * out["width"] for index in range(24)]
    assert out["empty"] is True
    assert out["inside"] is True


# --- Source checks -----------------------------------------------------------


def test_the_ignore_type_toggle_is_remembered_and_needs_grouping() -> None:
    filters = SOURCES["ha-blocky-log-filters.js"]
    assert 'readChoice("log_ignore_type", IGNORE_CHOICES, "on")' in filters
    assert 'writeChoice("log_ignore_type"' in filters
    assert "this._ignoreButton.disabled = !this._groupBox.checked;" in filters
    assert "get ignoreType()" in filters
    # A crossed-out T from an existing icon set; no new asset.
    assert 'log_ignore_type: "mdi:format-title"' in SOURCES["ha-blocky-actions.js"]
    assert ".ibtn.ignoretype.on::after" in SOURCES["ha-blocky-style-more.js"]
    # The type cell shows the combined types.
    assert 'types.join(", ")' in SOURCES["ha-blocky-log.js"]


def test_the_filters_are_ip_and_name_and_the_old_client_field_is_gone() -> None:
    filters = SOURCES["ha-blocky-log-filters.js"]
    log = SOURCES["ha-blocky-log.js"]
    assert 'search(45, "search_ip")' in filters
    assert 'search(64, "search_name")' in filters
    assert "message.ip = this._filters.ip" in log
    assert "message.name = this._filters.name" in log
    assert "message.client" not in log
    assert "ipFilterOk(this._filters.ip)" in log


def test_a_client_of_the_dashboard_opens_the_log() -> None:
    toplist = SOURCES["ha-blocky-toplist.js"]
    assert "isClient && typeof onOpen" in toplist
    assert 'event.key !== "Enter" && event.key !== " "' in toplist
    assert "this._host.openLog(address)" in SOURCES["ha-blocky-dashboard.js"]
    view = SOURCES["ha-blocky-card-view.js"]
    assert "openLog(address)" in view
    assert 'this._selectTab("log");' in view
    assert "this._log.showClient(address);" in view
    assert "setAddress(address)" in SOURCES["ha-blocky-log-filters.js"]


def test_the_picker_preselects_the_list_of_the_clients_level_and_reports_it() -> None:
    actions = SOURCES["ha-blocky-actions.js"]
    log = SOURCES["ha-blocky-log.js"]
    assert "open(type, domain, context, level)" in actions
    assert "preferredList(" in actions
    assert "this._onDone(context, chosen)" in actions
    assert "levelOfRow(row))" in log
    # The cascade: every visible row of the domain at an affected level.
    assert "affectedRowIds(this._rows, context.domain" in log
    assert "listLevels(lists, listName)" in log


def test_highlights_fade_by_animation_and_respect_reduced_motion() -> None:
    style = SOURCES["ha-blocky-style.js"]
    assert "animation: hbfade-good 1s ease-out" in style
    assert "@keyframes hbfade-bad" in style
    assert "@media (prefers-reduced-motion: reduce)" in style
    assert "transition: background-color 0.9s" not in style
    assert "tr.flash-info { animation: hbfade-info 1s ease-out; }" in style
    # The old on/off rule of the live rows is gone.
    assert "tr.flash-info { background-color" not in SOURCES["ha-blocky-style-more.js"]


def test_the_settings_tab_stays_put_while_the_entry_reloads() -> None:
    settings = SOURCES["ha-blocky-settings.js"]
    view = SOURCES["ha-blocky-card-view.js"]
    assert "if (this._reloading) return;" in settings
    assert "await this._host.reloadEntry(true);" in settings
    assert "async reloadEntry(wait = false)" in view
    assert 'this._tab === "settings" && !wait' in view


def test_the_default_base_groups_warning_is_shown_from_the_server_flag() -> None:
    protection = SOURCES["ha-blocky-protection.js"]
    assert "result.base_groups_saved !== false" in protection
    assert 'text: t("prot_base_default_warning")' in protection


def _rule(style: str, selector: str) -> str:
    """The declarations of the first rule that starts with `selector {`."""
    start = style.index(f"{selector} {{")
    return style[start : style.index("}", start)]


def test_the_log_row_has_the_cells_of_a_two_line_mobile_row() -> None:
    log = SOURCES["ha-blocky-log.js"]
    style = SOURCES["ha-blocky-style.js"]
    # One render path: the same cells on a wide and on a narrow card.
    assert 'className: "time" }, [' in log
    assert 'className: "when"' in log and 'className: "count"' in log
    assert "`statustext badge c-${kind}`" in log
    assert "statusicon" not in log
    narrow = style[style.index("@container (max-width: 760px)") :]
    # The table needs about 14rem for the domain: the log drops to two lines at 760 px,
    # the rest of the card (tab labels, requests) at 560 px.
    assert narrow.index("table.log thead") < narrow.index(
        "@container (max-width: 560px)"
    )
    assert "th.vh {" in style and "width: 100%; max-width: 0" in style
    # Line 1: client (name, or the address) and the time; line 2: badge and
    # domain; the action icon over both lines.
    assert (
        'grid-template-areas: "client client time actions" "status domain domain actions"'
        in narrow
    )
    for area in ("client", "time", "status", "domain", "actions"):
        assert (
            f"table.log td.{area} {{" in narrow
            or f"table.log td.{area} {{ grid-area: {area}" in narrow
        ), area
    # The badge column has a fixed width: the domains line up across rows.
    assert "grid-template-columns: 6.5rem minmax(0, 1fr) auto 2.5rem;" in narrow
    # The domain is cut with an ellipsis, its whole text is its title.
    assert "td.domain {" in style and "text-overflow: ellipsis" in style
    assert 'attrs: { title: row.domain || "" }' in log
    # The repeat count is lighter and smaller than the time.
    count = _rule(style, "td.time .count")
    assert "color: var(--secondary-text-color)" in count
    assert "font-size: var(--hb-fs-label)" in count


def test_the_heading_is_the_name_of_the_integration() -> None:
    view = SOURCES["ha-blocky-card-view.js"]
    assert 'const PRODUCT_NAME = "HA-Blocky";' in view
    assert "this._config.title || PRODUCT_NAME" in view
    assert 'this.t("title")' not in view


def test_a_badge_and_an_action_button_look_different() -> None:
    tabs = SOURCES["ha-blocky-style-tabs.js"]
    style = SOURCES["ha-blocky-style.js"]
    badge = _rule(tabs, ".badge")
    # A badge only tells: tinted, no border, no pointer, not clickable.
    assert "border: 0" in badge and "cursor: default" in badge
    assert "pointer-events: none" in badge
    assert "var(--c)" in badge
    assert ".badge:hover" not in tabs + style
    # A button acts: outlined, a pointer, hover and focus states.
    button = _rule(style, "button")
    assert "cursor: pointer" in button and "border: 1px solid" in button
    assert "button:hover:not(:disabled)" in style and "button:focus-visible" in style
    # The two never share a class: the log builds the badge, the action
    # buttons are buttons (`abtn`) or icon buttons.
    log = SOURCES["ha-blocky-log.js"]
    assert "badge" in log and "abtn" not in log
    assert "className: `abtn fx-${effectOf(name)}`" in SOURCES["ha-blocky-requests.js"]
    assert 'className: "abtn primary"' in SOURCES["ha-blocky-actions.js"]
    for name, source in SOURCES.items():
        if name.startswith("ha-blocky-style"):
            continue
        for line in source.splitlines():
            assert not ("badge" in line and "abtn" in line), (name, line)


def test_sizes_come_from_the_tokens_of_the_host() -> None:
    style = SOURCES["ha-blocky-style.js"]
    for token in (
        "--hb-s2: 8px",
        "--hb-s4: 16px",
        "--hb-fs-body: 14px",
        "--hb-fs-label: 12px",
    ):
        assert token in style, token
    # No text or background colour that a theme variable provides.
    for name in (
        "ha-blocky-style.js",
        "ha-blocky-style-tabs.js",
        "ha-blocky-style-more.js",
        "ha-blocky-style-dashboard.js",
    ):
        source = SOURCES[name]
        for forbidden in ("color: #", "background: #", "color: white", "color: black"):
            assert forbidden not in source, (name, forbidden)


def test_a_block_or_allow_reloads_the_log_and_keeps_its_length() -> None:
    log = SOURCES["ha-blocky-log.js"]
    assert "this.reloadCurrent();" in log
    assert "async load(reset, keep)" in log
    assert "limit: keep || this._host.config.page_size," in log
    assert "Math.min(shown, MAX_ROWS)" in log
    # The highlight is marked before the reload and picked up by the rebuilt row.
    assert log.index("flasher.mark(`log:${id}`") < log.index("this.reloadCurrent();")
    assert "flasher.apply(`log:${row.id}`, line)" in log


def test_the_saved_message_does_not_outlive_the_reload() -> None:
    settings = SOURCES["ha-blocky-settings.js"]
    assert "back = await this._host.reloadEntry(true);" in settings
    after = settings[settings.index("back = await") :]
    assert (
        'this._say(this._opsMessage, back ? "set_saved" : "set_load_error", !back);'
        in after
    )
    assert 'setTimeout(() => this._say(this._opsMessage, "", false), SAVED_MS)' in after
    # Any new message cancels the pending clear.
    assert (
        "if (message === this._opsMessage) clearTimeout(this._clearTimer);" in settings
    )


def test_settings_groups_are_stacked_with_a_gap() -> None:
    assert 'className: "stack"' in SOURCES["ha-blocky-protection.js"]
    assert 'className: "stack"' in SOURCES["ha-blocky-apply.js"]
    assert (
        ".stack { display: grid; gap: var(--hb-s4);"
        in SOURCES["ha-blocky-style-tabs.js"]
    )
    assert 'className: "plain vh"' in SOURCES["ha-blocky-log.js"]
