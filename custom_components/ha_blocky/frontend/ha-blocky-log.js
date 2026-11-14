/*
 * The "Query log" tab: filters, sorting, paging, grouping of repeats and the
 * allow/block icons. `host` offers: hass, entry, config, t(key), refresh().
 */

import { DOMAIN, clientCell, el } from "./ha-blocky-dom.js";
import { ListPicker, STATUS_ICONS, flasher, haIcon, iconButton } from "./ha-blocky-actions.js";
import { formatWhen, timeFormats } from "./ha-blocky-format.js";
import { groupRows } from "./ha-blocky-group.js";
import { LogFilters } from "./ha-blocky-log-filters.js";
import { affectedRowIds, ipFilterOk, levelOfRow, listLevels } from "./ha-blocky-log-logic.js";

// Live mode: how often the log is read, and for how long at most.
const LIVE_INTERVAL_MS = 3000;
const LIVE_MAX_MS = 10 * 60 * 1000;
const COLUMNS = [
  { key: "time", label: "col_time", sort: "id" },
  { key: "client", label: "col_client", sort: "client" },
  { key: "domain", label: "col_domain", sort: "domain" },
  { key: "query_type", label: "col_type", sort: "query_type" },
  { key: "response_type", label: "col_status", sort: "response_type" },
  { key: "duration_ms", label: "col_ms", sort: "duration_ms", numeric: true },
];

// The category of a response type; it picks the status icon.
const STATUS_CATEGORY = {
  RESOLVED: "resolved",
  CACHED: "cached",
  CONDITIONAL: "local",
  CUSTOMDNS: "local",
  HOSTSFILE: "local",
  SPECIAL: "local",
  SYNTHESIZED: "local",
};
// A blocked row can be allowed; a row that was answered can be blocked.
const BLOCKABLE = ["RESOLVED", "CACHED"];
// The kind of list each action adds to.
const LIST_TYPE_OF = { allow: "allow", block: "deny" };

function statusOf(row) {
  if (row.blocked === true) return "blocked";
  return Object.prototype.hasOwnProperty.call(STATUS_CATEGORY, row.response_type)
    ? STATUS_CATEGORY[row.response_type]
    : "other";
}

// The one action a row offers, or "" for none.
function actionOf(row) {
  if (row.blocked === true) return "allow";
  return BLOCKABLE.includes(row.response_type) ? "block" : "";
}

export class LogView {
  constructor(host, container) {
    this._host = host;
    this._rows = [];
    this._hasMore = false;
    this._nextBeforeId = undefined;
    this._loading = false;
    this._request = 0;
    this._filters = { domain: "", ip: "", name: "", status: "all", hours: 24 };
    this._sort = { key: "id", direction: -1 };
    this._debounce = undefined;
    this._live = false;
    this._liveTimer = undefined;
    this._liveUntil = 0;
    this._newestId = undefined;
    this._build(container);
  }

  _t(key) {
    return this._host.t(key);
  }

  _build(container) {
    this._bar = new LogFilters(this._host, {
      change: (debounce) => this._filterChanged(debounce),
      render: () => this.render(),
      live: () => this.setLive(!this._live),
      refresh: () => this.load(true),
    });
    this._liveButton = this._bar.live;
    this._refreshButton = this._bar.refresh;
    container.appendChild(this._bar.element);
    container.appendChild(el("div", { className: "hint", text: this._t("live_hint") }));

    this._message = el("div", { className: "message", attrs: { hidden: "" } });
    container.appendChild(this._message);

    this._panel = el("div", { className: "panel", attrs: { hidden: "" } });
    container.appendChild(this._panel);
    this._picker = new ListPicker(this._host, this._panel, (context, listName) => {
      // The row of the action, and every visible row of the same domain whose
      // client's level that list changes, light up for a second.
      if (context) {
        flasher.mark(context.key, context.action);
        const lists = this._host.entry && this._host.entry.lists;
        for (const id of affectedRowIds(this._rows, context.domain, listLevels(lists, listName))) {
          flasher.mark(`log:${id}`, context.action);
        }
      }
      this.render();
    });

    this._headRow = el("tr");
    this._tbody = el("tbody");
    this._table = el("table", { className: "log" }, [el("thead", {}, [this._headRow]), this._tbody]);
    container.appendChild(el("div", { className: "scroll" }, [this._table]));

    this._count = el("span");
    this._moreButton = el("button", { text: this._t("load_more") });
    this._moreButton.addEventListener("click", () => this.load(false));
    container.appendChild(
      el("div", { className: "footer" }, [this._count, this._moreButton])
    );

    this.renderHead();
    this.render();
  }

