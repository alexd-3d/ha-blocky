/*
 * The "Dashboard" tab: the blocking switch, the totals of a period, the
 * stacked chart of queries over time and the top clients, domains and blocked
 * domains. The numbers come from one read-only command (`ha_blocky/dashboard`)
 * that aggregates in the database. Every text from the answer is written with
 * textContent; colours come from style classes only.
 * `host` offers: hass, entry, config, t(key), isEditing(), editMode.
 */

import { UI_ICONS, haIcon } from "./ha-blocky-actions.js";
import { buttonGroup } from "./ha-blocky-controls.js";
import { buildChart } from "./ha-blocky-chart.js";
import { normalize } from "./ha-blocky-dashboard-data.js";
import { DOMAIN, el } from "./ha-blocky-dom.js";
import {
  PERIODS,
  ROW_CHOICES,
  compact,
  hasChoice,
  percent,
  readChoice,
  timeFormats,
  writeChoice,
} from "./ha-blocky-format.js";
import { Popover } from "./ha-blocky-popover.js";
import { prefs } from "./ha-blocky-prefs.js";
import { BlockingSwitch } from "./ha-blocky-switch.js";
import { topList } from "./ha-blocky-toplist.js";

const DEFAULT_REFRESH_SECONDS = 60;
const TILES = [
  { id: "total", icon: "tile_total", label: "dash_total", tone: "c-total" },
  { id: "blocked", icon: "tile_blocked", label: "dash_blocked", tone: "c-blocked" },
  { id: "cached", icon: "tile_cached", label: "dash_cached", tone: "c-cached" },
  { id: "latency", icon: "tile_latency", label: "dash_latency", tone: "c-resolved" },
];

export class DashboardView {
  constructor(host, container) {
    this._host = host;
    this._period = readChoice("period", PERIODS, "24h");
    this._rows = readChoice("rows", ROW_CHOICES, prefs.rows || 10);
    this._token = 0;
    this._active = false;
    this._data = undefined;
    this._timer = undefined;
    this._build(container);
  }

  _t(key) {
    return this._host.t(key);
  }

  _language() {
    const hass = this._host.hass;
    return (hass && hass.locale && hass.locale.language) || (hass && hass.language) || undefined;
  }

  // What the chart and the lists need to format times and texts.
  _ctx() {
    const language = this._language();
    const formats = timeFormats(language);
    return {
      language,
      t: (key) => this._t(key),
      time: (value, unit, full) => {
        const format =
          unit === "day"
            ? full ? formats.dayFull : formats.dayAxis
            : full ? formats.hourFull : formats.hourAxis;
        return format.format(value);
      },
      dateTime: (value) => {
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? "" : formats.dateTime.format(date);
      },
      clock: (date) => formats.clock.format(date),
    };
  }

  // A titled part with a muted hint and a "?" button that shows an info panel.
  _part(titleKey, hintKey, infoKey) {
    const info = el("div", { className: "info", text: this._t(infoKey), attrs: { hidden: "" } });
    const help = el("button", {
      className: "help",
      text: "?",
      attrs: { type: "button", "aria-expanded": "false", "aria-label": this._t("dash_help") },
    });
    help.addEventListener("click", () => {
      info.hidden = !info.hidden;
      help.setAttribute("aria-expanded", String(!info.hidden));
    });
    const body = el("div", { className: "pbody" });
    const head = el("div", { className: "phead" }, [
      el("h3", { text: this._t(titleKey) }),
      help,
    ]);
    const root = el("section", { className: "part" }, [
      head,
      el("div", { className: "hint", text: this._t(hintKey) }),
      info,
      body,
    ]);
    return { root, body };
  }

  _build(container) {
    this._root = el("div", { className: "dash" });
    this._popover = new Popover(this._root);

    this._switch = new BlockingSwitch(this._host, (key) => this.showMessage(key, Boolean(key)));
    this._message = el("div", { className: "message", attrs: { hidden: "" } });

    const periods = buttonGroup(
      this._t("period"),
      PERIODS.map((value) => ({ value, label: this._t(`dash_period_${value}`) })),
      this._period,
      (value) => {
        this._period = value;
        writeChoice("period", value);
        this.load();
      }
    );

    this._tiles = {};
    const tiles = el(
      "div",
      { className: "tiles" },
      TILES.map((tile) => {
        const value = el("div", { className: "tvalue", text: "-" });
        const sub = el("div", { className: "tsub" });
        this._tiles[tile.id] = { value, sub };
        return el("div", { className: `tile ${tile.tone}` }, [
          el("div", { className: "chip" }, [haIcon(UI_ICONS, tile.icon)]),
          el("div", { className: "tbody" }, [
            el("div", { className: "tlabel", text: this._t(tile.label) }),
            value,
            sub,
          ]),
        ]);
      })
    );

    const chart = this._part("dash_chart_title", "dash_chart_hint", "dash_chart_info");
    this._chartBody = chart.body;
    const rows = (this._rowsGroup = buttonGroup(
      this._t("dash_rows"),
      ROW_CHOICES.map((value) => ({ value, label: String(value) })),
      this._rows,
      (value) => {
        this._rows = value;
        writeChoice("rows", value);
        this.load();
      }
    ));
    const bar = el("div", { className: "listbar" }, [
      el("span", { text: this._t("dash_show_top"), className: "sub" }),
      rows,
    ]);
    const parts = [
      ["dash_clients_title", "dash_clients_hint", "dash_clients_info"],
      ["dash_domains_title", "dash_domains_hint", "dash_domains_info"],
      ["dash_blocked_title", "dash_blocked_hint", "dash_blocked_info"],
    ].map((keys) => this._part(...keys));
    [this._clients, this._domains, this._blocked] = parts.map((part) => part.body);

    this._footer = el("div", { className: "dfoot" });
    this._content = el("div", { className: "content" }, [
      chart.root,
      bar,
      el("div", { className: "tops" }, parts.map((part) => part.root)),
    ]);
    this._root.prepend(
      this._switch.element,
      el("div", { className: "hint", text: this._t("dash_switch_hint") }),
      this._message,
      periods,
      tiles,
      this._content,
      this._footer
    );
    container.appendChild(this._root);
  }

