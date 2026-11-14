/*
 * The filter bar of the Query log tab: domain, IP address, client name, status
 * and period, the grouping switch, the "ignore query type" toggle, live mode
 * and refresh. It only holds the controls and reports changes to the tab
 * through `handlers`: change(debounce), render(), live(), refresh().
 * `host` offers: t(key). The toggle is remembered by this browser (and may be
 * lost when storage is blocked: it is then simply on).
 */

import { glyphButton } from "./ha-blocky-controls.js";
import { el } from "./ha-blocky-dom.js";
import { readChoice, writeChoice } from "./ha-blocky-format.js";

const HOURS = [1, 6, 24, 168, 720];
const STATUSES = ["all", "blocked", "allowed"];
const IGNORE_CHOICES = ["on", "off"];

export class LogFilters {
  constructor(host, handlers) {
    const t = (key) => host.t(key);
    const search = (maxlength, key) =>
      el("input", {
        attrs: { type: "search", maxlength, placeholder: t(key), "aria-label": t(key) },
      });
    this.domain = search(253, "search_domain");
    this.ip = search(45, "search_ip");
    this.ip.setAttribute("autocomplete", "off");
    this.ip.setAttribute("spellcheck", "false");
    this.name = search(64, "search_name");
    this.status = el(
      "select",
      { attrs: { "aria-label": t("status") } },
      STATUSES.map((status) =>
        el("option", { text: t(`status_${status}`), attrs: { value: status } })
      )
    );
    this.hours = el(
      "select",
      { attrs: { "aria-label": t("period") } },
      HOURS.map((hours) => el("option", { text: t(`hours_${hours}`), attrs: { value: hours } }))
    );
    this.hours.value = "24";
    this.refresh = glyphButton(t("refresh"), "log_refresh");
    this.live = glyphButton(t("live_button"), "log_live", "live");
    this.live.setAttribute("aria-pressed", "false");

    this._groupBox = el("input", { attrs: { type: "checkbox" } });
    this._groupBox.checked = true;
    const groupLabel = el("label", { className: "check" }, [
      this._groupBox,
      el("span", { text: t("group_repeats") }),
    ]);
    // On: rows that differ only by query type merge into one group.
    this._ignoreType = readChoice("log_ignore_type", IGNORE_CHOICES, "on") === "on";
    this._ignoreButton = glyphButton(t("ignore_type"), "log_ignore_type", "ignoretype");
    this._drawIgnore();

    this.domain.addEventListener("input", () => handlers.change(true));
    this.ip.addEventListener("input", () => handlers.change(true));
    this.name.addEventListener("input", () => handlers.change(true));
    this.status.addEventListener("change", () => handlers.change(false));
    this.hours.addEventListener("change", () => handlers.change(false));
    this._groupBox.addEventListener("change", () => {
      this._drawIgnore();
      handlers.render();
    });
    this._ignoreButton.addEventListener("click", () => {
      this._ignoreType = !this._ignoreType;
      writeChoice("log_ignore_type", this._ignoreType ? "on" : "off");
      this._drawIgnore();
      handlers.render();
    });
    this.live.addEventListener("click", () => handlers.live());
    this.refresh.addEventListener("click", () => handlers.refresh());

    this.element = el("div", { className: "filters" }, [
      this.domain,
      this.ip,
      this.name,
      this.status,
      this.hours,
      groupLabel,
      this._ignoreButton,
      this.live,
      this.refresh,
    ]);
  }

  // Whether repeats are grouped, and whether grouping ignores the query type
  // (the second only counts while the first is on).
  get group() {
    return this._groupBox.checked;
  }

  get ignoreType() {
    return this._ignoreType;
  }

  _drawIgnore() {
    const on = this._ignoreType;
    this._ignoreButton.className = on ? "ibtn ignoretype on" : "ibtn ignoretype";
    this._ignoreButton.setAttribute("aria-pressed", String(on));
    this._ignoreButton.disabled = !this._groupBox.checked;
  }

  values() {
    return {
      domain: this.domain.value.trim(),
      ip: this.ip.value.trim(),
      name: this.name.value.trim(),
      status: this.status.value,
      hours: Number(this.hours.value),
    };
  }

  // Show the rows of one client address (a click on a client of the
  // dashboard); a name filter would only contradict it.
  setAddress(address) {
    this.ip.value = typeof address === "string" ? address.slice(0, 45) : "";
    this.name.value = "";
  }
}
