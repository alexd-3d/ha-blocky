/*
 * HA-Blocky query log card.
 *
 * Shows Blocky's query log with search, filters, sorting and paging, and lets
 * an administrator add a domain to a manual allow or deny list. A second tab
 * lists the requests for new domains and the phase of the clients of
 * allowlist-only zones, with the known domains of every client. A click on a
 * client names it (the name is kept by the
 * server, keyed by the client's address).
 *
 * The card is split into plain ES modules next to this file; the browser
 * loads them by relative path. Every value from the log or the server is
 * written with textContent. A DNS name or a device name can be chosen by any
 * device on the network, so nothing from them is ever interpreted as markup.
 * The card loads nothing from outside Home Assistant. The overview card
 * (ha-blocky-overview.js) is imported here: this is the only file Home
 * Assistant loads on its own.
 */

import { DOMAIN, el } from "./ha-blocky-dom.js";
import { translate } from "./ha-blocky-i18n.js";
import { LogView } from "./ha-blocky-log.js";
import { RequestsView } from "./ha-blocky-requests.js";
import "./ha-blocky-overview.js";
import { STYLE } from "./ha-blocky-style.js";

const MIN_REFRESH_SECONDS = 10;

class HaBlockyCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = undefined;
    this._built = false;
    this._started = false;
    this._entry = undefined;
    this._tab = "log";
    this._timer = undefined;
  }

  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    const pageSize = Number(config && config.page_size);
    const refresh = Number(config && config.auto_refresh);
    this._config = {
      title: config && typeof config.title === "string" ? config.title : undefined,
      entry_id:
        config && typeof config.entry_id === "string" ? config.entry_id : undefined,
      page_size: Number.isInteger(pageSize)
        ? Math.min(Math.max(pageSize, 10), 200)
        : 50,
      auto_refresh:
        Number.isFinite(refresh) && refresh > 0
          ? Math.max(refresh, MIN_REFRESH_SECONDS)
          : 0,
    };
    if (this._built) this._renderTitle();
    this._restartTimer();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._requests.watchSensor();
    if (!this._started) {
      this._started = true;
      this._start();
    }
  }

  getCardSize() {
    return 10;
  }

  connectedCallback() {
    this._restartTimer();
  }

  disconnectedCallback() {
    this._stopTimer();
    if (this._log) this._log.stop();
  }

  // What the tabs need from the card (their "host").
  get hass() {
    return this._hass;
  }

  get entry() {
    return this._entry;
  }

  get config() {
    return this._config;
  }

  t(key) {
    return translate(this._hass, key);
  }

  // True while a client name is being typed: reloads would throw it away.
  isEditing() {
    return Boolean(this.shadowRoot.querySelector("input.nameedit"));
  }

  // Reload what is shown, e.g. after a name was saved.
  async refresh() {
    await Promise.all([this._log.load(true), this._requests.load()]);
  }

  _build() {
    this._built = true;
    const root = this.shadowRoot;
    root.appendChild(el("style", { text: STYLE }));

    this._card = document.createElement("ha-card");
    this._body = el("div", { className: "body" });
    this._card.appendChild(this._body);
    root.appendChild(this._card);
    this._renderTitle();

    this._logTab = el("button", { text: this.t("tab_log"), className: "tab" });
    this._reqTab = el("button", { text: this.t("tab_requests"), className: "tab" });
    this._logTab.addEventListener("click", () => this._selectTab("log"));
    this._reqTab.addEventListener("click", () => this._selectTab("requests"));
    const tabs = el("div", { className: "tabs" }, [this._logTab, this._reqTab]);
    this._logView = el("div");
    this._reqView = el("div", { attrs: { hidden: "" } });
    this._body.append(tabs, this._logView, this._reqView);

    this._log = new LogView(this, this._logView);
    this._requests = new RequestsView(this, this._reqView);
    this._selectTab("log");
  }

  _renderTitle() {
    this._card.setAttribute("header", this._config.title || this.t("title"));
  }

  async _start() {
    const hass = this._hass;
    if (!hass.user || !hass.user.is_admin) {
      this._log.showMessage("not_admin", true);
      this._log.hideTable();
      return;
    }
    try {
      const config = await hass.callWS({ type: `${DOMAIN}/config` });
      const entries = Array.isArray(config.entries) ? config.entries : [];
      this._entry = this._config.entry_id
        ? entries.find((entry) => entry.entry_id === this._config.entry_id)
        : entries.find((entry) => entry.has_query_log) || entries[0];
    } catch (err) {
      this._log.showMessage("error", true);
      return;
    }
    if (!this._entry) {
      this._log.showMessage("no_entry", true);
      return;
    }
    if (!this._entry.has_query_log) {
      this._log.showMessage("no_query_log", false);
      return;
    }
    this._log.renderHead();
    await this._log.load(true);
    if (this._tab === "requests") this._requests.load();
    this._restartTimer();
  }

  _selectTab(tab) {
    this._tab = tab;
    this._logView.hidden = tab !== "log";
    this._reqView.hidden = tab !== "requests";
    this._logTab.className = tab === "log" ? "tab active" : "tab";
    this._reqTab.className = tab === "requests" ? "tab active" : "tab";
    this._requests.setActive(tab === "requests");
  }

  _stopTimer() {
    clearInterval(this._timer);
    this._timer = undefined;
  }

  _restartTimer() {
    this._stopTimer();
    const seconds = this._config.auto_refresh;
    if (!seconds || !this.isConnected || !this._entry) return;
    this._timer = setInterval(() => {
      // Only refresh the first page, and only while the user is not acting.
      if (
        document.visibilityState === "visible" &&
        this._log.onFirstPage &&
        !this._log.busy &&
        !this.isEditing()
      ) {
        this._log.load(true);
      }
    }, seconds * 1000);
  }
}

if (!customElements.get("ha-blocky-card")) {
  customElements.define("ha-blocky-card", HaBlockyCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "ha-blocky-card")) {
  window.customCards.push({
    type: "ha-blocky-card",
    name: "HA-Blocky query log",
    description: "Blocky's DNS query log with search, filters and allow/block actions.",
  });
}
