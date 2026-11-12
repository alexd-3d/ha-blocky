/*
 * The blocking switch of the Dashboard tab: a button with a status pill. It
 * drives the integration's own switch entity through the switch service; the
 * entity id comes from the server (`ha_blocky/config`) and is checked against
 * the shape of a switch entity id before it is used. Turning it off pauses for
 * the length `pause()` gives ({ id, minutes } of the integration's pause
 * select, which pauses right away when an option is selected); without one the
 * switch itself is turned off and pauses for its default.
 * `host` offers: hass, entry, t(key).
 */

import { el } from "./ha-blocky-dom.js";

const SWITCH_ID = /^switch\.[a-z0-9_]+$/;

export class BlockingSwitch {
  // `onError(key)` is told when the service call failed ("" when it went well).
  constructor(host, onError, pause) {
    this._host = host;
    this._onError = onError;
    this._pause = pause || (() => undefined);
    this._busy = false;
    this._pill = el("span", { className: "pill" });
    this.element = el(
      "button",
      {
        className: "bswitch",
        attrs: {
          type: "button",
          role: "switch",
          "aria-label": host.t("dash_switch_label"),
        },
      },
      [this._pill, el("span", { className: "track" }, [el("span", { className: "knob" })])]
    );
    this.element.addEventListener("click", () => this._toggle());
    this.update();
  }

  _state() {
    const entry = this._host.entry;
    const id = entry && typeof entry.blocking_entity === "string" ? entry.blocking_entity : "";
    if (!SWITCH_ID.test(id)) return { id: "", state: undefined };
    const hass = this._host.hass;
    const found = hass && hass.states ? hass.states[id] : undefined;
    return { id, state: found ? found.state : undefined };
  }

  // Redraw from the current state of the entity.
  update() {
    const { state } = this._state();
    const known = state === "on" || state === "off";
    const key =
      state === "on"
        ? "dash_blocking_active"
        : state === "off"
          ? "dash_blocking_paused"
          : "dash_blocking_unavailable";
    this._pill.textContent = this._host.t(key);
    this.element.className = `bswitch ${known ? state : "na"}`;
    this.element.setAttribute("aria-checked", String(state === "on"));
    this.element.disabled = !known || this._busy;
  }

  async _toggle() {
    const { id, state } = this._state();
    if (!id || (state !== "on" && state !== "off")) return;
    this._busy = true;
    this.update();
    try {
      const pause = state === "on" ? this._pause() : undefined;
      await this._host.hass.callService(
        ...(pause
          ? ["select", "select_option", { entity_id: pause.id, option: String(pause.minutes) }]
          : ["switch", state === "on" ? "turn_off" : "turn_on", { entity_id: id }])
      );
      this._onError("");
    } catch (err) {
      this._onError("dash_switch_error");
    } finally {
      this._busy = false;
      this.update();
    }
  }
}
