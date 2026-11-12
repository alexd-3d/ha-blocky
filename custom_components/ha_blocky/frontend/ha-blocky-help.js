/*
 * The "Help" tab: a short quick start, a few answers and three well-known
 * blocklist sources. All texts are the card's own (ha-blocky-i18n*.js). The
 * sources are plain selectable text with a copy button: never links, never
 * fetched. `host` offers: t(key).
 */

import { el } from "./ha-blocky-dom.js";
import { BLOCKLISTS } from "./ha-blocky-i18n-help.js";

const TAB_KEYS = ["dashboard", "log", "requests", "settings"];
const FAQ = ["delay", "pause", "name", "nodb", "sidebar"];
const COPIED_MS = 2000;

// Write text to the clipboard; false when the browser does not allow it.
async function copyText(text) {
  const clipboard = typeof navigator === "undefined" ? undefined : navigator.clipboard;
  if (!clipboard || typeof clipboard.writeText !== "function") return false;
  try {
    await clipboard.writeText(text);
    return true;
  } catch (err) {
    return false;
  }
}

export class HelpView {
  constructor(host, container) {
    this._host = host;
    container.appendChild(this._build());
  }

  _t(key) {
    return this._host.t(key);
  }

  // A collapsible section: a summary and its content.
  _section(title, children, open) {
    const details = el("details", { className: "sec" }, [
      el("summary", { text: title }),
      ...children,
    ]);
    if (open) details.setAttribute("open", "");
    return details;
  }

  _source(source) {
    const message = el("div", { className: "rowerror", attrs: { hidden: "" } });
    const button = el("button", { text: this._t("help_copy"), attrs: { type: "button" } });
    button.addEventListener("click", async () => {
      const done = await copyText(source.url);
      message.textContent = done ? "" : this._t("help_copy_failed");
      message.hidden = done;
      if (done) {
        button.textContent = this._t("help_copied");
        setTimeout(() => {
          button.textContent = this._t("help_copy");
        }, COPIED_MS);
      }
    });
    return el("div", { className: "srcrow" }, [
      el("div", { text: source.name, className: "srcname" }),
      el("span", { text: source.url, className: "srcurl" }),
      button,
      message,
    ]);
  }

  _build() {
    const t = (key) => this._t(key);
    const quick = this._section(
      t("help_quick_title"),
      [
        el(
          "ul",
          {},
          TAB_KEYS.map((tab) => el("li", { text: t(`help_tab_${tab}`) }))
        ),
      ],
      true
    );
    const names = this._section(t("help_names_title"), [
      el("p", { text: t("help_names_body") }),
    ]);
    const actions = this._section(t("help_actions_title"), [
      el("p", { text: t("help_actions_body") }),
    ]);
    const zones = this._section(t("help_zones_title"), [
      el("p", { text: t("help_zones_body") }),
    ]);
    const faq = this._section(
      t("help_faq_title"),
      FAQ.map((name) =>
        el("details", { className: "sec" }, [
          el("summary", { text: t(`help_faq_${name}_q`) }),
          el("p", { text: t(`help_faq_${name}_a`) }),
        ])
      )
    );
    const lists = this._section(t("help_lists_title"), [
      el("p", { text: t("help_lists_body") }),
      ...BLOCKLISTS.map((source) => this._source(source)),
    ]);
    return el("div", { className: "helppage" }, [quick, names, actions, zones, faq, lists]);
  }
}
