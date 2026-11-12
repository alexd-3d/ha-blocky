/*
 * The top lists of the dashboard tab (clients, domains, blocked domains).
 * Every row shows the name, the count and a thin bar split by category; a
 * popover gives the counts and shares per category, the time last seen and,
 * for a blocked domain, the most frequent block reason.
 * `ctx` offers: t(key), language, dateTime(value).
 */

import { el, svg } from "./ha-blocky-dom.js";
import { CATEGORIES, compact, percent, sumCounts } from "./ha-blocky-format.js";
import { swatchLine } from "./ha-blocky-chart.js";

const BAR_WIDTH = 100;
const BAR_HEIGHT = 4;

// The thin bar of a row: one rectangle per category on a track.
function miniBar(categories) {
  const total = sumCounts(categories);
  const bar = svg("svg", {
    class: "mbar",
    viewBox: `0 0 ${BAR_WIDTH} ${BAR_HEIGHT}`,
    preserveAspectRatio: "none",
    "aria-hidden": "true",
  });
  bar.appendChild(svg("rect", { class: "track", x: 0, y: 0, width: BAR_WIDTH, height: BAR_HEIGHT }));
  let x = 0;
  for (const category of CATEGORIES) {
    const width = total ? (categories[category] / total) * BAR_WIDTH : 0;
    if (width <= 0) continue;
    bar.appendChild(
      svg("rect", { class: `seg c-${category}`, x, y: 0, width, height: BAR_HEIGHT })
    );
    x += width;
  }
  return bar;
}

function detailLines(ctx, item) {
  const total = sumCounts(item.categories);
  const lines = [el("div", { text: item.client_name || item.name, className: "ptitle" })];
  if (item.client_name) lines.push(el("div", { text: item.name, className: "sub mono" }));
  for (const category of CATEGORIES) {
    const value = item.categories[category];
    if (!value) continue;
    lines.push(swatchLine(ctx, category, String(value), percent(value, total)));
  }
  if (item.last_seen) {
    lines.push(
      el("div", { className: "line" }, [
        el("span", { text: ctx.t("dash_last_seen"), className: "lname" }),
        el("span", { text: ctx.dateTime(item.last_seen), className: "lvalue" }),
      ])
    );
  }
  if (item.reason) {
    lines.push(
      el("div", { className: "line reason" }, [
        el("span", { text: ctx.t("dash_reason"), className: "lname" }),
        el("span", { text: item.reason, className: "lvalue" }),
      ])
    );
  }
  return lines;
}

// A list of rows. `items` have: name, count, categories and, optionally,
// client_name, last_seen and reason. `isClient` shows the address under the
// name of a client.
export function topList(ctx, popover, items, isClient) {
  const list = el("div", { className: "toplist", attrs: { role: "list" } });
  for (const item of items) {
    const named = isClient && item.client_name;
    const heading = [
      el("span", { text: named ? item.client_name : item.name, className: "tname" }),
      el("span", { text: compact(item.count, ctx.language), className: "tcount" }),
    ];
    const lines = [el("div", { className: "thead" }, heading)];
    if (named) lines.push(el("div", { text: item.name, className: "taddr" }));
    lines.push(miniBar(item.categories));
    const row = el(
      "div",
      {
        className: isClient ? "trow client" : "trow",
        attrs: { role: "listitem", tabindex: "0" },
      },
      lines
    );
    popover.attach(row, () => detailLines(ctx, item));
    list.appendChild(row);
  }
  return list;
}
