/*
 * The "Known domains" part of the Requests tab: one native <details> per
 * tracked client (the summary shows the client and the number of known
 * domains), loaded on the first opening. Clients of learning zones get a Block icon
 * per domain; the list of a client of an allowlist-only zone is read-only
 * (its known domains are on an allow list, which this card does not edit).
 * `host` offers: hass, entry, t(key), refresh().
 */

import { DOMAIN, clientLines, el } from "./ha-blocky-dom.js";
import { UI_ICONS, flasher, haIcon, iconButton } from "./ha-blocky-actions.js";

const LEARNING = "learning";

export class KnownView {
  constructor(host) {
    this._host = host;
    this._clients = [];
    // Address -> { open, loaded, loading, domains, total, mode, error, blocked, body }.
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
      state = {
        open: false,
        loaded: false,
        loading: false,
        domains: [],
        total: 0,
        mode: "",
        blocked: new Set(),
        body: undefined,
      };
      this._state.set(address, state);
    }
    return state;
  }

  // The <details> of a client opened or closed; the list loads on the first opening.
  _onToggle(address, details) {
    const state = this._stateOf(address);
    state.open = details.open;
    if (state.open && !state.loaded && !state.loading) this._load(address);
  }

  // Draw the list of one client into its body (the rest stays as it is).
  _fill(address) {
    const state = this._stateOf(address);
    if (state.body) state.body.replaceChildren(this._domainList(address, state));
  }

  async _load(address) {
    const state = this._stateOf(address);
    state.error = "";
    state.loading = true;
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
    state.loading = false;
    this._fill(address);
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
    this._fill(address);
  }

  _domainList(address, state) {
    const box = el("div", { className: "known" });
    if (state.error) box.appendChild(el("div", { text: state.error, className: "rowerror" }));
    if (state.loading && !state.loaded) {
      box.appendChild(el("div", { text: this._t("loading"), className: "sub" }));
    }
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
        el("span", { text: domain, className: "domain", attrs: { title: domain } }),
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
    const list = el("div", { className: "kn" });
    for (const item of this._clients) {
      const address = item.client;
      const state = this._stateOf(address);
      const known = Number(item.known) || 0;
      const summary = el("summary", { className: "ksum" }, [
        haIcon(UI_ICONS, "chevron", "karrow"),
        el("div", { className: "kname" }, clientLines(address, item.client_name, item.zone)),
        el("span", {
          text: String(known),
          className: "kcount",
          attrs: { title: `${this._t("known_title")}: ${known}` },
        }),
      ]);
      state.body = el("div", { className: "kbody" });
      const details = el("details", { className: "kitem" }, [summary, state.body]);
      if (state.open) details.setAttribute("open", "");
      details.addEventListener("toggle", () => this._onToggle(address, details));
      this._fill(address);
      list.appendChild(details);
    }
    this.element.replaceChildren(el("h3", { text: this._t("known_title") }), list);
  }
}
