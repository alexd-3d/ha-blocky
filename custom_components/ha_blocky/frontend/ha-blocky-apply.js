/*
 * "Applying changes to Blocky" and the setup check, in the Settings tab.
 *
 * Home Assistant does not write Blocky's configuration. A change of a level
 * makes the status say "N changes waiting"; the block to paste into Blocky is
 * fetched from the server on demand (it contains the secret list addresses),
 * shown in a read-only text box and copied with a button. "Check now" asks
 * Blocky to fetch its lists again and the status is read once more.
 * An opt-in (off by default, admin-only on the server) lets the integration
 * write its entries into the Blocky app's options and restart Blocky itself:
 * `ha_blocky/set_auto_apply` and `ha_blocky/apply_now`. Turning it on asks for
 * a confirmation first. The server's words are never shown: every result and
 * every refusal code has a text of the card's own.
 * `host` offers: hass, entry, t(key). `reload` reloads the whole part.
 */

import { buttonGroup, copyText, refusalText } from "./ha-blocky-controls.js";
import { DOMAIN, el } from "./ha-blocky-dom.js";
import { formatWhen, timeFormats } from "./ha-blocky-format.js";

const FORMATS = ["app", "plain"];
const CHECK_DELAY_MS = 2500;
const COPIED_MS = 2000;
const FETCH_LEVELS = ["unfiltered", "restricted", "lockdown"];
const APPLY_RESULTS = ["ok", "unchanged", "restored", "restore_failed"];

function fill(text, n) {
  return text.replace("{n}", String(n));
}

export class ApplyView {
  constructor(host, reload) {
    this._host = host;
    this._reload = reload;
    this._block = undefined;
    this._format = "app";
    this._auto = { enabled: false, available: false, last: undefined };
    this._running = false;
    this.element = el("div", { className: "stack" });
    this._build();
  }

  _t(key) {
    return this._host.t(key);
  }

  _say(message, text, isError) {
    message.textContent = text || "";
    message.className = isError ? "message error" : "message";
    message.hidden = !text;
  }

  _build() {
    const t = (key) => this._t(key);
    this._banner = el("div", { className: "banner" });
    this._message = el("div", { className: "message", attrs: { hidden: "" } });

    const show = el("button", { text: t("prot_block_show"), className: "primary" });
    show.title = t("prot_block_hint");
    show.addEventListener("click", () => this._showBlock());
    const check = el("button", { text: t("prot_check") });
    check.title = t("prot_check_hint");
    check.addEventListener("click", () => this._check(check));
    this._check_button = check;
    this._show_button = show;
    this._apply_now = el("button", { text: t("prot_apply_now"), className: "primary" });
    this._apply_now.title = t("prot_apply_now_hint");
    this._apply_now.hidden = true;
    this._apply_now.addEventListener("click", () => this._applyNow());

    this._formats = buttonGroup(
      t("prot_block_format"),
      FORMATS.map((value) => ({ value, label: t(`prot_block_${value}`) })),
      this._format,
      (value) => {
        this._format = value;
        this._drawBlock();
      }
    );
    this._text = el("textarea", {
      attrs: {
        readonly: "",
        rows: "14",
        spellcheck: "false",
        "aria-label": t("prot_block_title"),
      },
    });
    this._copy = el("button", { text: t("prot_copy") });
    this._copy.addEventListener("click", () => this._copyBlock());
    this._notes = el("div", { className: "hint" });
    this._blockBox = el("div", { className: "blockbox", attrs: { hidden: "" } }, [
      el("div", { className: "blockhead" }, [this._formats, this._copy]),
      this._text,
      this._notes,
    ]);

    // The opt-in: a switch, its reason when unavailable, and an inline
    // confirmation row (no browser dialog) before it is turned on.
    this._auto_box = el("input", {
      attrs: { type: "checkbox", "aria-label": t("prot_auto_label") },
    });
    this._auto_box.addEventListener("change", () => this._toggleAuto());
    this._auto_reason = el("div", { className: "hint", attrs: { hidden: "" } });
    const yes = el("button", { text: t("prot_auto_confirm_yes"), className: "primary" });
    yes.addEventListener("click", () => this._setAuto(true));
    const no = el("button", { text: t("cancel") });
    no.addEventListener("click", () => this._askAuto(false));
    this._auto_confirm = el("div", { className: "banner waiting", attrs: { hidden: "" } }, [
      el("div", { text: t("prot_auto_confirm") }),
      el("div", { className: "btnrow" }, [yes, no]),
    ]);
    const auto = el("div", { className: "field" }, [
      el("label", { className: "flabel" }, [
        this._auto_box,
        el("span", { text: ` ${t("prot_auto_label")}` }),
      ]),
      el("div", { className: "hint", text: t("prot_auto_hint") }),
      this._auto_reason,
      this._auto_confirm,
    ]);

    const apply = el("section", { className: "scard" }, [
      el("h3", { text: t("prot_apply_title") }),
      el("div", { className: "hint", text: t("prot_apply_hint") }),
      this._banner,
      auto,
      el("div", { className: "btnrow" }, [this._apply_now, show, check]),
      el("div", { className: "hint", text: t("prot_check_hint") }),
      this._blockBox,
      this._message,
    ]);

    // The setup check is the last part of the same card.
    this._setup = el("div");
    apply.append(
      el("div", { className: "subsec" }, [
        el("h4", { text: t("prot_setup_title") }),
        el("div", { className: "hint", text: t("prot_setup_hint") }),
        this._setup,
      ])
    );
    this.element.append(apply);
  }

