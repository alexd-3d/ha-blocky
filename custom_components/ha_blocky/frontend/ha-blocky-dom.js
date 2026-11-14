/*
 * DOM helpers of the HA-Blocky card.
 *
 * Every value from the log, the server or a device is written with
 * textContent. Nothing is ever interpreted as markup.
 */

export const DOMAIN = "ha_blocky";

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

// The protection levels a client can have; only these are ever shown.
export const LEVELS = ["unfiltered", "standard", "restricted", "lockdown"];

// The card's own name of a level (never taken from the server), or "" for
// Standard and for anything unknown: Standard needs no mention.
export function levelLabel(host, level) {
  return LEVELS.includes(level) && level !== "standard" ? host.t(`level_${level}`) : "";
}

// The lines of a client: the name (or the address) first; below it, dimmed,
// the level and the address. A long value is cut by the style sheet; the whole
// text stays available as the title of the line.
export function clientLines(address, name, level) {
  const line = (text, className) => el("div", { text, className, attrs: { title: text } });
  if (name) {
    return [line(name, "main"), line(level ? `${level} · ${address}` : address, "sub")];
  }
  const lines = [line(address, "main")];
  if (level) lines.push(line(level, "sub"));
  return lines;
}

// The cell of a client: its lines, nothing to click. A client is named in the
// Settings tab only. `host` offers: t(key).
export function clientCell(host, address, name, level) {
  const label = typeof address === "string" ? address : "";
  const cell = el("td", { className: "client" });
  cell.replaceChildren(...clientLines(label, nameOf(name), levelLabel(host, level)));
  return cell;
}
