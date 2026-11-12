/*
 * The display preferences kept by the server (the colour of each kind of
 * query and the default number of rows) and the one style element per card
 * that applies the colours. Everything from the server is validated again
 * here: a colour must be exactly #rrggbb before it gets near a style sheet.
 */

import { DOMAIN } from "./ha-blocky-dom.js";
import { ROW_CHOICES, colorCss, validColor, CATEGORIES } from "./ha-blocky-format.js";

const listeners = new Set();

// The preferences as last loaded; read by the cards.
export const prefs = { colors: {}, rows: undefined };

function clean(display) {
  const source = display && typeof display === "object" ? display : {};
  const colors = {};
  for (const category of CATEGORIES) {
    const color = validColor(source.colors && source.colors[category]);
    if (color) colors[category] = color;
  }
  const rows = ROW_CHOICES.includes(source.rows) ? source.rows : undefined;
  return { colors, rows };
}

// Take new preferences and tell everyone who listens.
export function setPrefs(display) {
  const next = clean(display);
  prefs.colors = next.colors;
  prefs.rows = next.rows;
  for (const listener of Array.from(listeners)) listener();
}

export function onPrefs(listener) {
  listeners.add(listener);
}

export function offPrefs(listener) {
  listeners.delete(listener);
}

// Ask the server for the preferences; a failure leaves the defaults.
export async function loadPrefs(hass) {
  try {
    const result = await hass.callWS({ type: `${DOMAIN}/settings` });
    setPrefs(result && result.display);
    return result;
  } catch (err) {
    return undefined;
  }
}

// The style element of one card. Its text is composed by colorCss only; a
// preview (the colours being edited) replaces the saved colours until it is
// cleared.
export class ColorStyle {
  constructor(root) {
    this.element = document.createElement("style");
    root.appendChild(this.element);
    this._preview = undefined;
    this._render = () => this.render();
    this.render();
  }

  render() {
    this.element.textContent = colorCss(this._preview || prefs.colors);
  }

  start() {
    onPrefs(this._render);
    this.render();
  }

  stop() {
    offPrefs(this._render);
  }

  preview(colors) {
    this._preview = colors;
    this.render();
  }
}