  // Draw the status and the setup check from the latest answer. `extra` holds
  // the opt-in: { auto_apply, apply_available, last_apply }.
  update(status, setup, extra) {
    const t = (key) => this._t(key);
    const more = extra && typeof extra === "object" ? extra : {};
    this._auto = {
      enabled: more.auto_apply === true,
      available: more.apply_available === true,
      last: more.last_apply && typeof more.last_apply === "object" ? more.last_apply : undefined,
    };
    this._drawAuto();
    const state = status && typeof status === "object" ? status : {};
    const waiting = Number(state.waiting) || 0;
    if (state.applied === true) {
      this._banner.textContent = t("prot_applied");
      this._banner.className = "banner ok";
    } else {
      const base = fill(t(waiting === 1 ? "prot_waiting_one" : "prot_waiting"), waiting);
      const note = state.fetched_since_start === true ? "" : ` ${t("prot_waiting_restart")}`;
      this._banner.textContent = `${base}${note}`;
      this._banner.className = "banner waiting";
    }

    const info = setup && typeof setup === "object" ? setup : {};
    const lists = state.lists && typeof state.lists === "object" ? state.lists : {};
    const yesNo = (value) => (value === true ? t("prot_yes") : t("prot_no"));
    const rows = [
      [t("prot_setup_api"), yesNo(info.api_ok)],
      [t("prot_setup_log"), info.log_ok === null ? t("prot_unused") : yesNo(info.log_ok)],
    ];
    for (const level of FETCH_LEVELS) {
      const entry = lists[level] && typeof lists[level] === "object" ? lists[level] : {};
      rows.push([
        `${t("prot_setup_fetched")} (${t(`level_${level}`)})`,
        entry.current === true
          ? t("prot_yes")
          : entry.fetched === true
            ? t("prot_old")
            : t("prot_no"),
      ]);
    }
    rows.push([t("prot_setup_applied"), yesNo(state.applied)]);
    rows.push([t("prot_setup_last_apply"), this._lastApply()]);
    this._setup.replaceChildren(
      el(
        "table",
        { className: "setupcheck" },
        [
          el(
            "tbody",
            {},
            rows.map(([label, value]) =>
              el("tr", {}, [el("td", { text: label }), el("td", { text: value })])
            )
          ),
        ]
      )
    );
  }

  // "Result, local time" of the last automatic apply, or "never".
  _lastApply() {
    const last = this._auto.last;
    if (!last || !APPLY_RESULTS.includes(last.result)) return this._t("prot_never");
    const hass = this._host.hass || {};
    const formats = timeFormats(hass.locale, hass.language);
    const when = formatWhen(formats.dateTime, last.at);
    const time = when ? `, ${when}` : "";
    return `${this._t(`apply_result_${last.result}`)}${time}`;
  }

