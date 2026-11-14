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
// The default colour of each category. The style sheet defines the custom
// properties from this table, and "Reset to defaults" shows it.
export const DEFAULT_COLORS = {
  resolved: "#26a69a",
  cached: "#42a5f5",
  local: "#ab47bc",
  blocked: "#ef5350",
  other: "#9e9e9e",
};
const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

// The colour in lower case when it is exactly #rrggbb, else "".
export function validColor(value) {
  return typeof value === "string" && HEX_COLOR.test(value) ? value.toLowerCase() : "";
}

// The text of the one style element that overrides the category colours. It
// is composed only from the fixed property names and values that passed
// validColor, so nothing else can ever get into a style sheet.
export function colorCss(colors) {
  const rules = [];
  for (const category of CATEGORIES) {
    const color = validColor(colors && colors[category]);
    if (color) rules.push(`--hb-color-${category}: ${color};`);
  }
  return rules.length ? `:host { ${rules.join(" ")} }` : "";
}

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

// The language for dates and times from the profile of Home Assistant
// (`hass.locale`): "system" lets the browser decide (undefined), anything else
// uses the language of the profile. Never throws; `locale` may be undefined.
export function timeLanguage(locale, fallback) {
  const object = locale && typeof locale === "object" ? locale : {};
  if (object.time_format === "system") return undefined;
  return (typeof object.language === "string" && object.language) || fallback || undefined;
}

// The Intl.DateTimeFormat options for the time format of the profile:
// "24" -> 24-hour clock, "12" -> 12-hour clock, "language" and "system" ->
// the default of the language or the browser (no option).
export function timeOptions(locale) {
  const setting = locale && typeof locale === "object" ? locale.time_format : undefined;
  if (setting === "24") return { hourCycle: "h23" };
  if (setting === "12") return { hour12: true };
  return {};
}

// The date and time formats of the card, following the profile of Home
// Assistant (`locale`: { language, time_format }). Times are shown in the local
// clock of the browser. This is the only place that formats a date or a time.
export function timeFormats(locale, fallbackLanguage) {
  const language = timeLanguage(locale, fallbackLanguage);
  const clockOptions = timeOptions(locale);
  const make = (options, withClock = true) => {
    const all = withClock ? { ...options, ...clockOptions } : options;
    try {
      return new Intl.DateTimeFormat(language, all);
    } catch (err) {
      return new Intl.DateTimeFormat(undefined, all);
    }
  };
  const clock = { hour: "2-digit", minute: "2-digit" };
  const day = { day: "numeric", month: "short" };
  let hourAxis = make({ hour: "numeric" });
  // A 24-hour clock reads better as "22:00" than as a bare "22".
  if (["h23", "h24"].includes(hourAxis.resolvedOptions().hourCycle)) {
    hourAxis = make(clock);
  }
  return {
    hourAxis,
    dayAxis: make(day, false),
    hourFull: make({ weekday: "short", ...day, ...clock }),
    dayFull: make({ weekday: "short", ...day }, false),
    dateTime: make({ ...day, ...clock }),
    clock: make({ ...clock, second: "2-digit" }),
    log: make({ year: "numeric", month: "2-digit", day: "2-digit", ...clock, second: "2-digit" }),
  };
}

// The text of a date (a Date, a timestamp or a date string) in a format from
// timeFormats, or "" when it is not a date.
export function formatWhen(format, value) {
  if (value === null || value === undefined) return "";
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? "" : format.format(date);
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

// Whether this browser has remembered a valid choice of `name`.
export function hasChoice(name, allowed) {
  try {
    const found = window.localStorage.getItem(STORAGE_PREFIX + name);
    return found !== null && choose(found, allowed, undefined) !== undefined;
  } catch (err) {
    return false;
  }
}

export function writeChoice(name, value) {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + name, String(value));
  } catch (err) {
    // Storage may be blocked; the choice is then simply not remembered.
  }
}
