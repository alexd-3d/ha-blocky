/*
 * HA-Blocky query log card.
 *
 * Shows Blocky's query log with search, filters, sorting and paging, and lets
 * an administrator add a domain to a manual allow or deny list.
 *
 * Every value from the log is written with textContent. A DNS name can be
 * chosen by any device on the network, so nothing from the log is ever
 * interpreted as markup. The card loads nothing from outside Home Assistant.
 */

const DOMAIN = "ha_blocky";

/* i18n:en */
const TEXT_EN = {
  "title": "Blocky query log",
  "search_domain": "Domain contains",
  "search_client": "Client address",
  "status": "Status",
  "status_all": "All",
  "status_blocked": "Blocked",
  "status_allowed": "Not blocked",
  "period": "Period",
  "hours_1": "Last hour",
  "hours_6": "Last 6 hours",
  "hours_24": "Last 24 hours",
  "hours_168": "Last 7 days",
  "hours_720": "Last 30 days",
  "refresh": "Refresh",
  "col_time": "Time",
  "col_client": "Client",
  "col_domain": "Domain",
  "col_type": "Type",
  "col_status": "Status",
  "col_ms": "ms",
  "col_actions": "Actions",
  "allow": "Allow",
  "block": "Block",
  "confirm": "Confirm",
  "cancel": "Cancel",
  "choose_list": "List",
  "action_allow": "Allow this domain:",
  "action_block": "Block this domain:",
  "done": "Done. Blocky reloads its lists in a few seconds.",
  "load_more": "Load more",
  "loading": "Loading…",
  "rows_shown": "rows shown",
  "no_rows": "No queries match these filters.",
  "no_query_log": "No query log database is configured for this integration.",
  "no_entry": "The HA-Blocky integration is not set up or not loaded.",
  "not_admin": "Only administrators can view the query log.",
  "error": "Could not load the query log."
};
/* i18n:end */

/* i18n:uk */
const TEXT_UK = {
  "title": "Журнал запитів Blocky",
  "search_domain": "Домен містить",
  "search_client": "Адреса клієнта",
  "status": "Статус",
  "status_all": "Усі",
  "status_blocked": "Заблоковані",
  "status_allowed": "Не заблоковані",
  "period": "Період",
  "hours_1": "Остання година",
  "hours_6": "Останні 6 годин",
  "hours_24": "Останні 24 години",
  "hours_168": "Останні 7 днів",
  "hours_720": "Останні 30 днів",
  "refresh": "Оновити",
  "col_time": "Час",
  "col_client": "Клієнт",
  "col_domain": "Домен",
  "col_type": "Тип",
  "col_status": "Статус",
  "col_ms": "мс",
  "col_actions": "Дії",
  "allow": "Дозволити",
  "block": "Заблокувати",
  "confirm": "Підтвердити",
  "cancel": "Скасувати",
  "choose_list": "Список",
  "action_allow": "Дозволити цей домен:",
  "action_block": "Заблокувати цей домен:",
  "done": "Готово. Blocky перечитає списки за кілька секунд.",
  "load_more": "Завантажити ще",
  "loading": "Завантаження…",
  "rows_shown": "рядків показано",
  "no_rows": "Немає запитів за цими фільтрами.",
  "no_query_log": "Для цієї інтеграції не налаштовано базу журналу запитів.",
  "no_entry": "Інтеграцію HA-Blocky не налаштовано або не завантажено.",
  "not_admin": "Журнал запитів доступний лише адміністраторам.",
  "error": "Не вдалося завантажити журнал запитів."
};
/* i18n:end */

const TEXTS = { en: TEXT_EN, uk: TEXT_UK };
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
const MIN_REFRESH_SECONDS = 10;

