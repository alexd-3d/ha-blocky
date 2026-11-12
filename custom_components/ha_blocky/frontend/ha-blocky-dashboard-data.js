/*
 * The answer of the dashboard command, reduced to clean values of known
 * kinds. Pure: no DOM. Texts are cut to the length the server allows; counts
 * are finite numbers of at least 0; unknown fields are dropped.
 */

import { categoryCounts, count } from "./ha-blocky-format.js";

function list(value) {
  return Array.isArray(value) ? value : [];
}

function text(value, max) {
  return typeof value === "string" ? value.slice(0, max) : "";
}

// The rows of a top list; a client is identified by its address.
function items(value, isClient) {
  return list(value)
    .filter((item) => item && typeof (isClient ? item.address : item.name) === "string")
    .map((item) => ({
      name: text(isClient ? item.address : item.name, 253),
      client_name: text(item.client_name, 64),
      count: count(item.count),
      categories: categoryCounts(item.categories),
      last_seen: text(item.last_seen, 40),
      reason: text(item.reason, 120),
    }));
}

export function normalize(result) {
  const totals = result.totals || {};
  const buckets = result.buckets || {};
  const meta = result.meta || {};
  const average = totals.avg_duration_ms === null ? NaN : Number(totals.avg_duration_ms);
  return {
    queries: count(totals.queries),
    unique: count(totals.unique_domains),
    average: Number.isFinite(average) ? average : undefined,
    categories: categoryCounts(totals.categories),
    unit: buckets.unit === "day" ? "day" : "hour",
    buckets: list(buckets.items)
      .filter((item) => item && typeof item.start === "string")
      .map((item) => ({
        start: new Date(item.start),
        categories: categoryCounts(item.categories),
      }))
      .filter((bucket) => !Number.isNaN(bucket.start.getTime())),
    clients: items(result.top_clients, true),
    domains: items(result.top_domains, false),
    blocked: items(result.top_blocked, false),
    version: text(meta.version, 32),
    blockyVersion: text(meta.blocky_version, 32),
    generated: new Date(meta.generated_at),
  };
}
