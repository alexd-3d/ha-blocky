/*
 * The "Query log" tab: filters, sorting, paging and the allow/block panel.
 * `host` offers: hass, entry, config, t(key), refresh().
 */

import { DOMAIN, clientCell, el } from "./ha-blocky-dom.js";

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
    this._pending = undefined;
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
        this._refreshButton,
      ])
    );

    this._message = el("div", { className: "message", attrs: { hidden: "" } });
    container.appendChild(this._message);

    this._panel = el("div", { className: "panel", attrs: { hidden: "" } });
    container.appendChild(this._panel);

    this._headRow = el("tr");
    this._tbody = el("tbody");
    this._table = el("table", {}, [el("thead", {}, [this._headRow]), this._tbody]);
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
    return Boolean(this._pending);
  }

  // The timer may reload the first page only.
  get onFirstPage() {
    return this._rows.length <= this._host.config.page_size;
  }

  _lists(type) {
    const entry = this._host.entry;
    const lists = entry && Array.isArray(entry.lists) ? entry.lists : [];
    return lists.filter((list) => list.type === type);
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
    if (this._lists("allow").length || this._lists("deny").length) {
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
    const canAllow = this._lists("allow").length > 0;
    const canBlock = this._lists("deny").length > 0;
    const fragment = document.createDocumentFragment();

    for (const row of this._sortedRows()) {
      const cells = [
        el("td", { text: this._formatTime(row.time) }),
        clientCell(this._host, row.client, row.client_name, row.zone),
        el("td", { text: row.domain || "", className: "domain" }),
        el("td", { text: row.query_type || "" }),
        el("td", { text: row.response_type || "", className: "status" }),
        el("td", { text: Number(row.duration_ms) || 0, className: "num" }),
      ];
      if (canAllow || canBlock) {
        const actions = el("td", { className: "actions" });
        if (canAllow) {
          const button = el("button", { text: this._t("allow") });
          button.addEventListener("click", () => this._openPanel("allow", row.domain));
          actions.appendChild(button);
        }
        if (canBlock) {
          const button = el("button", { text: this._t("block") });
          button.addEventListener("click", () => this._openPanel("deny", row.domain));
          actions.appendChild(button);
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

  _openPanel(type, domain) {
    const lists = this._lists(type);
    if (!lists.length || typeof domain !== "string" || !domain) return;
    this._pending = { type, domain };

    const select = el(
      "select",
      { attrs: { "aria-label": this._t("choose_list") } },
      lists.map((list) => el("option", { text: list.name, attrs: { value: list.name } }))
    );
    const confirm = el("button", { text: this._t("confirm"), className: "primary" });
    const cancel = el("button", { text: this._t("cancel") });
    const result = el("span");

    cancel.addEventListener("click", () => this._closePanel());
    confirm.addEventListener("click", async () => {
      confirm.disabled = true;
      try {
        await this._host.hass.callService(
          DOMAIN,
          type === "allow" ? "allow_domain" : "block_domain",
          { config_entry_id: this._host.entry.entry_id, list: select.value, domain }
        );
        result.textContent = this._t("done");
        confirm.hidden = true;
        cancel.textContent = "×";
      } catch (err) {
        result.textContent = (err && err.message) || this._t("error");
        confirm.disabled = false;
      }
    });

    this._panel.replaceChildren(
      el("span", { text: this._t(type === "allow" ? "action_allow" : "action_block") }),
      el("span", { text: domain, className: "name" }),
      select,
      confirm,
      cancel,
      result
    );
    this._panel.hidden = false;
  }

  _closePanel() {
    this._pending = undefined;
    this._panel.hidden = true;
    this._panel.replaceChildren();
  }
}
