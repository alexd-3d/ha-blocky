/*
 * Pure helpers of the dashboard tab: the query categories, number formatting,
 * the geometry of the stacked bars and the remembered choices. No DOM and no
 * imports, so it can be checked on its own.
 *
 * The colour of a category is never set from here: the style sheet maps the
 * class `c-<category>` to the custom property `--hb-color-<category>`.
 */

// The categories of a query, in the order they are stacked (bottom first).
export const CATEGORIES = ["resolved", "cached", "local", "blocked", "other"];
export const PERIODS = ["today", "24h", "7d", "30d"];
export const ROW_CHOICES = [5, 10, 20];

// The width of the slot of one bar in the chart's coordinate system, and the
// height of the whole chart.
export const SLOT = 10;
export const PLOT_HEIGHT = 100;
const BAR_PADDING = 1.5;
const STORAGE_PREFIX = "ha_blocky.";

// A count from the server: a finite number of at least 0, else 0.
export function count(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : 0;
}

// The counts of the known categories only, each a clean number.
export function categoryCounts(source) {
  const counts = {};
  for (const category of CATEGORIES) {
    counts[category] = count(source && typeof source === "object" ? source[category] : 0);
  }
  return counts;
}

export function sumCounts(counts) {
  return CATEGORIES.reduce((sum, category) => sum + counts[category], 0);
}

// 25100 -> "25.1K" (in the language of the user, when the browser knows it).
export function compact(value, language) {
  const number = count(value);
  try {
    return new Intl.NumberFormat(language, {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(number);
  } catch (err) {
    return String(Math.round(number));
  }
}

// A share in percent with at most one decimal: "12.3%", "5%", "0%".
export function percent(part, total) {
  const whole = count(total);
  if (!whole) return "0%";
  return `${Math.round((1000 * count(part)) / whole) / 10}%`;
}

// Every how many buckets a label is shown, for at most `maxLabels` labels.
export function labelStep(buckets, maxLabels = 6) {
  return Math.max(1, Math.ceil(buckets / maxLabels));
}

// The rectangles of a stacked bar chart. `items` are [{ categories }] with
// clean counts. Every bar has a slot of SLOT units; the tallest bar fills the
// plot. Segments are stacked from the bottom in the order of CATEGORIES.
export function stackBars(items) {
  const totals = items.map((item) => sumCounts(item.categories));
  const peak = Math.max(1, ...totals);
  const bars = items.map((item, index) => {
    let top = PLOT_HEIGHT;
    const segments = [];
    for (const category of CATEGORIES) {
      const height = (item.categories[category] / peak) * PLOT_HEIGHT;
      if (height <= 0) continue;
      top -= height;
      segments.push({ category, y: top, height });
    }
    return {
      x: index * SLOT + BAR_PADDING,
      width: SLOT - 2 * BAR_PADDING,
      slot: index * SLOT,
      total: totals[index],
      segments,
    };
  });
  return { peak, bars };
}

// The date and time formats of the dashboard, in the language of the user.
// Times are shown in the time zone of the browser.
export function timeFormats(language) {
  const make = (options) => {
    try {
      return new Intl.DateTimeFormat(language, options);
    } catch (err) {
      return new Intl.DateTimeFormat(undefined, options);
    }
  };
  const clock = { hour: "2-digit", minute: "2-digit" };
  const day = { day: "numeric", month: "short" };
  return {
    hourAxis: make({ hour: "numeric" }),
    dayAxis: make(day),
    hourFull: make({ weekday: "short", ...day, ...clock }),
    dayFull: make({ weekday: "short", ...day }),
    dateTime: make({ ...day, ...clock }),
    clock: make({ ...clock, second: "2-digit" }),
  };
}

// The member of `allowed` whose text equals `value`, else `fallback`.
export function choose(value, allowed, fallback) {
  const text = String(value);
  const found = allowed.find((item) => String(item) === text);
  return found === undefined ? fallback : found;
}

// A choice remembered by this browser, validated against the allowed values.
export function readChoice(name, allowed, fallback) {
  try {
    return choose(window.localStorage.getItem(STORAGE_PREFIX + name), allowed, fallback);
  } catch (err) {
    return fallback;
  }
}

export function writeChoice(name, value) {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + name, String(value));
  } catch (err) {
    // Storage may be blocked; the choice is then simply not remembered.
  }
}
