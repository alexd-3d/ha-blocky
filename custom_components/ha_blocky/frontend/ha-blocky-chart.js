/*
 * The "Queries over time" chart: stacked bars in inline SVG, a sparse time
 * axis, a legend and a popover per bar. The bars scale with the width of the
 * card (the SVG is stretched; no text is drawn inside it). Every colour comes
 * from a class that the style sheet maps to a `--hb-color-*` custom property.
 * `ctx` offers: t(key), language, time(value, unit, full).
 */

import { el, svg } from "./ha-blocky-dom.js";
import {
  CATEGORIES,
  PLOT_HEIGHT,
  SLOT,
  compact,
  labelStep,
  percent,
  stackBars,
  sumCounts,
} from "./ha-blocky-format.js";

const GRID_LINES = [0, 25, 50, 75, 100];

// One legend item or popover line: a colour swatch, a name and a number.
export function swatchLine(ctx, category, value, share) {
  const parts = [
    el("span", { className: `sw c-${category}` }),
    el("span", { text: ctx.t(`cat_${category}`), className: "lname" }),
    el("span", { text: value, className: "lvalue" }),
  ];
  if (share) parts.push(el("span", { text: share, className: "lshare" }));
  return el("div", { className: "line" }, parts);
}

function popoverLines(ctx, bucket, unit) {
  const total = sumCounts(bucket.categories);
  const lines = [
    el("div", { text: ctx.time(bucket.start, unit, true), className: "ptitle" }),
  ];
  for (const category of CATEGORIES) {
    const value = bucket.categories[category];
    if (!value) continue;
    lines.push(swatchLine(ctx, category, String(value), percent(value, total)));
  }
  lines.push(
    el("div", { className: "line total" }, [
      el("span", { text: ctx.t("dash_total_label"), className: "lname" }),
      el("span", { text: String(total), className: "lvalue" }),
    ])
  );
  return lines;
}

// The chart for `buckets` ([{ start, categories }]); `totals` are the counts
// of the whole period, shown in the legend.
export function buildChart(ctx, popover, buckets, unit, totals) {
  const { peak, bars } = stackBars(buckets);
  const slots = Math.max(1, buckets.length);
  const graphic = svg(
    "svg",
    {
      class: "bars",
      viewBox: `0 0 ${slots * SLOT} ${PLOT_HEIGHT}`,
      preserveAspectRatio: "none",
      role: "group",
      "aria-label": ctx.t("dash_chart_title"),
    },
    GRID_LINES.map((y) => svg("line", { class: "grid", x1: 0, x2: slots * SLOT, y1: y, y2: y }))
  );
  bars.forEach((bar, index) => {
    for (const segment of bar.segments) {
      graphic.appendChild(
        svg("rect", {
          class: `seg c-${segment.category}`,
          x: bar.x,
          y: segment.y,
          width: bar.width,
          height: segment.height,
        })
      );
    }
    const hit = svg("rect", {
      class: "hit",
      x: bar.slot,
      y: 0,
      width: SLOT,
      height: PLOT_HEIGHT,
      tabindex: 0,
      role: "img",
      "aria-label": `${ctx.time(buckets[index].start, unit, true)}: ${bar.total}`,
    });
    popover.attach(hit, () => popoverLines(ctx, buckets[index], unit));
    graphic.appendChild(hit);
  });

  const step = labelStep(buckets.length);
  const axis = el(
    "div",
    { className: "axis", attrs: { "aria-hidden": "true" } },
    buckets.map((bucket, index) =>
      el("span", {
        className: "tick",
        text: index % step === 0 ? ctx.time(bucket.start, unit, false) : "",
      })
    )
  );
  // Each legend entry explains its kind on hover and on keyboard focus.
  const legend = el(
    "div",
    { className: "legend" },
    CATEGORIES.map((category) => {
      const line = swatchLine(ctx, category, compact(totals[category], ctx.language), "");
      line.setAttribute("title", ctx.t(`cat_hint_${category}`));
      line.setAttribute("tabindex", "0");
      return line;
    })
  );
  return el("div", { className: "chart" }, [
    el("div", { className: "plot" }, [
      graphic,
      el("div", { className: "peak", text: compact(peak, ctx.language) }),
    ]),
    axis,
    legend,
  ]);
}
