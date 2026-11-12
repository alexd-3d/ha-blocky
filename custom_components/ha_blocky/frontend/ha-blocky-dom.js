/*
 * DOM helpers of the HA-Blocky card.
 *
 * Every value from the log, the server or a device is written with
 * textContent. Nothing is ever interpreted as markup.
 */

export const DOMAIN = "ha_blocky";
const MAX_NAME_LENGTH = 64;

export function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = String(options.text);
  for (const [name, value] of Object.entries(options.attrs || {})) {
    node.setAttribute(name, String(value));
  }
  for (const child of children) node.appendChild(child);
  return node;
}

// The namespace of SVG elements: an identifier, nothing is loaded from it.
export const SVG_NS = "http://www.w3.org/2000/svg";

// An SVG element. The attribute values are numbers computed by the card or
// fixed strings of the card, never text from the log.
export function svg(tag, attrs = {}, children = []) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs)) {
    node.setAttribute(name, String(value));
  }
  for (const child of children) node.appendChild(child);
  return node;
}

// Put an absolutely positioned element at pixel offsets. This is the only
// inline style of the card: two numbers, never a text from the log.
export function place(node, left, top) {
  node.style.left = `${Math.round(Number(left) || 0)}px`;
  node.style.top = `${Math.round(Number(top) || 0)}px`;
}

// A server-side name, or "" when the value is anything but a text.
export function nameOf(value) {
  return typeof value === "string" ? value : "";
}

// The lines of a client: the name (or the address) first; below it, dimmed,
// the zone and the address.
function clientLines(address, name, zone) {
  if (name) {
    const detail = zone ? `${zone} · ${address}` : address;
    return [
      el("div", { text: name, className: "main" }),
      el("div", { text: detail, className: "sub" }),
    ];
  }
  const lines = [el("div", { text: address, className: "main" })];
  if (zone) lines.push(el("div", { text: zone, className: "sub" }));
  return lines;
}

// The cell of a client. A click turns it into a text input: Enter saves the
// name on the server (an empty name clears it), Escape cancels.
// `host` offers: hass, t(key), refresh().
export function clientCell(host, address, name, zone) {
  const known = typeof address === "string" && address !== "";
  const label = known ? address : "";
  const shownName = nameOf(name);
  const shownZone = typeof zone === "string" ? zone : "";
  const cell = el("td", { className: "client" });
  const draw = () => cell.replaceChildren(...clientLines(label, shownName, shownZone));
  draw();
  if (!known) return cell;

  cell.setAttribute("tabindex", "0");
  cell.setAttribute("role", "button");
  cell.setAttribute("title", host.t("client_edit"));

  const edit = () => {
    if (cell.querySelector("input")) return;
    const input = el("input", {
      className: "nameedit",
      attrs: {
        type: "text",
        maxlength: MAX_NAME_LENGTH,
        placeholder: host.t("client_name_placeholder"),
        "aria-label": host.t("client_edit"),
      },
    });
    input.value = shownName;
    const error = el("div", { className: "rowerror" });
    error.hidden = true;
    let saving = false;

    const save = async () => {
      saving = true;
      input.disabled = true;
      try {
        await host.hass.callWS({
          type: `${DOMAIN}/set_client_name`,
          ip: address,
          name: input.value.trim(),
        });
      } catch (err) {
        saving = false;
        input.disabled = false;
        error.textContent = (err && err.message) || host.t("error");
        error.hidden = false;
        input.focus();
        return;
      }
      await host.refresh();
    };

    input.addEventListener("keydown", (event) => {
      event.stopPropagation();
      if (event.key === "Escape") {
        event.preventDefault();
        draw();
      } else if (event.key === "Enter") {
        event.preventDefault();
        if (!saving) save();
      }
    });
    input.addEventListener("click", (event) => event.stopPropagation());
    input.addEventListener("blur", () => {
      if (!saving) draw();
    });
    cell.replaceChildren(input, error);
    input.focus();
  };

  cell.addEventListener("click", edit);
  cell.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target === cell) {
      event.preventDefault();
      edit();
    }
  });
  return cell;
}
