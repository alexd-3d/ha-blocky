/*
 * The toolbar of the Dashboard tab: the blocking switch, the length of the
 * pause, two buttons for the integration's own button entities (refresh the
 * lists, flush the cache) and the period buttons. Only existing entities are
 * used: the switch and the pause select through the switch and select
 * services, the buttons through the button service. Their entity ids come
 * from the server (`ha_blocky/config`) and are checked against the shape of an
 * entity id of that domain; one that is missing or unavailable is hidden or
 * disabled, never an error. `host` offers: hass, entry, t(key).
 */

import { flasher } from "./ha-blocky-actions.js";
import { glyphButton } from "./ha-blocky-controls.js";
import { el } from "./ha-blocky-dom.js";
import { readChoice, writeChoice } from "./ha-blocky-format.js";
import { BlockingSwitch } from "./ha-blocky-switch.js";

const DEFAULT_MINUTES = 5;
const MAX_MINUTES = 1440;
const PAUSE_ID = /^select\.[a-z0-9_]+$/;
const BUTTON_ID = /^button\.[a-z0-9_]+$/;
const TOOLS = [
  { field: "refresh_lists_entity", icon: "tool_refresh_lists", label: "dash_refresh_lists" },
  { field: "flush_cache_entity", icon: "tool_flush_cache", label: "dash_flush_cache" },
];

// The text of a number of minutes: "15 min", "2 h". `t(key)` gives card texts.
export function durationText(t, minutes) {
  const whole = minutes >= 60 && minutes % 60 === 0;
  const text = t(whole ? "dash_hours" : "dash_minutes");
  return text.replace("{n}", String(whole ? minutes / 60 : minutes));
}

export class Toolbar {
  // `onError(key)` is told when an action failed ("" when it went well);
  // `periods` is the period button group.
  constructor(host, onError, periods) {
    this._host = host;
    this._onError = onError;
    this._minutes = undefined;
    this._shown = "";
    this._busy = false;
    this._switch = new BlockingSwitch(host, onError, () => this._pause());

    this._select = el("select", { attrs: { "aria-label": host.t("dash_pause_for") } });
    this._select.addEventListener("change", () => {
      this._minutes = Number(this._select.value);
      writeChoice("pause", this._minutes);
      this._drawHint();
    });
    this._pauseBox = el("label", { className: "pausebox", attrs: { hidden: "" } }, [
      el("span", { text: host.t("dash_pause_for"), className: "sub" }),
      this._select,
    ]);

    this._buttons = TOOLS.map((tool) => {
      const button = glyphButton(host.t(tool.label), tool.icon, "tbtn");
      button.hidden = true;
      button.addEventListener("click", () => this._press(tool, button));
      return { tool, button };
    });

    this._hint = el("div", { className: "hint" });
    const left = el("div", { className: "tgroup" }, [
      this._switch.element,
      this._pauseBox,
      ...this._buttons.map((item) => item.button),
    ]);
    this.element = el("div", { className: "dtools" }, [
      el("div", { className: "toolbar" }, [left, periods]),
      this._hint,
    ]);
    this.update();
  }

  _t(key) {
    return this._host.t(key);
  }

  // The id and the state of an entity of the entry (both undefined when the
  // server named none, the id is malformed or Home Assistant does not know it).
  _lookup(field, pattern) {
    const entry = this._host.entry;
    const id = entry && typeof entry[field] === "string" ? entry[field] : "";
    const hass = this._host.hass;
    if (!pattern.test(id) || !hass || !hass.states || !hass.states[id]) return {};
    return { id, state: hass.states[id] };
  }

  // The minutes the pause select offers (empty when it cannot be used).
  _options() {
    const { state } = this._lookup("pause_entity", PAUSE_ID);
    if (!state || state.state === "unavailable") return [];
    const options = state.attributes && Array.isArray(state.attributes.options) ? state.attributes.options : [];
    return options
      .map(Number)
      .filter((value) => Number.isInteger(value) && value > 0 && value <= MAX_MINUTES);
  }

  _current(options) {
    if (!options.includes(this._minutes)) {
      const fallback = options.includes(DEFAULT_MINUTES) ? DEFAULT_MINUTES : options[0];
      this._minutes = readChoice("pause", options, fallback);
    }
    return this._minutes;
  }

  // The pause for turning the switch off: { id, minutes }, or undefined (the
  // switch's own default then applies).
  _pause() {
    const options = this._options();
    const { id } = this._lookup("pause_entity", PAUSE_ID);
    return id && options.length ? { id, minutes: this._current(options) } : undefined;
  }

  _drawHint() {
    const options = this._options();
    const minutes = options.length ? this._current(options) : DEFAULT_MINUTES;
    const duration = durationText((key) => this._t(key), minutes);
    this._hint.textContent = this._t("dash_switch_hint").replace("{n}", duration);
  }

  // Redraw from the current states of the entities.
  update() {
    this._switch.update();
    const options = this._options();
    const key = options.join(",");
    if (key !== this._shown) {
      this._shown = key;
      this._select.replaceChildren(
        ...options.map((minutes) =>
          el("option", {
            text: durationText((name) => this._t(name), minutes),
            attrs: { value: minutes },
          })
        )
      );
    }
    this._pauseBox.hidden = !options.length;
    if (options.length) this._select.value = String(this._current(options));
    for (const { tool, button } of this._buttons) {
      const { state } = this._lookup(tool.field, BUTTON_ID);
      button.hidden = !state;
      button.disabled = !state || state.state === "unavailable" || this._busy;
    }
    this._drawHint();
  }

  async _press(tool, button) {
    const { id, state } = this._lookup(tool.field, BUTTON_ID);
    if (!id || state.state === "unavailable" || this._busy) return;
    this._busy = true;
    this.update();
    try {
      await this._host.hass.callService("button", "press", { entity_id: id });
      flasher.mark(`tool:${id}`, "approve", button);
      this._onError("");
    } catch (err) {
      flasher.mark(`tool:${id}`, "reject", button);
      this._onError("dash_tool_error");
    } finally {
      this._busy = false;
      this.update();
    }
  }
}
