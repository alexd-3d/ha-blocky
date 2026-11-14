/*
 * The "Rules" part of the Settings tab: the entries of the four fixed lists
 * (Always allow, Always block, the Restricted block list and the Lockdown
 * allow list), with Add and Remove. The names of the lists are the card's own
 * texts; the server checks every domain again.
 * `host` offers: hass, entry, t(key).
 */

import { glyphButton, refusalText } from "./ha-blocky-controls.js";
import { DOMAIN, el } from "./ha-blocky-dom.js";

// The lists, in the order they are shown. Names are only ever looked up here.
const LISTS = ["allow_default", "deny_default", "restricted_deny", "lockdown_allow"];

export class RulesView {
  constructor(host) {
    this._host = host;
    this._token = 0;
    this._lists = new Map();
    // The lists the user has opened; a redraw keeps them open.
    this._open = new Set();
    this._body = el("div");
    this._message = el("div", { className: "message", attrs: { hidden: "" } });
    this.element = el("section", { className: "scard" }, [
      el("h3", { text: host.t("prot_rules_title") }),
      el("div", { className: "hint", text: host.t("prot_rules_hint") }),
      el("div", { className: "hint", text: host.t("shared_rule_hint") }),
      this._body,
      this._message,
    ]);
  }

  _t(key) {
    return this._host.t(key);
  }

  _say(text, isError) {
    this._message.textContent = text || "";
    this._message.className = isError ? "message error" : "message";
    this._message.hidden = !text;
  }

  async load() {
    const entry = this._host.entry;
    if (!entry) return;
    const token = ++this._token;
    try {
      const result = await this._host.hass.callWS({
        type: `${DOMAIN}/rules`,
        entry_id: entry.entry_id,
      });
      if (token !== this._token) return;
      this._lists.clear();
      for (const item of Array.isArray(result.lists) ? result.lists : []) {
        if (item && LISTS.includes(item.name)) this._lists.set(item.name, item);
      }
      this._render();
    } catch (err) {
      if (token !== this._token) return;
      this._say(this._t("prot_load_error"), true);
    }
  }

  async _change(kind, name, domain) {
    try {
      await this._host.hass.callWS({
        type: `${DOMAIN}/rules_${kind}`,
        entry_id: this._host.entry.entry_id,
        list: name,
        domain,
      });
      this._say("", false);
      await this.load();
      return true;
    } catch (err) {
      this._say(refusalText(this._host, err, "prot_error"), true);
      return false;
    }
  }

  _listBox(name) {
    const t = (key) => this._t(key);
    const data = this._lists.get(name) || {};
    const entries = Array.isArray(data.entries)
      ? data.entries.filter((value) => typeof value === "string")
      : [];
    const total = Number(data.total) || entries.length;
    const rows = entries.map((domain) => {
      const remove = glyphButton(t("prot_rules_remove"), "rule_remove");
      remove.addEventListener("click", () => this._change("remove", name, domain));
      return el("div", { className: "rulerow" }, [
        el("span", { text: domain, className: "domain", attrs: { title: domain } }),
        remove,
      ]);
    });
    if (!entries.length) rows.push(el("div", { className: "sub", text: t("prot_rules_empty") }));
    if (total > entries.length) {
      rows.push(
        el("div", { className: "sub", text: t("prot_rules_more").replace("{n}", total - entries.length) })
      );
    }

    const input = el("input", {
      attrs: {
        type: "text",
        maxlength: 260,
        autocomplete: "off",
        spellcheck: "false",
        placeholder: t("prot_rules_placeholder"),
        "aria-label": t(`list_${name}`),
        title: t(`prot_rule_${name}`),
      },
    });
    const add = el("button", { text: t("prot_rules_add") });
    const submit = async () => {
      const value = input.value.trim();
      if (!value) return;
      if (await this._change("add", name, value)) input.value = "";
    };
    add.addEventListener("click", submit);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        submit();
      }
    });
    const parts = [
      el("summary", { text: `${t(`list_${name}`)} (${total})` }),
      el("div", { className: "hint", text: t(`prot_rule_${name}`) }),
    ];
    if (data.exact_only === true) {
      parts.push(el("div", { className: "hint", text: t("prot_rules_exact") }));
    }
    parts.push(...rows, el("div", { className: "btnrow" }, [input, add]));
    const details = el("details", { className: "sec" }, parts);
    if (this._open.has(name)) details.setAttribute("open", "");
    details.addEventListener("toggle", () => {
      if (details.open) this._open.add(name);
      else this._open.delete(name);
    });
    return details;
  }

  _render() {
    this._body.replaceChildren(...LISTS.map((name) => this._listBox(name)));
    this._say("", false);
  }
}
