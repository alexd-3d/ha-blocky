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
  const button = el("span", {
    className: "iconbtn",
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

  open(type, domain) {
    const lists = this.lists(type);
    if (!lists.length || typeof domain !== "string" || !domain) return;
    const t = (key) => this._host.t(key);
    this._pending = { type, domain };

    const select = el(
      "select",
      { attrs: { "aria-label": t("choose_list") } },
      lists.map((list) => el("option", { text: list.name, attrs: { value: list.name } }))
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
        if (this._onDone) this._onDone();
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
