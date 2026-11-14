/*
 * The parts of the Help tab about protection levels: a table that compares the
 * four levels, concrete use cases, and a short walk-through of how a change
 * gets applied. Every text is the card's own (looked up by key); nothing is
 * taken from the server. `t(key)` is the card's text lookup.
 */

import { el } from "./ha-blocky-dom.js";

const LEVEL_NAMES = ["unfiltered", "standard", "restricted", "lockdown"];
const COLUMNS = ["blocked", "rules", "asked", "new"];
const USE_CASES = ["broken", "family", "child", "iot"];
const STEPS = ["1", "2", "3", "4", "5", "6"];

// The comparison table: one row per level, one column per question.
export function levelTable(t) {
  const head = el("tr", {}, [
    el("th", { text: t("help_col_level"), className: "plain" }),
    ...COLUMNS.map((column) => el("th", { text: t(`help_col_${column}`), className: "plain" })),
  ]);
  const body = el(
    "tbody",
    {},
    LEVEL_NAMES.map((level) =>
      el("tr", {}, [
        el("th", { text: t(`level_${level}`), className: "plain levelname" }),
        ...COLUMNS.map((column) =>
          el("td", { text: t(`help_cmp_${level}_${column}`), className: "wrap" })
        ),
      ])
    )
  );
  return el("div", { className: "scroll" }, [
    el("table", { className: "compare" }, [el("thead", {}, [head]), body]),
  ]);
}

// The sections added to the Help page; `section(title, children)` makes one.
export function levelSections(t, section) {
  const levels = section(
    t("help_levels_title"),
    [el("p", { text: t("help_levels_intro") }), levelTable(t), el("p", { text: t("shared_rule_hint") })],
    true
  );
  const uses = section(t("help_use_title"), [
    el(
      "ul",
      {},
      USE_CASES.map((name) => el("li", { text: t(`help_use_${name}`) }))
    ),
  ]);
  const apply = section(t("help_apply_title"), [
    el("p", { text: t("help_apply_intro") }),
    el(
      "ol",
      {},
      STEPS.map((step) => el("li", { text: t(`help_apply_${step}`) }))
    ),
  ]);
  return [levels, uses, apply];
}
