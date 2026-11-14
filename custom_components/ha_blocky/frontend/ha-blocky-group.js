/*
 * Grouping of repeated log rows. Pure display logic: no DOM, no imports, so
 * it can be checked on its own.
 */

function isNewer(row, other) {
  const left = Number(row.id);
  const right = Number(other.id);
  if (Number.isFinite(left) && Number.isFinite(right)) return left > right;
  return String(row.time || "") > String(other.time || "");
}

// Turn rows (in display order) into [{ row, count, types }] entries. With
// `enabled`, rows with the same client, domain, query type and response type
// become one entry: `row` is the latest of them and `count` how many there
// were. With `ignoreType` as well, rows that differ only in the query type
// merge too, and `types` lists the distinct query types of the entry (sorted).
// An entry stands where its first row stood. Without `enabled` every row is
// its own entry. The rows themselves are never changed.
export function groupRows(rows, enabled, ignoreType = false) {
  const typesOf = (row) => (row.query_type ? [String(row.query_type)] : []);
  if (!enabled) return rows.map((row) => ({ row, count: 1, types: typesOf(row) }));
  const merge = ignoreType === true;
  const groups = new Map();
  for (const row of rows) {
    const key = JSON.stringify(
      merge
        ? [row.client, row.domain, row.response_type]
        : [row.client, row.domain, row.query_type, row.response_type]
    );
    const group = groups.get(key);
    if (group === undefined) {
      groups.set(key, { row, count: 1, types: new Set(typesOf(row)) });
    } else {
      group.count += 1;
      for (const type of typesOf(row)) group.types.add(type);
      if (isNewer(row, group.row)) group.row = row;
    }
  }
  return Array.from(groups.values(), (group) => ({
    row: group.row,
    count: group.count,
    types: Array.from(group.types).sort(),
  }));
}
