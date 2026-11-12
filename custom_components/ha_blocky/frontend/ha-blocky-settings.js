/*
 * The "Settings" tab. Display preferences (the colour of each kind of query
 * and the default number of rows) are kept per Home Assistant and apply at
 * once; the operational options (intervals, new-domain reporting, sidebar
 * entry, list names) are options of the integration and reload it.
 * Both go through the command `ha_blocky/set_settings`; the server checks
 * every value again. Colours are validated here too (exactly #rrggbb) before
 * they are used.
 * `host` offers: hass, entry, t(key), previewColors(colors), reloadEntry().
 */

import { buttonGroup } from "./ha-blocky-controls.js";
import { DOMAIN, el, svg } from "./ha-blocky-dom.js";
import {
  CATEGORIES,
  DEFAULT_COLORS,
  ROW_CHOICES,
  validColor,
} from "./ha-blocky-format.js";
import { loadPrefs, prefs } from "./ha-blocky-prefs.js";
import { OptionsForm } from "./ha-blocky-settings-options.js";

// The label of each field a refusal can name (never taken from the server).
const FIELD_LABELS = {
  status_interval: "set_status_interval",
  stats_interval: "set_stats_interval",
  tops_interval: "set_tops_interval",
  report_existing_domains: "set_report",
  show_in_sidebar: "set_sidebar",
  allow_lists: "set_allow_lists",
  deny_lists: "set_deny_lists",
  exact_only_lists: "set_exact_lists",
  rows: "set_rows_default",
};
const RELOAD_DELAY_MS = 4000;

export class SettingsView {
  constructor(host, container) {
    this._host = host;
    this._rows = undefined;
    this._rowsTouched = false;
    this._inputs = {};
    this._options = new OptionsForm(host);
    this._build(container);
  }

  _t(key) {
    return this._host.t(key);
  }

  // The label of the refused field and the reason, from the card's own texts.
  _errorText(err) {
    const code = err && typeof err.code === "string" ? err.code : "";
    const reason = this._t(`serr_${code}`);
    const known = reason !== `serr_${code}`;
    const name = err && typeof err.message === "string" ? err.message : "";
    let label = "";
    if (name.startsWith("colors.") && CATEGORIES.includes(name.slice(7))) {
      label = this._t(`cat_${name.slice(7)}`);
    } else if (Object.prototype.hasOwnProperty.call(FIELD_LABELS, name)) {
      label = this._t(FIELD_LABELS[name]);
    }
    const text = known ? reason : this._t("set_save_error");
    return label ? `${label}: ${text}` : text;
  }

  // A card of the Settings tab: a heading, a short description, then the fields.
  _section(titleKey, hintKey) {
    const message = el("div", { className: "message", attrs: { hidden: "" } });
    const root = el("section", { className: "scard" }, [
      el("h3", { text: this._t(titleKey) }),
      el("div", { className: "hint", text: this._t(hintKey) }),
    ]);
    return { root, message };
  }

  _say(message, key, isError, text) {
    message.textContent = text || (key ? this._t(key) : "");
    message.className = isError ? "message error" : "message";
    message.hidden = !message.textContent;
  }

