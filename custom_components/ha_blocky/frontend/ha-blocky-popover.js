/*
 * The one popover of the dashboard tab. It is shown on hover (a mouse), on a
 * tap (touch) or on Enter/Space (keyboard), sits inside the bounds of the
 * card and closes on a tap outside, on Escape and when anything scrolls.
 * The content is built by the caller from DOM nodes; nothing is parsed.
 */

import { el, place } from "./ha-blocky-dom.js";

const GAP = 6;
let nextId = 0;

export class Popover {
  // `root` is the positioned element (position: relative) the popover sits in.
  constructor(root) {
    this._root = root;
    this._anchor = undefined;
    this.element = el("div", {
      className: "pop",
      attrs: { role: "tooltip", id: `hb-pop-${++nextId}`, hidden: "" },
    });
    root.appendChild(this.element);
    this._outside = (event) => {
      const path = event.composedPath();
      if (!path.includes(this.element) && !path.includes(this._anchor)) this.hide();
    };
    this._escape = (event) => {
      if (event.key === "Escape") this.hide();
    };
    this._scroll = () => this.hide();
  }

  get isOpen() {
    return !this.element.hidden;
  }

  // Show the popover below the anchor (above it when there is no room).
  show(anchor, nodes) {
    this.hide();
    this._anchor = anchor;
    this.element.replaceChildren(...nodes);
    this.element.hidden = false;
    anchor.setAttribute("aria-describedby", this.element.id);

    const root = this._root.getBoundingClientRect();
    const box = anchor.getBoundingClientRect();
    const pop = this.element.getBoundingClientRect();
    const middle = box.left - root.left + box.width / 2;
    const left = Math.max(0, Math.min(middle - pop.width / 2, root.width - pop.width));
    let top = box.bottom - root.top + GAP;
    if (top + pop.height > root.height) {
      top = Math.max(0, box.top - root.top - pop.height - GAP);
    }
    place(this.element, left, top);

    document.addEventListener("pointerdown", this._outside, true);
    document.addEventListener("keydown", this._escape, true);
    window.addEventListener("scroll", this._scroll, true);
  }

  hide() {
    if (this.element.hidden) return;
    document.removeEventListener("pointerdown", this._outside, true);
    document.removeEventListener("keydown", this._escape, true);
    window.removeEventListener("scroll", this._scroll, true);
    if (this._anchor) this._anchor.removeAttribute("aria-describedby");
    this._anchor = undefined;
    this.element.hidden = true;
    this.element.replaceChildren();
  }

  // Make `anchor` open the popover with the nodes `build()` returns.
  attach(anchor, build) {
    const open = () => this.show(anchor, build());
    anchor.addEventListener("pointerenter", (event) => {
      if (event.pointerType === "mouse") open();
    });
    anchor.addEventListener("pointerleave", (event) => {
      if (event.pointerType === "mouse" && this._anchor === anchor) this.hide();
    });
    anchor.addEventListener("click", (event) => {
      if (this._anchor !== anchor) {
        open();
      } else if (event.pointerType !== "mouse") {
        this.hide();
      }
    });
    anchor.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      if (this._anchor === anchor) {
        this.hide();
      } else {
        open();
      }
    });
    anchor.addEventListener("blur", () => {
      if (this._anchor === anchor) this.hide();
    });
  }
}