  stop() {
    clearTimeout(this._debounce);
    this.setLive(false);
  }

  // Whether the tab is the one shown; leaving it ends live mode.
  setActive(active) {
    if (!active) this.setLive(false);
  }

  // Live mode: read the first page every few seconds, only while the page is
  // visible, for at most ten minutes. Rows new since the last read light up.
  setLive(on) {
    if (on === this._live) return;
    this._live = on;
    clearInterval(this._liveTimer);
    this._liveTimer = undefined;
    this._liveButton.className = on ? "ibtn live on" : "ibtn live";
    this._liveButton.setAttribute("aria-pressed", String(on));
    if (!on) return;
    this._liveUntil = Date.now() + LIVE_MAX_MS;
    this._newestId = this._rows.reduce((top, row) => Math.max(top, Number(row.id) || 0), 0);
    this._liveTimer = setInterval(() => this._liveTick(), LIVE_INTERVAL_MS);
  }

  _liveTick() {
    if (Date.now() >= this._liveUntil) {
      this.setLive(false);
      return;
    }
    if (
      document.visibilityState === "visible" &&
      !this._loading &&
      !this.busy &&
      !this._host.isEditing()
    ) {
      this.load(true);
    }
  }

  // Show the rows of one client address (a click on a client of the dashboard).
  showClient(address) {
    this._bar.setAddress(address);
    this._filterChanged(false);
  }

  hideTable() {
    this._table.hidden = true;
  }

  showMessage(key, isError) {
    this._message.textContent = key ? this._t(key) : "";
    this._message.className = isError ? "message error" : "message";
    this._message.hidden = !key;
  }

  // True while the user works with the allow/block panel.
  get busy() {
    return this._picker.busy;
  }

  // The timer may reload the first page only.
  get onFirstPage() {
    return this._rows.length <= this._host.config.page_size;
  }

  _filterChanged(debounce) {
    this._filters = this._bar.values();
    clearTimeout(this._debounce);
    if (debounce) {
      this._debounce = setTimeout(() => this.load(true), 400);
    } else {
      this.load(true);
    }
  }

  async load(reset) {
    const entry = this._host.entry;
    if (!entry || !entry.has_query_log) return;
    // The server refuses such a value anyway; do not even ask.
    if (!ipFilterOk(this._filters.ip)) {
      this.showMessage("bad_ip_filter", true);
      return;
    }
    const request = ++this._request;
    this._loading = true;
    this._renderFooter();

    const message = {
      type: `${DOMAIN}/query_log`,
      entry_id: entry.entry_id,
      hours: this._filters.hours,
      status: this._filters.status,
      limit: this._host.config.page_size,
    };
    if (this._filters.domain) message.domain = this._filters.domain;
    if (this._filters.ip) message.ip = this._filters.ip;
    if (this._filters.name) message.name = this._filters.name;
    if (!reset && this._nextBeforeId) message.before_id = this._nextBeforeId;

    try {
      const result = await this._host.hass.callWS(message);
      if (request !== this._request) return;
      const rows = Array.isArray(result.rows) ? result.rows : [];
      if (reset && this._live && this._newestId !== undefined) {
        for (const row of rows) {
          if (Number(row.id) > this._newestId) flasher.mark(`log:${row.id}`, "new");
        }
      }
      this._rows = reset ? rows : this._rows.concat(rows);
      this._newestId = this._rows.reduce(
        (top, row) => Math.max(top, Number(row.id) || 0),
        this._newestId || 0
      );
      this._hasMore = Boolean(result.has_more);
      this._nextBeforeId = result.next_before_id || undefined;
      this.showMessage(this._rows.length ? "" : "no_rows", false);
    } catch (err) {
      if (request !== this._request) return;
      const known = { no_query_log: "no_query_log", invalid_ip: "bad_ip_filter", invalid_name: "bad_name_filter" };
      this.showMessage(
        err && Object.prototype.hasOwnProperty.call(known, err.code) ? known[err.code] : "error",
        true
      );
    } finally {
      if (request === this._request) {
        this._loading = false;
        this.render();
      }
    }
  }

