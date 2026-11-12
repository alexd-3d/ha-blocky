/*
 * HA-Blocky card: the entry module Home Assistant loads on its own.
 *
 * This file has no imports on purpose. It defines the two card elements the
 * moment it runs, so a dashboard never meets an undefined element (Home
 * Assistant shows an error card when a custom element is not defined within
 * about two seconds, and the whole module graph of the views can take longer
 * on a slow link). Each element is a thin shell: it keeps the configuration
 * and `hass` it is given, shows a short loading note, loads the real view
 * module (ha-blocky-card-view.js, ha-blocky-overview.js) once, and hands
 * everything over. `setConfig`, `hass`, `editMode`, `getCardSize` and
 * `connectedCallback` never raise an error, whatever the order of the calls.
 */

const NOTES = {
  loading: { en: "Loading…", uk: "Завантаження…" },
  failed: {
    en: "The card could not be loaded. Reload the page.",
    uk: "Не вдалося завантажити картку. Оновіть сторінку.",
  },
};

const STYLE = `
  :host { display: block; }
  .note { padding: 16px; color: var(--secondary-text-color); }
  .note.error { color: var(--error-color); }
`;

function noteText(hass, key) {
  const language = (hass && hass.locale && hass.locale.language) || (hass && hass.language) || "en";
  return NOTES[key][language.split("-")[0] === "uk" ? "uk" : "en"];
}

// Define `tag` as a shell for the view element `viewTag`, which `load()` (a
// dynamic import of a module that defines it) makes available.
function defineShell(tag, load, viewTag, size) {
  if (customElements.get(tag)) return;
  class Shell extends HTMLElement {
    constructor() {
      super();
      this._config = undefined;
      this._hass = undefined;
      this._editMode = false;
      this._view = undefined;
      this._state = "idle";
      this._sent = {};
      const root = this.attachShadow({ mode: "open" });
      const style = document.createElement("style");
      style.textContent = STYLE;
      this._note = document.createElement("div");
      this._note.className = "note";
      root.append(style, this._note);
      this._say("loading");
    }

    static getStubConfig() {
      return {};
    }

    setConfig(config) {
      this._config = config;
      this._pass();
    }

    set hass(hass) {
      this._hass = hass;
      if (!this._view) this._say(this._state === "failed" ? "failed" : "loading");
      this._load();
      this._pass();
    }

    get hass() {
      return this._hass;
    }

    set editMode(value) {
      this._editMode = Boolean(value);
      this._pass();
    }

    get editMode() {
      return this._editMode;
    }

    getCardSize() {
      return size;
    }

    connectedCallback() {
      this._load();
    }

    _say(key) {
      this._note.textContent = noteText(this._hass, key);
      this._note.className = key === "failed" ? "note error" : "note";
    }

    // Load the view module once; a failure is shown and logged, never thrown.
    _load() {
      if (this._state !== "idle") return;
      this._state = "loading";
      let pending;
      try {
        pending = load();
      } catch (err) {
        pending = Promise.reject(err);
      }
      Promise.resolve(pending)
        .then(() => customElements.whenDefined(viewTag))
        .then(() => this._attach())
        .catch((err) => {
          this._state = "failed";
          this._say("failed");
          console.error("HA-Blocky: could not load the card", err);
        });
    }

    _attach() {
      this._view = document.createElement(viewTag);
      this._state = "ready";
      this._note.remove();
      this.shadowRoot.appendChild(this._view);
      this._pass();
    }

    // Hand the configuration, the edit mode and `hass` to the view; only what
    // changed, and never an exception back to Home Assistant.
    _pass() {
      const view = this._view;
      if (!view) return;
      try {
        if (this._config !== undefined && this._sent.config !== this._config) {
          this._sent.config = this._config;
          view.setConfig(this._config);
        }
        if (this._sent.editMode !== this._editMode) {
          this._sent.editMode = this._editMode;
          view.editMode = this._editMode;
        }
        if (this._hass !== undefined && this._hass !== null) view.hass = this._hass;
      } catch (err) {
        console.error("HA-Blocky: the card failed", err);
      }
    }
  }
  customElements.define(tag, Shell);
}

defineShell("ha-blocky-card", () => import("./ha-blocky-card-view.js"), "ha-blocky-card-view", 10);
defineShell("ha-blocky-overview-card", () => import("./ha-blocky-overview.js"), "ha-blocky-overview-view", 8);

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "ha-blocky-card")) {
  window.customCards.push({
    type: "ha-blocky-card",
    name: "HA-Blocky",
    description:
      "Blocky dashboard, DNS query log with search, filters and allow/block actions, and requests.",
  });
}
if (!window.customCards.some((card) => card.type === "ha-blocky-overview-card")) {
  window.customCards.push({
    type: "ha-blocky-overview-card",
    name: "HA-Blocky overview",
    description: "Top domains, blocked domains and clients of the last 24 hours, and pending requests.",
  });
}
