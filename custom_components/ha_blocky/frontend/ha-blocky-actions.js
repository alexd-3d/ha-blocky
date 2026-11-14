/*
 * Shared pieces of the card and the overview card: the icon buttons, the
 * fixed icon tables and the panel that picks the list for allow/block.
 * `host` offers: hass, entry, t(key).
 *
 * Icon names never come from data: they are looked up in the two tables
 * below, and an unknown key gives no icon.
 */

import { DOMAIN, el } from "./ha-blocky-dom.js";

// What a request may be resolved with; "dismiss" is a rejection.
export const ACTION_OF = {
  approve: "approve",
  reject: "reject",
  block: "block",
  dismiss: "reject",
};

// The icons of the actions.
export const ICONS = {
  allow: "mdi:shield-check",
  block: "mdi:shield-off",
  approve: "mdi:check",
  reject: "mdi:close",
  dismiss: "mdi:close",
};

// The icons of the status of a query, by category.
export const STATUS_ICONS = {
  blocked: "mdi:cancel",
  resolved: "mdi:check",
  cached: "mdi:cached",
  local: "mdi:home-outline",
  other: "mdi:help-circle-outline",
};

// The icons of the card's own chrome: the tabs, the tiles and the tool buttons.
export const UI_ICONS = {
  tab_dashboard: "mdi:view-dashboard",
  tab_log: "mdi:format-list-bulleted",
  tab_requests: "mdi:inbox-arrow-down",
  tab_settings: "mdi:cog",
  tab_help: "mdi:help-circle-outline",
  tile_total: "mdi:dns",
  tile_blocked: "mdi:cancel",
  tile_cached: "mdi:cached",
  tile_latency: "mdi:timer-outline",
  help: "mdi:help-circle-outline",
  tool_refresh_lists: "mdi:playlist-check",
  tool_flush_cache: "mdi:delete-sweep",
  log_refresh: "mdi:refresh",
  log_live: "mdi:access-point",
  chevron: "mdi:chevron-right",
  rule_remove: "mdi:close",
};

// The effect of each action: "good" actions let something through, "bad" ones
// keep it out or remove it. The icon takes the colour of its effect; an
// unknown action stays neutral.
export const EFFECT_OF = {
  allow: "good",
  approve: "good",
  block: "bad",
  reject: "bad",
  dismiss: "bad",
  // A row that appeared in the live query log: a neutral highlight.
  new: "info",
};

export function effectOf(action) {
  return Object.prototype.hasOwnProperty.call(EFFECT_OF, action) ? EFFECT_OF[action] : "";
}

const FLASH_MS = 1000;

// Highlights the row an action was done on for about a second: the row gets
// the class `flash-good` or `flash-bad`, the style sheet fades it out. A
// refresh that rebuilds the row picks the highlight up again by its key.
class Flasher {
  constructor() {
    this._marks = new Map();
  }

  // Remember the action; `node` (if given) is highlighted at once.
  mark(key, action, node) {
    const effect = effectOf(action);
    if (!effect) return;
    this._marks.set(key, { effect, until: Date.now() + FLASH_MS });
    if (node) this.apply(key, node);
  }

  // Highlight `node` for what is left of the second, if `key` was marked.
  apply(key, node) {
    const mark = this._marks.get(key);
    if (!mark) return;
    const left = mark.until - Date.now();
    if (left <= 0) {
      this._marks.delete(key);
      return;
    }
    const name = `flash-${mark.effect}`;
    node.classList.add(name);
    setTimeout(() => node.classList.remove(name), left);
  }
}

export const flasher = new Flasher();

// Wait while a highlighted row is still worth seeing (it is about to go).
export function flashPause() {
  return new Promise((resolve) => setTimeout(resolve, FLASH_MS * 0.8));
}

// An icon from one of the tables above (no icon for an unknown key).
export function haIcon(table, key, className) {
  const icon = document.createElement("ha-icon");
  if (Object.prototype.hasOwnProperty.call(table, key)) icon.icon = table[key];
  if (className) icon.className = className;
  icon.setAttribute("aria-hidden", "true");
  return icon;
}

export function setDisabled(button, disabled) {
  if (disabled) {
    button.setAttribute("aria-disabled", "true");
  } else {
    button.removeAttribute("aria-disabled");
  }
}

// An icon that acts as a button: focusable, named for screen readers, and
// triggered by a click, Enter or Space. `labelKey` is a key of the card's own
// texts; the label is never taken from data.
export function iconButton(host, action, labelKey, onClick) {
  const label = host.t(labelKey);
  const effect = effectOf(action);
  const button = el("span", {
    className: effect ? `iconbtn fx-${effect}` : "iconbtn",
    attrs: { role: "button", tabindex: "0", title: label, "aria-label": label },
  });
  button.appendChild(haIcon(ICONS, action));
  const run = () => {
    if (button.getAttribute("aria-disabled") !== "true") onClick(button);
  };
  button.addEventListener("click", run);
  button.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      event.stopPropagation();
      run();
    }
  });
  return button;
}

// The panel that asks for the list a domain goes to, then calls the
// allow_domain or block_domain service. `panel` is an element the caller owns.
export class ListPicker {
  constructor(host, panel, onDone) {
    this._host = host;
    this._panel = panel;
    this._onDone = onDone;
    this._pending = undefined;
  }

  // True while the panel is open: reloads would put the choice in doubt.
  get busy() {
    return Boolean(this._pending);
  }

  lists(type) {
    const entry = this._host.entry;
    const lists = entry && Array.isArray(entry.lists) ? entry.lists : [];
    return lists.filter((list) => list.type === type);
  }

  // `context` is handed back to the done callback, so that it knows the row.
  open(type, domain, context) {
    const lists = this.lists(type);
    if (!lists.length || typeof domain !== "string" || !domain) return;
    const t = (key) => this._host.t(key);
    this._pending = { type, domain };

    const select = el(
      "select",
      { attrs: { "aria-label": t("choose_list") } },
      lists.map((list) =>
        el("option", { text: t(`list_${list.name}`), attrs: { value: list.name } })
      )
    );
    const confirm = el("button", { text: t("confirm"), className: "primary" });
    const cancel = el("button", { text: t("cancel") });
    const result = el("span");

    cancel.addEventListener("click", () => this.close());
    confirm.addEventListener("click", async () => {
      confirm.disabled = true;
      try {
        await this._host.hass.callService(
          DOMAIN,
          type === "allow" ? "allow_domain" : "block_domain",
          { config_entry_id: this._host.entry.entry_id, list: select.value, domain }
        );
        result.textContent = t("done");
        confirm.hidden = true;
        cancel.textContent = "×";
        if (this._onDone) this._onDone(context);
      } catch (err) {
        result.textContent = (err && err.message) || t("error");
        confirm.disabled = false;
      }
    });

    this._panel.replaceChildren(
      el("span", { text: t(type === "allow" ? "action_allow" : "action_block") }),
      el("span", { text: domain, className: "name" }),
      select,
      confirm,
      cancel,
      result
    );
    this._panel.hidden = false;
  }

  close() {
    this._pending = undefined;
    this._panel.hidden = true;
    this._panel.replaceChildren();
  }
}
