/*
 * The "Protection" part of the Settings tab: the clients with their level, the
 * notifications, the list groups of the Standard level, the rules, the block to
 * paste into Blocky and the setup check.
 *
 * Everything is written through admin-only commands (`ha_blocky/levels`,
 * `set_client_level`, `set_base_groups`, `set_notify`); the server validates
 * every value again. Texts are the card's own, looked up by key; the only text
 * that comes from the server is a client's name and address, written with
 * textContent.
 * `host` offers: hass, entry, t(key), reloadEntry().
 */

import { buttonGroup, field, refusalText } from "./ha-blocky-controls.js";
import { ApplyView } from "./ha-blocky-apply.js";
import { DOMAIN, clientLines, el, LEVELS } from "./ha-blocky-dom.js";
import { RulesView } from "./ha-blocky-rules.js";

const NOTIFY_LEVELS = ["restricted", "lockdown"];

export class ProtectionView {
  constructor(host) {
    this._host = host;
    this._clients = [];
    this._token = 0;
    this._baseTouched = false;
    this.element = el("div");
    this._apply = new ApplyView(host, () => this.load());
    this._rules = new RulesView(host);
    this._build();
  }

  _t(key) {
    return this._host.t(key);
  }

  _section(titleKey, hintKey) {
    const message = el("div", { className: "message", attrs: { hidden: "" } });
    const root = el("section", { className: "scard" }, [
      el("h3", { text: this._t(titleKey) }),
      el("div", { className: "hint", text: this._t(hintKey) }),
    ]);
    return { root, message };
  }

  _say(message, text, isError) {
    message.textContent = text || "";
    message.className = isError ? "message error" : "message";
    message.hidden = !text;
  }

  _build() {
    const t = (key) => this._t(key);

    // Clients and levels.
    const clients = this._section("prot_title", "prot_hint");
    this._clientsMessage = clients.message;
    this._table = el("div", { className: "scroll" });
    const legend = el(
      "ul",
      { className: "levellegend" },
      LEVELS.map((level) =>
        el("li", {}, [
          el("strong", { text: `${t(`level_${level}`)}: ` }),
          el("span", { text: t(`level_text_${level}`) }),
        ])
      )
    );
    clients.root.append(
      el("div", { className: "hint", text: t("prot_level_hint") }),
      this._table,
      legend,
      el("div", { className: "hint", text: t("shared_rule_hint") }),
      clients.message
    );

    // Notifications.
    const notify = this._section("prot_notify_title", "prot_notify_hint");
    this._notifyMessage = notify.message;
    this._notifyGroups = {};
    for (const level of NOTIFY_LEVELS) {
      const group = buttonGroup(
        t(`prot_notify_${level}`),
        [
          { value: false, label: t("prot_notify_off") },
          { value: true, label: t("prot_notify_each") },
        ],
        level === "lockdown",
        (value) => this._setNotify(level, value)
      );
      this._notifyGroups[level] = group;
      notify.root.append(
        el("div", { className: "group" }, [
          el("div", { className: "flabel", text: t(`prot_notify_${level}`) }),
          group,
        ])
      );
    }
    notify.root.append(
      el("div", { className: "hint", text: t("prot_notify_control_hint") }),
      notify.message
    );

    // The list groups of the Standard level.
    const base = this._section("prot_base_title", "prot_base_hint");
    this._baseMessage = base.message;
    this._baseInput = el("input", {
      className: "widefield",
      attrs: { type: "text", maxlength: 1100, autocomplete: "off", spellcheck: "false" },
    });
    this._baseInput.addEventListener("input", () => {
      this._baseTouched = true;
    });
    const save = el("button", { text: t("set_save"), className: "primary" });
    save.addEventListener("click", () => this._saveBase());
    this._baseWarning = el("div", {
      className: "basewarning banner waiting",
      text: t("prot_base_default_warning"),
      attrs: { hidden: "" },
    });
    base.root.append(
      this._baseWarning,
      field(t("prot_base_label"), this._baseInput, t("prot_base_field_hint")),
      el("div", { className: "btnrow" }, [save]),
      base.message
    );

    this.element.append(
      clients.root,
      notify.root,
      base.root,
      this._rules.element,
      this._apply.element
    );
  }

  async load() {
    const entry = this._host.entry;
    if (!entry) return;
    const token = ++this._token;
    try {
      const result = await this._host.hass.callWS({
        type: `${DOMAIN}/levels`,
        entry_id: entry.entry_id,
      });
      if (token !== this._token) return;
      this._clients = Array.isArray(result.clients) ? result.clients : [];
      this._renderClients();
      const notify = result.notify && typeof result.notify === "object" ? result.notify : {};
      for (const level of NOTIFY_LEVELS) {
        this._notifyGroups[level].mark(notify[level] === true);
      }
      if (!this._baseTouched && Array.isArray(result.base_groups)) {
        this._baseInput.value = result.base_groups
          .filter((name) => typeof name === "string")
          .join(", ");
      }
      // Never saved: the built-in default may not match the names in Blocky.
      this._baseWarning.hidden = result.base_groups_saved !== false;
      this._apply.update(result.status, result.setup);
      this._say(this._clientsMessage, "", false);
    } catch (err) {
      if (token !== this._token) return;
      this._say(this._clientsMessage, this._t("prot_load_error"), true);
    }
    this._rules.load();
  }

