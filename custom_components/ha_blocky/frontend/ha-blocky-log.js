/*
 * The "Query log" tab: filters, sorting, paging, grouping of repeats and the
 * allow/block icons. `host` offers: hass, entry, config, t(key), refresh().
 */

import { DOMAIN, clientCell, el } from "./ha-blocky-dom.js";
import { ListPicker, STATUS_ICONS, haIcon, iconButton } from "./ha-blocky-actions.js";
import { groupRows } from "./ha-blocky-group.js";

const HOURS = [1, 6, 24, 168, 720];
const STATUSES = ["all", "blocked", "allowed"];
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
    this._filters = { domain: "", client: "", status: "all", hours: 24 };
    this._sort = { key: "id", direction: -1 };
    this._group = true;
    this._debounce = undefined;
    this._build(container);
  }

  _t(key) {
    return this._host.t(key);
  }

  _build(container) {
    this._domainInput = el("input", {
      attrs: { type: "search", maxlength: 253, placeholder: this._t("search_domain") },
    });
    this._clientInput = el("input", {
      attrs: { type: "search", maxlength: 64, placeholder: this._t("search_client") },
    });
    this._statusSelect = el(
      "select",
      { attrs: { "aria-label": this._t("status") } },
      STATUSES.map((status) =>
        el("option", { text: this._t(`status_${status}`), attrs: { value: status } })
      )
    );
    this._hoursSelect = el(
      "select",
      { attrs: { "aria-label": this._t("period") } },
      HOURS.map((hours) =>
        el("option", { text: this._t(`hours_${hours}`), attrs: { value: hours } })
      )
    );
    this._hoursSelect.value = "24";
    this._refreshButton = el("button", { text: this._t("refresh") });
    this._groupBox = el("input", { attrs: { type: "checkbox" } });
    this._groupBox.checked = this._group;
    const groupLabel = el("label", { className: "check" }, [
      this._groupBox,
      el("span", { text: this._t("group_repeats") }),
    ]);

    this._groupBox.addEventListener("change", () => {
      this._group = this._groupBox.checked;
      this.render();
    });
    this._domainInput.addEventListener("input", () => this._filterChanged(true));
    this._clientInput.addEventListener("input", () => this._filterChanged(true));
    this._statusSelect.addEventListener("change", () => this._filterChanged(false));
    this._hoursSelect.addEventListener("change", () => this._filterChanged(false));
    this._refreshButton.addEventListener("click", () => this.load(true));

    container.appendChild(
      el("div", { className: "filters" }, [
        this._domainInput,
        this._clientInput,
        this._statusSelect,
        this._hoursSelect,
        groupLabel,
        this._refreshButton,
      ])
    );

    this._message = el("div", { className: "message", attrs: { hidden: "" } });
    container.appendChild(this._message);

    this._panel = el("div", { className: "panel", attrs: { hidden: "" } });
    container.appendChild(this._panel);
    this._picker = new ListPicker(this._host, this._panel);

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
    this._filters = {
      domain: this._domainInput.value.trim(),
      client: this._clientInput.value.trim(),
      status: this._statusSelect.value,
      hours: Number(this._hoursSelect.value),
    };
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
    if (this._filters.client) message.client = this._filters.client;
    if (!reset && this._nextBeforeId) message.before_id = this._nextBeforeId;

    try {
      const result = await this._host.hass.callWS(message);
      if (request !== this._request) return;
      const rows = Array.isArray(result.rows) ? result.rows : [];
      this._rows = reset ? rows : this._rows.concat(rows);
      this._hasMore = Boolean(result.has_more);
      this._nextBeforeId = result.next_before_id || undefined;
      this.showMessage(this._rows.length ? "" : "no_rows", false);
    } catch (err) {
      if (request !== this._request) return;
      this.showMessage(err && err.code === "no_query_log" ? "no_query_log" : "error", true);
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

  _formatTime(value) {
    if (typeof value !== "string") return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const hass = this._host.hass;
    const language = (hass && hass.locale && hass.locale.language) || undefined;
    try {
      return date.toLocaleString(language);
    } catch (err) {
      return date.toLocaleString();
    }
  }

  render() {
    const canAct = this._picker.lists("allow").length || this._picker.lists("deny").length;
    const fragment = document.createDocumentFragment();

    for (const { row, count } of groupRows(this._sortedRows(), this._group)) {
      const time = el("td", { text: this._formatTime(row.time), className: "time" });
      if (count > 1) {
        time.appendChild(el("span", { text: `×${count}`, className: "count" }));
      }
      const status = el(
        "td",
        { className: "status", attrs: { title: row.response_type || "" } },
        [
          haIcon(STATUS_ICONS, statusOf(row), "statusicon"),
          el("span", { text: row.response_type || "", className: "statustext" }),
        ]
      );
      const cells = [
        time,
        clientCell(this._host, row.client, row.client_name, row.zone),
        el("td", { text: row.domain || "", className: "domain" }),
        el("td", { text: row.query_type || "", className: "type" }),
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
              this._picker.open(type, row.domain)
            )
          );
        }
        cells.push(actions);
      }
      const title = row.reason ? { title: row.reason } : {};
      fragment.appendChild(
        el("tr", { className: row.blocked ? "blocked" : "", attrs: title }, cells)
      );
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