  renderHead() {
    this._headRow.replaceChildren();
    for (const column of COLUMNS) {
      const active = this._sort.key === column.sort;
      const arrow = active ? (this._sort.direction > 0 ? " ▲" : " ▼") : "";
      const cell = el("th", {
        text: this._t(column.label) + arrow,
        className: column.numeric ? "num" : "",
      });
      cell.addEventListener("click", () => {
        this._sort = {
          key: column.sort,
          direction: active ? -this._sort.direction : column.sort === "id" ? -1 : 1,
        };
        this.renderHead();
        this.render();
      });
      this._headRow.appendChild(cell);
    }
    if (this._picker.lists("allow").length || this._picker.lists("deny").length) {
      this._headRow.appendChild(
        el("th", { text: this._t("col_actions"), className: "plain" })
      );
    }
  }

  _sortedRows() {
    const { key, direction } = this._sort;
    const numeric = key === "id" || key === "duration_ms";
    return this._rows.slice().sort((a, b) => {
      const left = a[key];
      const right = b[key];
      const order = numeric
        ? Number(left) - Number(right)
        : String(left || "").localeCompare(String(right || ""));
      return (order || Number(a.id) - Number(b.id)) * direction;
    });
  }

  // The time of a row, in the language and the time format of the profile.
  _formatTime(value) {
    if (typeof value !== "string") return "";
    const hass = this._host.hass;
    const language = hass && hass.language;
    if (!this._formats || this._formatsFor !== (hass && hass.locale)) {
      this._formatsFor = hass && hass.locale;
      this._formats = timeFormats(this._formatsFor, language);
    }
    return formatWhen(this._formats.log, value);
  }

  render() {
    const canAct = this._picker.lists("allow").length || this._picker.lists("deny").length;
    const fragment = document.createDocumentFragment();

    for (const { row, count, types } of groupRows(this._sortedRows(), this._bar.group, this._bar.ignoreType)) {
      const time = el("td", { text: this._formatTime(row.time), className: "time" });
      if (count > 1) {
        time.appendChild(el("span", { text: `×${count}`, className: "count" }));
      }
      const kind = statusOf(row);
      const status = el(
        "td",
        { className: "status", attrs: { title: row.response_type || "" } },
        [
          haIcon(STATUS_ICONS, kind, `statusicon c-${kind}`),
          el("span", { text: row.response_type || "", className: `statustext badge c-${kind}` }),
        ]
      );
      const cells = [
        time,
        clientCell(this._host, row.client, row.client_name, row.level),
        el("td", {
          text: row.domain || "",
          className: "domain",
          attrs: { title: row.domain || "" },
        }),
        el("td", { text: types.join(", "), className: "type" }),
        status,
        el("td", { text: Number(row.duration_ms) || 0, className: "num ms" }),
      ];
      if (canAct) {
        const actions = el("td", { className: "actions" });
        const action = actionOf(row);
        const type = LIST_TYPE_OF[action];
        if (action && row.domain && this._picker.lists(type).length) {
          actions.appendChild(
            iconButton(this._host, action, action, () =>
              this._picker.open(type, row.domain, { key: `log:${row.id}`, action, domain: row.domain }, levelOfRow(row))
            )
          );
        }
        cells.push(actions);
      }
      const title = row.reason ? { title: row.reason } : {};
      const line = el("tr", { className: row.blocked ? "blocked" : "", attrs: title }, cells);
      flasher.apply(`log:${row.id}`, line);
      fragment.appendChild(line);
    }
    this._tbody.replaceChildren(fragment);
    this._renderFooter();
  }

  _renderFooter() {
    this._count.textContent = this._loading
      ? this._t("loading")
      : `${this._rows.length} ${this._t("rows_shown")}`;
    this._moreButton.hidden = !this._hasMore;
    this._moreButton.disabled = this._loading;
    this._refreshButton.disabled = this._loading;
  }
}