  async _send(payload, message) {
    try {
      await this._host.hass.callWS({
        entry_id: this._host.entry.entry_id,
        ...payload,
      });
      return true;
    } catch (err) {
      this._say(message, refusalText(this._host, err, "prot_error"), true);
      return false;
    }
  }

  async _setLevel(address, level, ask) {
    const payload = { type: `${DOMAIN}/set_client_level`, client: address, level };
    if (typeof ask === "boolean") payload.ask = ask;
    if (await this._send(payload, this._clientsMessage)) {
      this._say(this._clientsMessage, "", false);
    }
    await this.load();
  }

  async _setNotify(level, enabled) {
    const done = await this._send(
      { type: `${DOMAIN}/set_notify`, level, enabled },
      this._notifyMessage
    );
    this._say(this._notifyMessage, done ? this._t("set_saved") : "", false);
    if (!done) await this.load();
  }

  async _saveBase() {
    const groups = this._baseInput.value
      .split(",")
      .map((name) => name.trim())
      .filter((name) => name !== "");
    const done = await this._send(
      { type: `${DOMAIN}/set_base_groups`, groups },
      this._baseMessage
    );
    if (done) {
      this._baseTouched = false;
      this._say(this._baseMessage, this._t("set_saved"), false);
    }
    await this.load();
  }

  // The name of a client, edited in place. A name typed here is stored by the
  // server (empty clears it); a name that comes from a device tracker is shown
  // as the placeholder, not as a value, so it is never saved by accident.
  _nameEditor(item) {
    const t = (key) => this._t(key);
    const manual = item.name_source === "manual" && typeof item.client_name === "string";
    const device = item.name_source === "device" && typeof item.client_name === "string";
    const input = el("input", {
      className: "nameedit",
      attrs: {
        type: "text",
        maxlength: 64,
        autocomplete: "off",
        spellcheck: "false",
        "aria-label": t("client_edit"),
        title: t("client_edit"),
        placeholder: device ? item.client_name : t("client_name_placeholder"),
      },
    });
    input.value = manual ? item.client_name : "";
    const error = el("div", { className: "rowerror", attrs: { hidden: "" } });
    // "change" fires when the field is left or Enter is pressed, and only if
    // the text changed.
    input.addEventListener("change", async () => {
      input.disabled = true;
      try {
        await this._host.hass.callWS({
          type: `${DOMAIN}/set_client_name`,
          ip: item.address,
          name: input.value.trim(),
        });
      } catch (err) {
        // The card's own words for the refusal; the typed value is not echoed.
        error.textContent = refusalText(this._host, err, "prot_error");
        error.hidden = false;
        input.disabled = false;
        return;
      }
      if (typeof this._host.refresh === "function") this._host.refresh();
      await this.load();
    });
    return [input, error];
  }

  _renderClients() {
    const t = (key) => this._t(key);
    if (!this._clients.length) {
      this._table.replaceChildren(el("div", { className: "message", text: t("prot_none") }));
      return;
    }
    const body = el("tbody");
    for (const item of this._clients) {
      if (!item || typeof item.address !== "string") continue;
      const level = LEVELS.includes(item.level) ? item.level : "standard";
      const select = el(
        "select",
        { attrs: { "aria-label": t("prot_level"), title: t("prot_level_hint") } },
        LEVELS.map((name) => el("option", { text: t(`level_${name}`), attrs: { value: name } }))
      );
      select.value = level;
      select.addEventListener("change", () => this._setLevel(item.address, select.value));
      const cells = [
        el("td", { className: "client" }, clientLines(item.address, "", "")),
        el("td", { className: "nametd" }, this._nameEditor(item)),
        el("td", {}, [select]),
      ];
      const askCell = el("td", { className: "askcell" });
      if (level === "lockdown") {
        const box = el("input", {
          attrs: { type: "checkbox", "aria-label": t("prot_ask"), title: t("prot_ask_hint") },
        });
        box.checked = item.ask === true;
        box.addEventListener("change", () => this._setLevel(item.address, "lockdown", box.checked));
        askCell.append(box, el("span", { text: ` ${t("prot_ask")}`, className: "sub" }));
      }
      cells.push(askCell);
      body.appendChild(el("tr", {}, cells));
    }
    this._table.replaceChildren(el("table", { className: "prot" }, [body]));
  }
}