const STYLE = `
  :host { display: block; }
  .body { padding: 0 16px 16px; }
  .filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
  .filters input, .filters select, .panel select {
    flex: 1 1 140px; min-width: 0; box-sizing: border-box; padding: 8px;
    font: inherit; color: var(--primary-text-color);
    background: var(--card-background-color);
    border: 1px solid var(--divider-color); border-radius: 6px;
  }
  button {
    font: inherit; cursor: pointer; padding: 6px 12px; border-radius: 6px;
    color: var(--primary-text-color); background: transparent;
    border: 1px solid var(--divider-color);
  }
  button.primary {
    color: var(--text-primary-color); background: var(--primary-color);
    border-color: var(--primary-color);
  }
  button:disabled { opacity: 0.5; cursor: default; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
  th, td {
    text-align: left; padding: 6px 8px; white-space: nowrap;
    border-bottom: 1px solid var(--divider-color);
  }
  th { cursor: pointer; user-select: none; color: var(--secondary-text-color); }
  th.plain { cursor: default; }
  td.domain {
    white-space: normal; word-break: break-all;
    font-family: var(--code-font-family, monospace);
  }
  td.num, th.num { text-align: right; }
  tr.blocked td.status { color: var(--error-color); font-weight: 500; }
  td.actions button { padding: 2px 8px; margin-right: 4px; font-size: 0.9em; }
  .panel {
    display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
    margin: 12px 0; padding: 12px; border-radius: 6px;
    border: 1px solid var(--primary-color);
  }
  .panel .name {
    word-break: break-all; font-family: var(--code-font-family, monospace);
  }
  .zone { font-size: 0.85em; color: var(--secondary-text-color); }
  .message { margin: 12px 0; color: var(--secondary-text-color); }
  .message.error { color: var(--error-color); }
  .footer {
    display: flex; align-items: center; justify-content: space-between;
    gap: 8px; margin-top: 12px; color: var(--secondary-text-color);
  }
  [hidden] { display: none !important; }
`;

function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = String(options.text);
  for (const [name, value] of Object.entries(options.attrs || {})) {
    node.setAttribute(name, String(value));
  }
  for (const child of children) node.appendChild(child);
  return node;
}

class HaBlockyCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = undefined;
    this._built = false;
    this._started = false;
    this._entry = undefined;
    this._rows = [];
    this._hasMore = false;
    this._nextBeforeId = undefined;
    this._loading = false;
    this._request = 0;
    this._filters = { domain: "", client: "", status: "all", hours: 24 };
    this._sort = { key: "id", direction: -1 };
    this._pending = undefined;
    this._debounce = undefined;
    this._timer = undefined;
  }

  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    const pageSize = Number(config && config.page_size);
    const refresh = Number(config && config.auto_refresh);
    this._config = {
      title: config && typeof config.title === "string" ? config.title : undefined,
      entry_id:
        config && typeof config.entry_id === "string" ? config.entry_id : undefined,
      page_size: Number.isInteger(pageSize)
        ? Math.min(Math.max(pageSize, 10), 200)
        : 50,
      auto_refresh:
        Number.isFinite(refresh) && refresh > 0
          ? Math.max(refresh, MIN_REFRESH_SECONDS)
          : 0,
    };
    if (this._built) this._renderTitle();
    this._restartTimer();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    if (!this._started) {
      this._started = true;
      this._start();
    }
  }

  getCardSize() {
    return 10;
  }

  connectedCallback() {
    this._restartTimer();
  }

  disconnectedCallback() {
    this._stopTimer();
    clearTimeout(this._debounce);
  }

  _t(key) {
    const hass = this._hass;
    const language =
      (hass && hass.locale && hass.locale.language) || (hass && hass.language) || "en";
    const table = TEXTS[language] || TEXTS[language.split("-")[0]] || TEXT_EN;
    return table[key] || TEXT_EN[key] || key;
  }

  _build() {
    this._built = true;
    const root = this.shadowRoot;
    root.appendChild(el("style", { text: STYLE }));

    this._card = document.createElement("ha-card");
    this._body = el("div", { className: "body" });
    this._card.appendChild(this._body);
    root.appendChild(this._card);
    this._renderTitle();

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
    this._refreshButton.addEventListener("click", () => this._load(true));

    this._body.appendChild(
      el("div", { className: "filters" }, [
        this._domainInput,
        this._clientInput,
        this._statusSelect,
        this._hoursSelect,
        this._refreshButton,
      ])
    );

    this._message = el("div", { className: "message", attrs: { hidden: "" } });
    this._body.appendChild(this._message);

    this._panel = el("div", { className: "panel", attrs: { hidden: "" } });
    this._body.appendChild(this._panel);

    this._headRow = el("tr");
    this._tbody = el("tbody");
    this._table = el("table", {}, [el("thead", {}, [this._headRow]), this._tbody]);
    this._body.appendChild(el("div", { className: "scroll" }, [this._table]));

    this._count = el("span");
    this._moreButton = el("button", { text: this._t("load_more") });
    this._moreButton.addEventListener("click", () => this._load(false));
    this._body.appendChild(
      el("div", { className: "footer" }, [this._count, this._moreButton])
    );

    this._renderHead();
    this._renderRows();
  }

  _renderTitle() {
    this._card.setAttribute("header", this._config.title || this._t("title"));
  }

  _showMessage(key, isError) {
    this._message.textContent = key ? this._t(key) : "";
    this._message.className = isError ? "message error" : "message";
    this._message.hidden = !key;
  }

  async _start() {
    const hass = this._hass;
    if (!hass.user || !hass.user.is_admin) {
      this._showMessage("not_admin", true);
      this._table.hidden = true;
      return;
    }
    try {
      const config = await hass.callWS({ type: `${DOMAIN}/config` });
      const entries = Array.isArray(config.entries) ? config.entries : [];
      this._entry = this._config.entry_id
        ? entries.find((entry) => entry.entry_id === this._config.entry_id)
        : entries.find((entry) => entry.has_query_log) || entries[0];
    } catch (err) {
      this._showMessage("error", true);
      return;
    }
    if (!this._entry) {
      this._showMessage("no_entry", true);
      return;
    }
    if (!this._entry.has_query_log) {
      this._showMessage("no_query_log", false);
      return;
    }
    this._renderHead();
    await this._load(true);
    this._restartTimer();
  }

  _lists(type) {
    const lists = this._entry && Array.isArray(this._entry.lists) ? this._entry.lists : [];
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
      this._debounce = setTimeout(() => this._load(true), 400);
    } else {
      this._load(true);
    }
  }

  async _load(reset) {
    if (!this._entry || !this._entry.has_query_log) return;
    const request = ++this._request;
    this._loading = true;
    this._renderFooter();

    const message = {
      type: `${DOMAIN}/query_log`,
      entry_id: this._entry.entry_id,
      hours: this._filters.hours,
      status: this._filters.status,
      limit: this._config.page_size,
    };
    if (this._filters.domain) message.domain = this._filters.domain;
    if (this._filters.client) message.client = this._filters.client;
    if (!reset && this._nextBeforeId) message.before_id = this._nextBeforeId;

    try {
      const result = await this._hass.callWS(message);
      if (request !== this._request) return;
      const rows = Array.isArray(result.rows) ? result.rows : [];
      this._rows = reset ? rows : this._rows.concat(rows);
      this._hasMore = Boolean(result.has_more);
      this._nextBeforeId = result.next_before_id || undefined;
      this._showMessage(this._rows.length ? "" : "no_rows", false);
    } catch (err) {
      if (request !== this._request) return;
      this._showMessage(err && err.code === "no_query_log" ? "no_query_log" : "error", true);
    } finally {
      if (request === this._request) {
        this._loading = false;
        this._renderRows();
      }
    }
  }

  _renderHead() {
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
        this._renderHead();
        this._renderRows();
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
    const language =
      (this._hass && this._hass.locale && this._hass.locale.language) || undefined;
    try {
      return date.toLocaleString(language);
    } catch (err) {
      return date.toLocaleString();
    }
  }

  _clientCell(row) {
    const zone = typeof row.zone === "string" ? row.zone : "";
    const children = zone ? [el("div", { text: zone, className: "zone" })] : [];
    return el("td", { text: row.client || "" }, children);
  }

  _renderRows() {
    const canAllow = this._lists("allow").length > 0;
    const canBlock = this._lists("deny").length > 0;
    const fragment = document.createDocumentFragment();

    for (const row of this._sortedRows()) {
      const cells = [
        el("td", { text: this._formatTime(row.time) }),
        this._clientCell(row),
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
        await this._hass.callService(
          DOMAIN,
          type === "allow" ? "allow_domain" : "block_domain",
          { config_entry_id: this._entry.entry_id, list: select.value, domain }
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

  _stopTimer() {
    clearInterval(this._timer);
    this._timer = undefined;
  }

  _restartTimer() {
    this._stopTimer();
    const seconds = this._config.auto_refresh;
    if (!seconds || !this.isConnected || !this._entry) return;
    this._timer = setInterval(() => {
      // Only refresh the first page, and only while the user is not acting.
      const firstPage = this._rows.length <= this._config.page_size;
      if (document.visibilityState === "visible" && firstPage && !this._pending) {
        this._load(true);
      }
    }, seconds * 1000);
  }
}

if (!customElements.get("ha-blocky-card")) {
  customElements.define("ha-blocky-card", HaBlockyCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "ha-blocky-card")) {
  window.customCards.push({
    type: "ha-blocky-card",
    name: "HA-Blocky query log",
    description: "Blocky's DNS query log with search, filters and allow/block actions.",
  });
}
