/*
 * The "Known domains" part of the Requests tab: one collapsible list per
 * tracked client, loaded on demand. Clients of learning zones get a Block icon
 * per domain; the list of a client of an allowlist-only zone is read-only
 * (its known domains are on an allow list, which this card does not edit).
 * `host` offers: hass, entry, t(key), refresh().
 */

import { DOMAIN, clientCell, el } from "./ha-blocky-dom.js";
import { flasher, iconButton } from "./ha-blocky-actions.js";

const LEARNING = "learning";

export class KnownView {
  constructor(host) {
    this._host = host;
    this._clients = [];
    // Address -> { open, loaded, domains, total, mode, error, blocked }.
    this._state = new Map();
    this.element = el("div");
  }

  _t(key) {
    return this._host.t(key);
  }

  // Take the tracked clients of the latest answer and draw them.
  update(clients) {
    this._clients = Array.isArray(clients)
      ? clients.filter((item) => item && typeof item.client === "string")
      : [];
    const present = new Set(this._clients.map((item) => item.client));
    for (const address of Array.from(this._state.keys())) {
      if (!present.has(address)) this._state.delete(address);
    }
    this._render();
  }

  _stateOf(address) {
    let state = this._state.get(address);
    if (!state) {
      state = { open: false, loaded: false, domains: [], total: 0, mode: "", blocked: new Set() };
      this._state.set(address, state);
    }
    return state;
  }

  async _toggle(address) {
    const state = this._stateOf(address);
    state.open = !state.open;
    if (state.open && !state.loaded) {
      this._render();
      await this._load(address);
    } else {
      this._render();
    }
  }

  async _load(address) {
    const state = this._stateOf(address);
    state.error = "";
    try {
      const result = await this._host.hass.callWS({
        type: `${DOMAIN}/known_domains`,
        entry_id: this._host.entry.entry_id,
        client: address,
      });
      state.domains = Array.isArray(result.domains)
        ? result.domains.filter((domain) => typeof domain === "string")
        : [];
      state.total = Number(result.total) || 0;
      state.mode = typeof result.mode === "string" ? result.mode : "";
      state.loaded = true;
    } catch (err) {
      state.error = this._t("known_error");
    }
    this._render();
  }

  async _block(address, domain) {
    const state = this._stateOf(address);
    state.error = "";
    try {
      await this._host.hass.callWS({
        type: `${DOMAIN}/block_known`,
        entry_id: this._host.entry.entry_id,
        client: address,
        domain,
      });
      state.blocked.add(domain);
      flasher.mark(`known:${address}:${domain}`, "block");
    } catch (err) {
      state.error = (err && err.message) || this._t("error");
    }
    this._render();
  }

  _domainList(address, state) {
    const box = el("div", { className: "known" });
    if (state.error) box.appendChild(el("div", { text: state.error, className: "rowerror" }));
    if (!state.loaded) return box;
    const canBlock = state.mode === LEARNING;
    if (!canBlock) {
      box.appendChild(el("div", { text: this._t("known_readonly"), className: "sub" }));
    }
    if (!state.domains.length) {
      box.appendChild(el("div", { text: this._t("known_none"), className: "sub" }));
    }
    for (const domain of state.domains) {
      const line = el("div", { className: "knownrow" }, [
        el("span", { text: domain, className: "domain" }),
      ]);
      if (canBlock) {
        if (state.blocked.has(domain)) {
          line.appendChild(el("span", { text: this._t("known_blocked"), className: "sub" }));
        } else {
          line.appendChild(
            iconButton(this._host, "block", "block", () => this._block(address, domain))
          );
        }
      }
      flasher.apply(`known:${address}:${domain}`, line);
      box.appendChild(line);
    }
    return box;
  }

  _render() {
    if (!this._clients.length) {
      this.element.replaceChildren();
      return;
    }
    const body = el("tbody");
    for (const item of this._clients) {
      const state = this._stateOf(item.client);
      const toggle = el("button", {
        text: `${this._t("known_title")} (${Number(item.known) || 0})`,
        attrs: { "aria-expanded": state.open ? "true" : "false" },
      });
      toggle.addEventListener("click", () => this._toggle(item.client));
      body.appendChild(
        el("tr", {}, [
          clientCell(this._host, item.client, item.client_name, item.zone),
          el("td", {}, [toggle]),
        ])
      );
      if (state.open) {
        body.appendChild(
          el("tr", {}, [
            el("td", { attrs: { colspan: "2" } }, [this._domainList(item.client, state)]),
          ])
        );
      }
    }
    this.element.replaceChildren(
      el("h3", { text: this._t("known_title") }),
      el("div", { className: "scroll" }, [el("table", { className: "kn" }, [body])])
    );
  }
}
