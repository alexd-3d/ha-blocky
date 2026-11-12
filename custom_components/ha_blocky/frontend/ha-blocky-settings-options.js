/*
 * The operational half of the Settings tab: the update intervals, the
 * new-domain reporting, the sidebar entry and the names of the manual lists.
 * These are options of the integration; saving them reloads it. The server
 * validates every value again and names the field it refuses.
 * `host` offers: t(key).
 */

import { field } from "./ha-blocky-controls.js";
import { el } from "./ha-blocky-dom.js";

const INTERVALS = [
  ["status_interval", "set_status_interval"],
  ["stats_interval", "set_stats_interval"],
  ["tops_interval", "set_tops_interval"],
];
const BOOLEANS = [
  ["report_existing_domains", "set_report", "set_report_hint"],
  ["show_in_sidebar", "set_sidebar", ""],
];
const LISTS = [
  ["allow_lists", "set_allow_lists"],
  ["deny_lists", "set_deny_lists"],
  ["exact_only_lists", "set_exact_lists"],
];

function names(value) {
  return Array.isArray(value) ? value.filter((name) => typeof name === "string") : [];
}

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
    this.element = el("div");
  }

  // Draw the form for an entry as the server described it.
  fill(entry) {
    const t = (key) => this._host.t(key);
    this._inputs = {};
    this._fields = {};
    const source = entry && typeof entry === "object" ? entry : {};
    const intervals =
      source.intervals && typeof source.intervals === "object" ? source.intervals : {};
    this._loaded = { intervals: {}, booleans: {}, lists: {} };
    const boxes = [];

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
      boxes.push(this._fields[key]);
    }
    boxes.push(el("div", { className: "hint", text: t("set_interval_note") }));

    for (const [key, label, hint] of BOOLEANS) {
      const on = source[key] === true;
      this._loaded.booleans[key] = on;
      const input = el("input", { attrs: { type: "checkbox" } });
      input.checked = on;
      this._inputs[key] = input;
      const box = field(t(label), input, hint ? t(hint) : "");
      box.classList.add("check");
      this._fields[key] = box;
      boxes.push(box);
    }

    for (const [key, label] of LISTS) {
      const current = names(source[key]);
      this._loaded.lists[key] = current;
      const input = el("input", {
        attrs: { type: "text", maxlength: 700, autocomplete: "off" },
      });
      input.value = current.join(", ");
      this._inputs[key] = input;
      this._fields[key] = field(t(label), input, "");
      boxes.push(this._fields[key]);
    }
    boxes.push(el("div", { className: "hint", text: t("set_lists_hint") }));
    this.element.replaceChildren(...boxes);
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
    for (const [key] of LISTS) {
      const value = this._inputs[key].value
        .split(",")
        .map((name) => name.trim())
        .filter((name) => name !== "");
      if (value.join("\n") !== this._loaded.lists[key].join("\n")) out[key] = value;
    }
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