  _drawAuto() {
    const { enabled, available } = this._auto;
    this._auto_box.checked = enabled;
    this._auto_box.disabled = !available || this._running;
    this._auto_reason.textContent = available ? "" : this._t("prot_auto_unavailable");
    this._auto_reason.hidden = available;
    if (!available || enabled) this._auto_confirm.hidden = true;
    this._apply_now.hidden = !(enabled && available);
    this._apply_now.disabled = this._running;
    this._show_button.disabled = this._running;
    this._check_button.disabled = this._running;
  }

  _askAuto(show) {
    this._auto_confirm.hidden = !show;
    this._auto_box.checked = this._auto.enabled;
  }

  // Off at once; on only after the confirmation row.
  _toggleAuto() {
    if (this._auto_box.checked) {
      this._askAuto(true);
    } else {
      this._setAuto(false);
    }
  }

  async _setAuto(enabled) {
    try {
      await this._host.hass.callWS({
        type: `${DOMAIN}/set_auto_apply`,
        entry_id: this._host.entry.entry_id,
        enabled,
      });
      this._say(this._message, "", false);
    } catch (err) {
      this._say(this._message, refusalText(this._host, err, "prot_error"), true);
    }
    this._auto_confirm.hidden = true;
    await this._reload();
  }

  // Write the entries into the Blocky app's options and restart Blocky.
  async _applyNow() {
    this._running = true;
    this._drawAuto();
    this._say(this._message, this._t("prot_apply_running"), false);
    let text = "";
    let failed = false;
    try {
      const answer = await this._host.hass.callWS({
        type: `${DOMAIN}/apply_now`,
        entry_id: this._host.entry.entry_id,
      });
      const result = answer && answer.result;
      const known = APPLY_RESULTS.includes(result);
      failed = !known || result === "restored" || result === "restore_failed";
      text = known ? this._t(`apply_result_${result}`) : this._t("prot_error");
    } catch (err) {
      failed = true;
      text = refusalText(this._host, err, "prot_error");
    }
    this._running = false;
    this._drawAuto();
    this._say(this._message, text, failed);
    await this._reload();
  }

  async _showBlock() {
    const entry = this._host.entry;
    try {
      this._block = await this._host.hass.callWS({
        type: `${DOMAIN}/get_block`,
        entry_id: entry.entry_id,
      });
    } catch (err) {
      this._say(this._message, refusalText(this._host, err, "prot_error"), true);
      return;
    }
    this._say(this._message, "", false);
    this._drawBlock();
  }

  _drawBlock() {
    const block = this._block;
    if (!block || typeof block[this._format] !== "string") return;
    this._text.value = block[this._format];
    this._blockBox.hidden = false;
    const notes = [this._t("prot_block_secret")];
    if (block.base_known === false) notes.push(this._t("prot_block_base_unknown"));
    this._notes.textContent = notes.join(" ");
  }

  async _copyBlock() {
    const done = await copyText(this._text.value);
    this._say(this._message, done ? "" : this._t("help_copy_failed"), !done);
    if (done) {
      this._copy.textContent = this._t("help_copied");
      setTimeout(() => {
        this._copy.textContent = this._t("prot_copy");
      }, COPIED_MS);
    }
  }

  // Ask Blocky to fetch its lists again, then look at the status once more.
  async _check(button) {
    const id = this._host.entry && this._host.entry.refresh_lists_entity;
    if (typeof id !== "string") {
      this._say(this._message, this._t("prot_check_unavailable"), true);
      return;
    }
    button.disabled = true;
    try {
      await this._host.hass.callService("button", "press", { entity_id: id });
      await new Promise((resolve) => setTimeout(resolve, CHECK_DELAY_MS));
      this._say(this._message, "", false);
    } catch (err) {
      this._say(this._message, this._t("prot_error"), true);
    }
    button.disabled = false;
    await this._reload();
  }
}
