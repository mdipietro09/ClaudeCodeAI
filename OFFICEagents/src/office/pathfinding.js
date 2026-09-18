import { BLOCKED, COLS, ROWS, cellCenter } from "./layout.js";

// A* on the 4-connected cell grid. Returns a list of pixel waypoints
// (collinear cells collapsed) from start cell to goal cell, inclusive.
export function findPath(start, goal) {
  if (start.c === goal.c && start.r === goal.r) return [cellCenter(goal.c, goal.r)];

  const key = (c, r) => r * COLS + c;
  const open = new Map(); // key -> node
  const closed = new Set();
  const h = (c, r) => Math.abs(c - goal.c) + Math.abs(r - goal.r);

  const startNode = { c: start.c, r: start.r, g: 0, f: h(start.c, start.r), parent: null };
  open.set(key(start.c, start.r), startNode);

  let goalNode = null;
  while (open.size > 0) {
    let current = null;
    for (const node of open.values()) if (!current || node.f < current.f) current = node;
    if (current.c === goal.c && current.r === goal.r) {
      goalNode = current;
      break;
    }
    open.delete(key(current.c, current.r));
    closed.add(key(current.c, current.r));

    for (const [dc, dr] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const c = current.c + dc;
      const r = current.r + dr;
      if (c < 0 || c >= COLS || r < 0 || r >= ROWS) continue;
      if (BLOCKED[r][c] && !(c === goal.c && r === goal.r)) continue;
      const k = key(c, r);
      if (closed.has(k)) continue;
      const g = current.g + 1;
      const existing = open.get(k);
      if (!existing || g < existing.g) {
        open.set(k, { c, r, g, f: g + h(c, r), parent: current });
      }
    }
  }

  if (!goalNode) return [cellCenter(goal.c, goal.r)]; // unreachable: jump (shouldn't happen)

  const cells = [];
  for (let n = goalNode; n; n = n.parent) cells.unshift(n);

  // collapse collinear runs so the tween has fewer, longer segments
  const pts = [cells[0]];
  for (let i = 1; i < cells.length - 1; i++) {
    const a = pts[pts.length - 1];
    const b = cells[i];
    const c = cells[i + 1];
    if ((b.c - a.c) * (c.r - b.r) !== (b.r - a.r) * (c.c - b.c)) pts.push(b);
  }
  pts.push(cells[cells.length - 1]);
  return pts.map((p) => cellCenter(p.c, p.r));
}
