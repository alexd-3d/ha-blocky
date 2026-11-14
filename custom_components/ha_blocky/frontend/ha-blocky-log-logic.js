/*
 * Pure logic of the Query log tab: no DOM, no imports, so it can be checked on
 * its own. The levels are the card's own fixed names; a list's levels come from
 * the server (`ha_blocky/config`) and are checked against them again here.
 */

const LEVEL_NAMES = ["unfiltered", "standard", "restricted", "lockdown"];

// The same rule as the server's: only the characters of an IP address, 45 at
// most. A value that fails is not sent.
const IP_FILTER = /^[0-9a-fA-F.:]{0,45}$/;

export function ipFilterOk(value) {
  return typeof value === "string" && IP_FILTER.test(value.trim());
}

// The level of a log row; a row without a level is a Standard client's.
export function levelOfRow(row) {
  return row && LEVEL_NAMES.includes(row.level) ? row.level : "standard";
}

// The levels whose answers the list `name` changes (empty when unknown).
export function listLevels(lists, name) {
  const list = (Array.isArray(lists) ? lists : []).find((item) => item && item.name === name);
  return list && Array.isArray(list.levels)
    ? list.levels.filter((level) => LEVEL_NAMES.includes(level))
    : [];
}

// The list to preselect for a client of `level`: of the lists of this `type`
// ("allow" or "deny") that change that level's answers, the most specific one
// (the fewest levels). Undefined when none does (then the first list stays).
export function preferredList(lists, type, level) {
  let best;
  for (const list of Array.isArray(lists) ? lists : []) {
    if (!list || list.type !== type) continue;
    const levels = listLevels(lists, list.name);
    if (!levels.includes(level)) continue;
    if (best === undefined || levels.length < best.size) {
      best = { name: list.name, size: levels.length };
    }
  }
  return best && best.name;
}

// The ids of the rows an action on `domain` changes the answer for: rows of
// that domain whose client's level is among `levels`. Rows of other levels
// are left alone.
export function affectedRowIds(rows, domain, levels) {
  if (typeof domain !== "string" || !domain) return [];
  const wanted = domain.toLowerCase();
  return (Array.isArray(rows) ? rows : [])
    .filter(
      (row) =>
        row &&
        typeof row.domain === "string" &&
        row.domain.toLowerCase() === wanted &&
        levels.includes(levelOfRow(row))
    )
    .map((row) => row.id);
}