  _build(container) {
    const display = this._section("set_display_title", "set_display_hint");
    this._displayMessage = display.message;
    const grid = el("div", { className: "colors" });
    for (const category of CATEGORIES) {
      const input = el("input", {
        attrs: { type: "color", "aria-label": this._t(`cat_${category}`) },
      });
      input.value = DEFAULT_COLORS[category];
      input.addEventListener("input", () => this._host.previewColors(this._colors()));
      this._inputs[category] = input;
      grid.appendChild(
        el("label", { className: "crow" }, [
          input,
          el("span", { text: this._t(`cat_${category}`), className: "cname" }),
        ])
      );
    }
    // The preview uses the classes of the dashboard, so it shows the colours
    // being edited (the card previews them while they are edited).
    const bar = svg("svg", {
      class: "mbar pbar",
      viewBox: "0 0 100 4",
      preserveAspectRatio: "none",
      "aria-hidden": "true",
    });
    CATEGORIES.forEach((category, index) => {
      bar.appendChild(
        svg("rect", {
          class: `seg c-${category}`,
          x: index * 20,
          y: 0,
          width: 20,
          height: 4,
        })
      );
    });
    this._rowsGroup = buttonGroup(
      this._t("set_rows_default"),
      ROW_CHOICES.map((value) => ({ value, label: String(value) })),
      10,
      (value) => {
        this._rows = value;
        this._rowsTouched = true;
      }
    );
    const save = el("button", { text: this._t("set_save"), className: "primary" });
    const reset = el("button", { text: this._t("set_reset") });
    save.addEventListener("click", () => this._saveDisplay());
    reset.addEventListener("click", () => this._resetDisplay());
    display.root.append(
      el("div", { className: "group" }, [
        el("h4", { className: "gtitle", text: this._t("set_colors") }),
        grid,
        el("div", { className: "flabel", text: this._t("set_preview") }),
        bar,
      ]),
      el("div", { className: "group" }, [
        el("h4", { className: "gtitle", text: this._t("set_group_defaults") }),
        el("div", { className: "flabel", text: this._t("set_rows_default") }),
        this._rowsGroup,
        el("div", { className: "hint", text: this._t("set_rows_hint") }),
      ]),
      el("div", { className: "btnrow" }, [save, reset]),
      display.message
    );

    const ops = this._section("set_ops_title", "set_ops_hint");
    this._opsMessage = ops.message;
    const saveOps = el("button", { text: this._t("set_save"), className: "primary" });
    saveOps.addEventListener("click", () => this._saveOptions());
    ops.root.append(
      this._options.element,
      el("div", { className: "btnrow" }, [saveOps]),
      ops.message
    );

    this._ops = ops.root;
    container.appendChild(el("div", { className: "settings" }, [display.root, ops.root]));
  }

  // The colours in the inputs, each checked before it is used.
  _colors() {
    const colors = {};
    for (const category of CATEGORIES) {
      colors[category] =
        validColor(this._inputs[category].value) || DEFAULT_COLORS[category];
    }
    return colors;
  }

  // Show what is saved: the inputs, the rows and no preview.
  _showSaved() {
    for (const category of CATEGORIES) {
      this._inputs[category].value = prefs.colors[category] || DEFAULT_COLORS[category];
    }
    this._rows = prefs.rows;
    this._rowsTouched = false;
    this._rowsGroup.mark(prefs.rows || 10);
    this._host.previewColors(undefined);
  }

  async load() {
    const entry = this._host.entry;
    try {
      const result = await this._host.hass.callWS({
        type: `${DOMAIN}/settings`,
        ...(entry ? { entry_id: entry.entry_id } : {}),
      });
      await loadPrefs(this._host.hass);
      this._showSaved();
      this._ops.hidden = !(result && result.entry);
      this._options.fill(result && result.entry);
      this._say(this._displayMessage, "", false);
    } catch (err) {
      this._say(this._displayMessage, "set_load_error", true);
    }
  }

  // Leaving the tab drops a preview that was not saved.
  setActive(active) {
    if (active) {
      this.load();
    } else {
      this._host.previewColors(undefined);
    }
  }

  async _send(payload, message) {
    try {
      const result = await this._host.hass.callWS({
        type: `${DOMAIN}/set_settings`,
        ...payload,
      });
      return result || {};
    } catch (err) {
      this._say(message, "", true, this._errorText(err));
      return undefined;
    }
  }

  async _saveDisplay() {
    const colors = {};
    const current = this._colors();
    for (const category of CATEGORIES) {
      const same = current[category] === DEFAULT_COLORS[category];
      colors[category] = same ? null : current[category];
    }
    const payload = { colors };
    if (this._rowsTouched) payload.rows = this._rows || null;
    if (await this._send(payload, this._displayMessage)) {
      await loadPrefs(this._host.hass);
      this._showSaved();
      this._say(this._displayMessage, "set_saved", false);
    }
  }

  async _resetDisplay() {
    const colors = {};
    for (const category of CATEGORIES) colors[category] = null;
    if (await this._send({ colors, rows: null }, this._displayMessage)) {
      await loadPrefs(this._host.hass);
      this._showSaved();
      this._say(this._displayMessage, "set_saved", false);
    }
  }

  async _saveOptions() {
    const changes = this._options.changes();
    if (!Object.keys(changes).length) {
      this._say(this._opsMessage, "serr_nothing_to_change", false);
      return;
    }
    const entry = this._host.entry;
    const payload = { ...changes, ...(entry ? { entry_id: entry.entry_id } : {}) };
    const result = await this._send(payload, this._opsMessage);
    if (!result) return;
    this._say(this._opsMessage, result.reloading ? "set_saved_reload" : "set_saved", false);
    // The integration reloads; look again once it is back.
    setTimeout(() => this._host.reloadEntry(), RELOAD_DELAY_MS);
  }
}
