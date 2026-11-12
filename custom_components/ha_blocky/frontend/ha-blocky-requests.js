/*
 * The "Requests" tab: requests for new domains waiting for a decision and the
 * phase of the clients of allowlist-only zones, then the known domains of
 * every tracked client.
 * `host` offers: hass, entry, t(key), refresh(), isEditing().
 */

import { ACTION_OF } from "./ha-blocky-actions.js";
import { DOMAIN, clientCell, el } from "./ha-blocky-dom.js";
import { KnownView } from "./ha-blocky-known.js";

const PHASES = ["learning", "locked"];
const SENSOR_FALLBACK = "sensor.ha_blocky_pending_domain_requests";

export class RequestsView {
  constructor(host, container) {
    this._host = host;
    this._reqs = [];
    this._phases = [];
    this._busy = new Set();
    this._errors = new Map();
    this._token = 0;
    this._sensorId = undefined;
    this._sensorState = undefined;
    this._active = false;

    this._message = el("div", { className: "message", attrs: { hidden: "" } });
    this._body = el("div");
    this._known = new KnownView(host);
    container.append(this._message, this._body, this._known.element);
  }

  _t(key) {
    return this._host.t(key);
  }

  // Whether the tab is the one shown; only then does it reload on its own.
  setActive(active) {
    this._active = active;
    if (active) this.load();
  }

  // Reload the requests when the pending-requests sensor changes.
  watchSensor() {
    const hass = this._host.hass;
    if (!this._sensorId) {
      const entities = hass.entities || {};
      for (const [id, info] of Object.entries(entities)) {
        if (info && info.platform === DOMAIN && info.translation_key === "pending_requests") {
          this._sensorId = id;
          break;
        }
      }
      if (!this._sensorId && hass.states && hass.states[SENSOR_FALLBACK]) {
        this._sensorId = SENSOR_FALLBACK;
      }
    }
    const sensor = this._sensorId && hass.states ? hass.states[this._sensorId] : undefined;
    const state = sensor ? sensor.state : undefined;
    if (state === this._sensorState) return;
    const first = this._sensorState === undefined;
    this._sensorState = state;
    if (!first && this._active && this._busy.size === 0 && !this._host.isEditing()) {
      this.load();
    }
  }

  _age(created) {
    const time = new Date(created).getTime();
    if (Number.isNaN(time)) return "";
    const minutes = Math.max(0, Math.round((Date.now() - time) / 60000));
    return minutes < 120
      ? `${minutes} ${this._t("unit_min")}`
      : `${Math.round(minutes / 60)} ${this._t("unit_h")}`;
  }

  async load() {
    const entry = this._host.entry;
    if (!entry || !entry.has_query_log) return;
    const token = ++this._token;
    try {
      const result = await this._host.hass.callWS({
        type: `${DOMAIN}/requests`,
        entry_id: entry.entry_id,
      });
      if (token !== this._token) return;
      this._reqs = Array.isArray(result.requests) ? result.requests : [];
      this._phases = Array.isArray(result.clients) ? result.clients : [];
      this._known.update(result.tracked);
      this._message.hidden = true;
    } catch (err) {
      if (token !== this._token) return;
      this._message.textContent = this._t("req_error");
      this._message.className = "message error";
      this._message.hidden = false;
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
      await this._host.hass.callWS({
        type: `${DOMAIN}/resolve_request`,
        entry_id: this._host.entry.entry_id,
        request_id: request.id,
        action,
      });
    } catch (err) {
      this._errors.set(request.id, (err && (err.message || err.code)) || this._t("error"));
    } finally {
      this._busy.delete(request.id);
    }
    await this.load();
  }

  async _setPhase(client, phase) {
    if (!PHASES.includes(phase) || typeof client !== "string") return;
    const key = `phase:${client}`;
    this._busy.add(key);
    this._errors.delete(key);
    this._render();
    try {
      await this._host.hass.callService(DOMAIN, "set_client_phase", {
        config_entry_id: this._host.entry.entry_id,
        client,
        phase,
      });
    } catch (err) {
      this._errors.set(key, (err && err.message) || this._t("error"));
    } finally {
      this._busy.delete(key);
    }
    await this.load();
  }

  _render() {
    const fragment = document.createDocumentFragment();
    if (!this._reqs.length) {
      fragment.appendChild(el("div", { text: this._t("req_none"), className: "message" }));
    } else {
      const head = el("tr", {}, [
        el("th", { text: this._t("req_client"), className: "plain" }),
        el("th", { text: this._t("req_zone"), className: "plain" }),
        el("th", { text: this._t("req_domain"), className: "plain" }),
        el("th", { text: this._t("req_age"), className: "plain" }),
        el("th", { className: "plain" }),
      ]);
      const body = el("tbody");
      for (const request of this._reqs) {
        const busy = this._busy.has(request.id);
        const actions = el("td", { className: "buttons" });
        const names = Array.isArray(request.actions) ? request.actions : [];
        for (const name of names) {
          if (!Object.prototype.hasOwnProperty.call(ACTION_OF, name)) continue;
          const button = el("button", {
            text: this._t(`act_${name}`),
            className: name === "approve" || name === "block" ? "primary" : "",
          });
          button.disabled = busy;
          button.addEventListener("click", () => this._resolve(request, name));
          actions.appendChild(button);
        }
        const error = this._errors.get(request.id);
        if (error) actions.appendChild(el("div", { text: error, className: "rowerror" }));
        body.appendChild(
          el("tr", {}, [
            clientCell(this._host, request.client, request.client_name, ""),
            el("td", { text: request.zone || "" }),
            el("td", { text: request.domain || "", className: "domain" }),
            el("td", { text: this._age(request.created) }),
            actions,
          ])
        );
      }
      fragment.appendChild(
        el("div", { className: "scroll" }, [
          el("table", {}, [el("thead", {}, [head]), body]),
        ])
      );
    }

    if (this._phases.length) {
      fragment.appendChild(el("h3", { text: this._t("req_phases") }));
      const body = el("tbody");
      for (const entry of this._phases) {
        const key = `phase:${entry.client}`;
        const select = el(
          "select",
          { attrs: { "aria-label": this._t("req_phases") } },
          PHASES.map((phase) =>
            el("option", { text: this._t(`phase_${phase}`), attrs: { value: phase } })
          )
        );
        select.value = PHASES.includes(entry.phase) ? entry.phase : "learning";
        select.disabled = this._busy.has(key);
        select.addEventListener("change", () => this._setPhase(entry.client, select.value));
        const control = el("td", {}, [select]);
        const error = this._errors.get(key);
        if (error) control.appendChild(el("div", { text: error, className: "rowerror" }));
        body.appendChild(
          el("tr", {}, [
            clientCell(this._host, entry.client, entry.client_name, entry.zone),
            control,
          ])
        );
      }
      fragment.appendChild(el("div", { className: "scroll" }, [el("table", {}, [body])]));
    }
    this._body.replaceChildren(fragment);
  }
}
