/*
 * HA-Blocky card.
 *
 * Three tabs. The Dashboard shows the blocking switch, the totals of a period,
 * a chart of queries over time and the top clients and domains. The Query log
 * has search, filters, sorting and paging, and lets an administrator add a
 * domain to a manual allow or deny list. Requests lists the requests for new
 * domains and the phase of the clients of allowlist-only zones, with the known
 * domains of every client. A click on a client names it (the name is kept by
 * the server, keyed by the client's address).
 *
 * The card is split into plain ES modules next to this file; the browser
 * loads them by relative path. Every value from the log or the server is
 * written with textContent. A DNS name or a device name can be chosen by any
 * device on the network, so nothing from them is ever interpreted as markup.
 * The card loads nothing from outside Home Assistant. The overview card
 * (ha-blocky-overview.js) is imported here: this is the only file Home
 * Assistant loads on its own.
 */

import { UI_ICONS, haIcon } from "./ha-blocky-actions.js";
import { DashboardView } from "./ha-blocky-dashboard.js";
import { DOMAIN, el } from "./ha-blocky-dom.js";
import { translate } from "./ha-blocky-i18n.js";
import { LogView } from "./ha-blocky-log.js";
import { RequestsView } from "./ha-blocky-requests.js";
import "./ha-blocky-overview.js";
import { STYLE } from "./ha-blocky-style.js";

const MIN_REFRESH_SECONDS = 10;
const TABS = ["dashboard", "log", "requests"];

class HaBlockyCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = undefined;
    this._built = false;
    this._started = false;
    this._entry = undefined;
    this._tab = "dashboard";
    this._editMode = false;
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
      // Not set: the dashboard reloads by itself, the query log does not.
      auto_refresh:
        config && config.auto_refresh === undefined
          ? undefined
          : Number.isFinite(refresh) && refresh > 0
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
    this._dash.updateHass();
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
    if (this._dash) this._dash.stop();
  }

  // Home Assistant sets this while the dashboard is being edited.
  set editMode(value) {
    this._editMode = Boolean(value);
  }

  get editMode() {
    return this._editMode;
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
    await Promise.all([this._log.load(true), this._requests.load(), this._dash.load()]);
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

    // A tab shows an icon and its title; a narrow card shows the icon only.
    this._tabs = {};
    this._views = {};
    for (const id of TABS) {
      const label = this.t(`tab_${id}`);
      const button = el(
        "button",
        { className: "tab", attrs: { type: "button", role: "tab", title: label, "aria-label": label } },
        [haIcon(UI_ICONS, `tab_${id}`, "tabicon"), el("span", { text: label, className: "tablabel" })]
      );
      button.addEventListener("click", () => this._selectTab(id));
      this._tabs[id] = button;
      this._views[id] = el("div", { attrs: { hidden: "" } });
    }
    const tabs = el("div", { className: "tabs", attrs: { role: "tablist" } }, Object.values(this._tabs));
    this._body.append(tabs, ...Object.values(this._views));

    this._dash = new DashboardView(this, this._views.dashboard);
    this._log = new LogView(this, this._views.log);
    this._requests = new RequestsView(this, this._views.requests);
    this._selectTab(this._tab);
  }

  _renderTitle() {
    this._card.setAttribute("header", this._config.title || this.t("title"));
  }

  async _start() {
    const hass = this._hass;
    if (!hass.user || !hass.user.is_admin) {
      this._log.showMessage("not_admin", true);
      this._log.hideTable();
      this._dash.hideContent("not_admin", true);
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
      this._dash.hideContent("dash_error", true);
      return;
    }
    if (!this._entry) {
      this._log.showMessage("no_entry", true);
      this._dash.hideContent("no_entry", true);
      return;
    }
    this._dash.updateHass();
    this._dash.setActive(this._tab === "dashboard");
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
    for (const id of TABS) {
      this._views[id].hidden = id !== tab;
      this._tabs[id].className = id === tab ? "tab active" : "tab";
      this._tabs[id].setAttribute("aria-selected", String(id === tab));
    }
    this._requests.setActive(tab === "requests");
    this._dash.setActive(tab === "dashboard");
  }

  _stopTimer() {
    clearInterval(this._timer);
    this._timer = undefined;
  }

  _restartTimer() {
    this._stopTimer();
    if (this._dash) this._dash.restartTimer();
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
    name: "HA-Blocky",
    description:
      "Blocky dashboard, DNS query log with search, filters and allow/block actions, and requests.",
  });
}
