/*
 * "Applying changes to Blocky" and the setup check, in the Settings tab.
 *
 * Home Assistant does not write Blocky's configuration. A change of a level
 * makes the status say "N changes waiting"; the block to paste into Blocky is
 * fetched from the server on demand (it contains the secret list addresses),
 * shown in a read-only text box and copied with a button. "Check now" asks
 * Blocky to fetch its lists again and the status is read once more.
 * `host` offers: hass, entry, t(key). `reload` reloads the whole part.
 */

import { buttonGroup, copyText, refusalText } from "./ha-blocky-controls.js";
import { DOMAIN, el } from "./ha-blocky-dom.js";

const FORMATS = ["app", "plain"];
const CHECK_DELAY_MS = 2500;
const COPIED_MS = 2000;
const FETCH_LEVELS = ["unfiltered", "restricted", "lockdown"];

function fill(text, n) {
  return text.replace("{n}", String(n));
}

export class ApplyView {
  constructor(host, reload) {
    this._host = host;
    this._reload = reload;
    this._block = undefined;
    this._format = "app";
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
      this._formats,
      this._text,
      el("div", { className: "btnrow" }, [this._copy]),
      this._notes,
    ]);

    const apply = el("section", { className: "scard" }, [
      el("h3", { text: t("prot_apply_title") }),
      el("div", { className: "hint", text: t("prot_apply_hint") }),
      this._banner,
      el("div", { className: "btnrow" }, [show, check]),
      el("div", { className: "hint", text: t("prot_check_hint") }),
      this._blockBox,
      this._message,
    ]);

    this._setup = el("div");
    const setup = el("section", { className: "scard" }, [
      el("h3", { text: t("prot_setup_title") }),
      el("div", { className: "hint", text: t("prot_setup_hint") }),
      this._setup,
    ]);
    this.element.append(apply, setup);
  }

  // Draw the status and the setup check from the latest answer.
  update(status, setup) {
    const t = (key) => this._t(key);
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
