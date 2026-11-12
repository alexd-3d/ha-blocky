/*
 * Small shared controls: a joined group of buttons and a labelled field.
 * Texts are the card's own (looked up by key), never from the server.
 */

import { el } from "./ha-blocky-dom.js";

// A joined group of buttons, one of them pressed. `options` are
// [{ value, label }]; `onPick` gets the chosen value. The element offers
// `mark(value)` to change the pressed button from outside.
export function buttonGroup(label, options, current, onPick) {
  const group = el("div", {
    className: "btngroup",
    attrs: { role: "group", "aria-label": label },
  });
  const buttons = options.map((option) => {
    const button = el("button", { text: option.label, attrs: { type: "button" } });
    button.addEventListener("click", () => {
      group.mark(option.value);
      onPick(option.value);
    });
    return { value: option.value, button };
  });
  group.mark = (value) => {
    for (const entry of buttons) {
      const on = entry.value === value;
      entry.button.className = on ? "on" : "";
      entry.button.setAttribute("aria-pressed", String(on));
    }
  };
  group.mark(current);
  group.append(...buttons.map((entry) => entry.button));
  return group;
}

// A label above an input (or a checkbox beside its label), a muted hint and
// room for the error of the field.
export function field(labelText, control, hintText) {
  const error = el("div", { className: "rowerror", attrs: { hidden: "" } });
  const box = el("div", { className: "field" }, [
    el("label", { className: "flabel" }, [el("span", { text: labelText }), control]),
  ]);
  if (hintText) box.appendChild(el("div", { className: "hint", text: hintText }));
  box.appendChild(error);
  box.showError = (text) => {
    error.textContent = text || "";
    error.hidden = !text;
  };
  return box;
}