  // Redraw what depends on the states of Home Assistant: the blocking switch.
  updateHass() {
    this._switch.update();
  }

  showMessage(key, isError) {
    this._message.textContent = key ? this._t(key) : "";
    this._message.className = isError ? "message error" : "message";
    this._message.hidden = !key;
  }

  // Without a database or an administrator there is nothing to count.
  hideContent(key, isError) {
    this._popover.hide();
    this._content.hidden = true;
    this._footer.hidden = true;
    this.showMessage(key, isError);
  }

  // The server's default number of rows counts until this browser has a choice.
  applyPrefs() {
    if (hasChoice("rows", ROW_CHOICES)) return;
    const wanted = prefs.rows || 10;
    if (this._rows === wanted) return;
    this._rows = wanted;
    this._rowsGroup.mark(wanted);
    if (this._active) this.load();
  }

  // Whether the tab is the one shown; only then does it reload on its own.
  setActive(active) {
    this._active = active;
    this._restartTimer();
    if (active) this.load();
  }

  async load() {
    const entry = this._host.entry;
    if (!entry) return;
    if (!entry.has_query_log) {
      this.hideContent("dash_no_database", false);
      return;
    }
    const token = ++this._token;
    try {
      const result = await this._host.hass.callWS({
        type: `${DOMAIN}/dashboard`,
        entry_id: entry.entry_id,
        period: this._period,
        rows: this._rows,
      });
      if (token !== this._token) return;
      if (result.state !== "ok") {
        this.hideContent("dash_no_database", false);
        return;
      }
      this._data = normalize(result);
      this._content.hidden = false;
      this._footer.hidden = false;
      this.showMessage("", false);
      this._render();
    } catch (err) {
      if (token !== this._token) return;
      this.hideContent(err && err.code === "no_query_log" ? "dash_no_database" : "dash_error", true);
    }
  }

  _render() {
    const data = this._data;
    const ctx = this._ctx();
    const cats = data.categories;
    this._popover.hide();

    const set = (id, value, sub) => {
      this._tiles[id].value.textContent = value;
      this._tiles[id].sub.textContent = sub;
    };
    const total = data.queries;
    set("total", compact(total, ctx.language), `${compact(data.unique, ctx.language)} ${this._t("dash_unique")}`);
    set("blocked", compact(cats.blocked, ctx.language), `${percent(cats.blocked, total)} ${this._t("dash_of_total")}`);
    set(
      "cached",
      compact(cats.cached, ctx.language),
      `${percent(cats.cached, cats.cached + cats.resolved)} ${this._t("dash_cache_rate")}`
    );
    set(
      "latency",
      data.average === undefined ? "-" : `${data.average.toFixed(data.average < 10 ? 1 : 0)} ms`,
      this._t("dash_latency_sub")
    );

    this._chartBody.replaceChildren(
      total
        ? buildChart(ctx, this._popover, data.buckets, data.unit, cats)
        : el("div", { className: "sub", text: this._t("dash_none") })
    );
    const fill = (body, rows, isClient) =>
      body.replaceChildren(
        rows.length
          ? topList(ctx, this._popover, rows, isClient)
          : el("div", { className: "sub", text: this._t("dash_none") })
      );
    fill(this._clients, data.clients, true);
    fill(this._domains, data.domains, false);
    fill(this._blocked, data.blocked, false);

    const parts = [`${this._t("dash_version")} ${data.version ? `v${data.version}` : ""}`.trim()];
    if (data.blockyVersion) parts.push(`${this._t("dash_blocky_version")} ${data.blockyVersion}`);
    if (!Number.isNaN(data.generated.getTime())) {
      parts.push(`${this._t("dash_updated")} ${ctx.clock(data.generated)}`);
    }
    this._footer.textContent = parts.join(" · ");
  }

  stop() {
    clearInterval(this._timer);
    this._timer = undefined;
    this._popover.hide();
  }

  // Reload on a timer while the tab is shown, the page is visible, the
  // dashboard is not being edited and no popover or name field is open.
  _restartTimer() {
    clearInterval(this._timer);
    this._timer = undefined;
    const configured = this._host.config.auto_refresh;
    const seconds = configured === undefined ? DEFAULT_REFRESH_SECONDS : configured;
    if (!seconds || !this._active || !this._host.isConnected) return;
    this._timer = setInterval(() => {
      if (
        document.visibilityState === "visible" &&
        !this._host.editMode &&
        !this._host.isEditing() &&
        !this._popover.isOpen
      ) {
        this.load();
      }
    }, seconds * 1000);
  }

  restartTimer() {
    this._restartTimer();
  }
}
