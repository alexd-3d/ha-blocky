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

// Turn rows (in display order) into [{ row, count }] entries. With `enabled`,
// rows with the same client, domain, query type and response type become one
// entry: `row` is the latest of them and `count` how many there were. An entry
// stands where its first row stood. Without `enabled` every row is its own
// entry. The rows themselves are never changed.
export function groupRows(rows, enabled) {
  if (!enabled) return rows.map((row) => ({ row, count: 1 }));
  const groups = new Map();
  for (const row of rows) {
    const key = JSON.stringify([
      row.client,
      row.domain,
      row.query_type,
      row.response_type,
    ]);
    const group = groups.get(key);
    if (group === undefined) {
      groups.set(key, { row, count: 1 });
    } else {
      group.count += 1;
      if (isNewer(row, group.row)) group.row = row;
    }
  }
  return Array.from(groups.values());
}
