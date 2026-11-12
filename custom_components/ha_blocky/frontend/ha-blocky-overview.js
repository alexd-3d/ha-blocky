/*
 * HA-Blocky overview card: the top domains, top blocked domains and top
 * clients of the last 24 hours, and the requests waiting for a decision, each
 * with icon actions. A client is named as in the query log card (a click names
 * it; the name is kept by the server).
 *
 * Like the query log card it writes every value from the server with
 * textContent only and loads nothing from outside Home Assistant.
 */

import { ACTION_OF, ListPicker, flashPause, flasher, iconButton, setDisabled } from "./ha-blocky-actions.js";
import { DOMAIN, clientCell, el } from "./ha-blocky-dom.js";
import { translate } from "./ha-blocky-i18n.js";
import { ColorStyle, loadPrefs } from "./ha-blocky-prefs.js";
import { STYLE } from "./ha-blocky-style.js";

const MIN_REFRESH_SECONDS = 10;
const DEFAULT_REFRESH_SECONDS = 60;
// The kind of list each icon action adds to.
const LIST_TYPE_OF = { allow: "allow", block: "deny" };

function list(value) {
  return Array.isArray(value) ? value : [];
}

class HaBlockyOverviewCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = undefined;
    this._built = false;
    this._started = false;
    this._entry = undefined;
    this._timer = undefined;
    this._token = 0;
    this._data = { domains: [], blocked: [], clients: [], requests: [] };
    this._busy = new Set();
    this._errors = new Map();
  }

  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    const refresh =
      config && config.auto_refresh !== undefined
        ? Number(config.auto_refresh)
        : DEFAULT_REFRESH_SECONDS;
    this._config = {
      title: config && typeof config.title === "string" ? config.title : undefined,
      entry_id:
        config && typeof config.entry_id === "string" ? config.entry_id : undefined,
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
    if (!this._started) {
      this._started = true;
      this._start();
    }
  }

  get hass() {
    return this._hass;
  }

  get entry() {
    return this._entry;
  }

  getCardSize() {
    return 8;
  }

  connectedCallback() {
    this._restartTimer();
    if (this._colors) this._colors.start();
  }

  disconnectedCallback() {
    this._stopTimer();
    if (this._colors) this._colors.stop();
  }

  t(key) {
    return translate(this._hass, key);
  }

  // True while a client name is being typed: reloads would throw it away.
  isEditing() {
    return Boolean(this.shadowRoot.querySelector("input.nameedit"));
  }

  // Reload what is shown, e.g. after a name was saved.
  refresh() {
    return this.load();
  }

  _build() {
    this._built = true;
    const root = this.shadowRoot;
    root.appendChild(el("style", { text: STYLE }));
    this._colors = new ColorStyle(root);
    this._colors.start();
    this._card = document.createElement("ha-card");
    this._message = el("div", { className: "message", attrs: { hidden: "" } });
    this._panel = el("div", { className: "panel", attrs: { hidden: "" } });
    this._content = el("div");
    this._card.appendChild(
      el("div", { className: "body" }, [this._message, this._panel, this._content])
    );
    root.appendChild(this._card);
    this._picker = new ListPicker(this, this._panel, (context) => {
      // Highlight the row of the action while the lists are reloaded.
      if (context) flasher.mark(context.key, context.action);
      this.load();
    });
    this._renderTitle();
  }

  _renderTitle() {
    this._card.setAttribute("header", this._config.title || this.t("ov_title"));
  }

  _showMessage(key, isError) {
    this._message.textContent = key ? this.t(key) : "";
    this._message.className = isError ? "message error" : "message";
    this._message.hidden = !key;
  }

  async _start() {
    const hass = this._hass;
    if (!hass.user || !hass.user.is_admin) {
      this._showMessage("not_admin", true);
      return;
    }
    try {
      const config = await hass.callWS({ type: `${DOMAIN}/config` });
      const entries = list(config.entries);
      this._entry = this._config.entry_id
        ? entries.find((entry) => entry.entry_id === this._config.entry_id)
        : entries.find((entry) => entry.has_query_log) || entries[0];
    } catch (err) {
      this._showMessage("error", true);
      return;
    }
    if (!this._entry) {
      this._showMessage("no_entry", true);
      return;
    }
    if (!this._entry.has_query_log) {
      this._showMessage("no_query_log", false);
      return;
    }
    await loadPrefs(hass);
    await this.load();
    this._restartTimer();
  }

  async load() {
    const entry = this._entry;
    if (!entry || !entry.has_query_log) return;
    const token = ++this._token;
    try {
      const result = await this._hass.callWS({
        type: `${DOMAIN}/overview`,
        entry_id: entry.entry_id,
      });
      if (token !== this._token) return;
      this._data = {
        domains: list(result.top_domains),
        blocked: list(result.top_blocked_domains),
        clients: list(result.top_clients),
        requests: list(result.requests),
      };
      this._showMessage("", false);
    } catch (err) {
      if (token !== this._token) return;
      this._showMessage(err && err.code === "no_query_log" ? "no_query_log" : "ov_error", true);
    }
    this._render();
  }

  async _resolve(request, name) {
    const action = ACTION_OF[name];
    if (!action || typeof request.id !== "string") return;
    this._busy.add(request.id);
    this._errors.delete(request.id);
    this._render();
    try {
      await this._hass.callWS({
        type: `${DOMAIN}/resolve_request`,
        entry_id: this._entry.entry_id,
        request_id: request.id,
        action,
      });
      flasher.mark(`req:${request.id}`, name);
    } catch (err) {
      this._errors.set(request.id, (err && (err.message || err.code)) || this.t("error"));
    } finally {
      this._busy.delete(request.id);
    }
    // Show the highlighted row for a moment before the list is reloaded.
    this._render();
    if (!this._errors.has(request.id)) await flashPause();
    await this.load();
  }

  // A table of domains with their counts and, if the card may act, one icon.
  _domainTable(titleKey, items, action) {
    const type = LIST_TYPE_OF[action];
    const canAct = this._picker.lists(type).length > 0;
    const body = el("tbody");
    for (const item of items) {
      if (!item || typeof item.name !== "string") continue;
      const cells = [
        el("td", { text: item.name, className: "domain" }),
        el("td", { text: Number(item.count) || 0, className: "num" }),
      ];
      const key = `ov:${action}:${item.name}`;
      if (canAct) {
        cells.push(
          el("td", { className: "actions" }, [
            iconButton(this, action, action, () =>
              this._picker.open(type, item.name, { key, action })
            ),
          ])
        );
      }
      const line = el("tr", {}, cells);
      flasher.apply(key, line);
      body.appendChild(line);
    }
    return this._section(titleKey, body);
  }

  _clientTable(items) {
    const body = el("tbody");
    for (const item of items) {
      if (!item || typeof item.name !== "string") continue;
      body.appendChild(
        el("tr", {}, [
          clientCell(this, item.name, item.client_name, ""),
          el("td", { text: Number(item.count) || 0, className: "num" }),
        ])
      );
    }
    return this._section("ov_top_clients", body);
  }

  _requestTable(requests) {
    const body = el("tbody");
    for (const request of requests) {
      if (!request || typeof request.id !== "string") continue;
      const busy = this._busy.has(request.id);
      const actions = el("td", { className: "actions" });
      for (const name of list(request.actions)) {
        if (!Object.prototype.hasOwnProperty.call(ACTION_OF, name)) continue;
        const button = iconButton(this, name, `act_${name}`, () => this._resolve(request, name));
        setDisabled(button, busy);
        actions.appendChild(button);
      }
      const error = this._errors.get(request.id);
      if (error) actions.appendChild(el("div", { text: error, className: "rowerror" }));
      const line = el("tr", {}, [
        clientCell(this, request.client, request.client_name, request.zone),
        el("td", { text: request.domain || "", className: "domain" }),
        actions,
      ]);
      flasher.apply(`req:${request.id}`, line);
      body.appendChild(line);
    }
    return this._section("ov_requests", body, "req_none");
  }

  _section(titleKey, body, emptyKey = "ov_none") {
    const section = el("div", { className: "section" }, [
      el("h3", { text: this.t(titleKey) }),
    ]);
    if (!body.childNodes.length) {
      section.appendChild(el("div", { text: this.t(emptyKey), className: "sub" }));
    } else {
      section.appendChild(el("div", { className: "scroll" }, [el("table", {}, [body])]));
    }
    return section;
  }

  _render() {
    const data = this._data;
    this._content.replaceChildren(
      this._requestTable(data.requests),
      el("div", { className: "lists" }, [
        this._domainTable("ov_top_domains", data.domains, "block"),
        this._domainTable("ov_top_blocked", data.blocked, "allow"),
        this._clientTable(data.clients),
      ])
    );
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
      if (
        document.visibilityState === "visible" &&
        this._busy.size === 0 &&
        !this._picker.busy &&
        !this.isEditing()
      ) {
        this.load();
      }
    }, seconds * 1000);
  }
}

if (!customElements.get("ha-blocky-overview-card")) {
  customElements.define("ha-blocky-overview-card", HaBlockyOverviewCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "ha-blocky-overview-card")) {
  window.customCards.push({
    type: "ha-blocky-overview-card",
    name: "HA-Blocky overview",
    description: "Top domains, blocked domains and clients of the last 24 hours, and pending requests.",
  });
}
