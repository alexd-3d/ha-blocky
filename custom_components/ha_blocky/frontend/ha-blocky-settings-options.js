/*
 * The operational half of the Settings tab: the update intervals, the
 * new-domain reporting, the sidebar entry and the hidden clients (a list of
 * addresses edited here and saved with the rest).
 * These are options of the integration; saving them reloads it. The server
 * validates every value again and names the field it refuses.
 * `host` offers: t(key).
 */

import { field, glyphButton } from "./ha-blocky-controls.js";
import { el } from "./ha-blocky-dom.js";

const INTERVALS = [
  ["status_interval", "set_status_interval"],
  ["stats_interval", "set_stats_interval"],
  ["tops_interval", "set_tops_interval"],
];
const BOOLEANS = [
  ["report_existing_domains", "set_report", "set_report_hint"],
  ["show_in_sidebar", "set_sidebar", "set_sidebar_hint"],
];

// What an address field may hold: the characters of an IPv4 or IPv6 address
// (the server checks the address itself and refuses anything else).
const ADDRESS_TEXT = /^[0-9a-fA-F.:]{2,45}$/;
const MAX_HIDDEN = 50;

function whole(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

export class OptionsForm {
  constructor(host) {
    this._host = host;
    this._loaded = undefined;
    this._inputs = {};
    this._fields = {};
    this._hidden = [];
    this._hiddenBody = el("div");
    this.element = el("div");
  }

  // The clients of the draft list as the server described them: a clean
  // address, and the name kept for it (shown, never used as a value).
  _readHidden(value) {
    const out = [];
    for (const item of Array.isArray(value) ? value : []) {
      if (!item || typeof item.address !== "string") continue;
      if (!ADDRESS_TEXT.test(item.address)) continue;
      const name = typeof item.client_name === "string" ? item.client_name.slice(0, 64) : "";
      out.push({ address: item.address, name });
    }
    return out.slice(0, MAX_HIDDEN);
  }

  _drawHidden() {
    const t = (key) => this._host.t(key);
    const rows = this._hidden.map((item) => {
      const remove = glyphButton(t("prot_rules_remove"), "rule_remove");
      remove.addEventListener("click", () => {
        this._hidden = this._hidden.filter((other) => other.address !== item.address);
        this._drawHidden();
      });
      return el("div", { className: "rulerow" }, [
        el("span", {
          text: item.name ? `${item.address} (${item.name})` : item.address,
          className: "domain",
          attrs: { title: item.address },
        }),
        remove,
      ]);
    });
    if (!rows.length) rows.push(el("div", { className: "sub", text: t("set_hidden_empty") }));
    this._hiddenBody.replaceChildren(...rows);
  }

  _hiddenGroup() {
    const t = (key) => this._host.t(key);
    const error = el("div", { className: "rowerror", attrs: { hidden: "" } });
    const input = el("input", {
      attrs: {
        type: "text",
        maxlength: 45,
        autocomplete: "off",
        spellcheck: "false",
        placeholder: t("set_hidden_placeholder"),
        "aria-label": t("set_group_hidden"),
      },
    });
    const add = el("button", { text: t("prot_rules_add"), attrs: { type: "button" } });
    const submit = () => {
      const value = input.value.trim();
      if (!value) return;
      const problem = !ADDRESS_TEXT.test(value)
        ? "serr_invalid_address"
        : this._hidden.length >= MAX_HIDDEN
          ? "serr_too_many_clients"
          : "";
      error.textContent = problem ? t(problem) : "";
      error.hidden = !problem;
      if (problem) return;
      if (!this._hidden.some((item) => item.address === value)) {
        // Normalised by the server on saving; a repeat is simply kept once.
        this._hidden.push({ address: value, name: "" });
      }
      input.value = "";
      this._drawHidden();
    };
    add.addEventListener("click", submit);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        submit();
      }
    });
    this._fields.hidden_clients = {
      showError: (text) => {
        error.textContent = text || "";
        error.hidden = !text;
      },
    };
    this._drawHidden();
    return el("div", { className: "group" }, [
      el("h4", { className: "gtitle", text: t("set_group_hidden") }),
      el("div", { className: "hint", text: t("set_hidden_hint") }),
      this._hiddenBody,
      el("div", { className: "btnrow" }, [input, add]),
      error,
    ]);
  }

  // Draw the form for an entry as the server described it.
  fill(entry) {
    const t = (key) => this._host.t(key);
    this._inputs = {};
    this._fields = {};
    const source = entry && typeof entry === "object" ? entry : {};
    const intervals =
      source.intervals && typeof source.intervals === "object" ? source.intervals : {};
    this._hidden = this._readHidden(source.hidden_clients);
    this._loaded = {
      intervals: {},
      booleans: {},
      hidden: this._hidden.map((item) => item.address),
    };
    const intervalBoxes = [];
    const generalBoxes = [];

    for (const [key, label] of INTERVALS) {
      const spec = intervals[key] || {};
      const value = whole(spec.value);
      this._loaded.intervals[key] = value;
      const input = el("input", {
        attrs: { type: "number", step: "1", min: whole(spec.min), max: whole(spec.max) },
      });
      input.value = String(value);
      const range = `${whole(spec.min)} - ${whole(spec.max)}`;
      const hint = `${range}, ${t("set_default")} ${whole(spec.default)}`;
      this._inputs[key] = input;
      this._fields[key] = field(t(label), input, hint);
      intervalBoxes.push(this._fields[key]);
    }
    intervalBoxes.push(el("div", { className: "hint", text: t("set_interval_note") }));

    for (const [key, label, hint] of BOOLEANS) {
      const on = source[key] === true;
      this._loaded.booleans[key] = on;
      const input = el("input", { attrs: { type: "checkbox" } });
      input.checked = on;
      this._inputs[key] = input;
      const box = field(t(label), input, hint ? t(hint) : "");
      box.classList.add("check");
      this._fields[key] = box;
      generalBoxes.push(box);
    }

    // One titled group per kind of option; they are saved together.
    const group = (titleKey, children) =>
      el("div", { className: "group" }, [
        el("h4", { className: "gtitle", text: t(titleKey) }),
        ...children,
      ]);
    this.element.replaceChildren(
      group("set_group_intervals", intervalBoxes),
      group("set_group_general", generalBoxes),
      this._hiddenGroup()
    );
  }

  // The values that differ from what was loaded, as the command takes them.
  changes() {
    const out = {};
    if (!this._loaded) return out;
    for (const [key] of INTERVALS) {
      const value = whole(this._inputs[key].value);
      if (value !== this._loaded.intervals[key]) out[key] = value;
    }
    for (const [key] of BOOLEANS) {
      if (this._inputs[key].checked !== this._loaded.booleans[key]) {
        out[key] = this._inputs[key].checked;
      }
    }
    const hidden = this._hidden.map((item) => item.address);
    if (hidden.join(",") !== this._loaded.hidden.join(",")) out.hidden_clients = hidden;
    return out;
  }

  // Show the error of one field (by its key in the command); clear the rest.
  showError(key, text) {
    for (const box of Object.values(this._fields)) box.showError("");
    if (text && Object.prototype.hasOwnProperty.call(this._fields, key)) {
      this._fields[key].showError(text);
      return true;
    }
    return false;
  }
}
