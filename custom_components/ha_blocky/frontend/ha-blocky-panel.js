/*
 * HA-Blocky sidebar panel: hosts the query log card full width.
 *
 * Home Assistant creates this element for the panel and sets `hass` (and
 * `narrow`, `route`, `panel`, which are not needed here). The panel is
 * registered for administrators only; the card checks the role again.
 */

import "./ha-blocky-card.js";
import { el } from "./ha-blocky-dom.js";

const PANEL_STYLE = `
  :host { display: block; padding: 16px; box-sizing: border-box; }
  ha-blocky-card { display: block; width: 100%; }
`;

class HaBlockyPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._card = undefined;
    this._hass = undefined;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._card) {
      this._card = document.createElement("ha-blocky-card");
      this._card.setConfig({});
      this.shadowRoot.append(el("style", { text: PANEL_STYLE }), this._card);
    }
    this._card.hass = hass;
  }

  get hass() {
    return this._hass;
  }
}

if (!customElements.get("ha-blocky-panel")) {
  customElements.define("ha-blocky-panel", HaBlockyPanel);
}
