// Office coordinate system: a fixed 960x576 stage divided into 32px grid
// cells (30 cols x 18 rows). Pathfinding runs on the cell grid; rendering
// uses pixel positions. Cell (c, r) has its center at (c*32+16, r*32+16).

export const CELL = 32;
export const COLS = 30;
export const ROWS = 18;
export const STAGE_W = COLS * CELL; // 960
export const STAGE_H = ROWS * CELL; // 576

export const cellCenter = (c, r) => ({ x: c * CELL + CELL / 2, y: r * CELL + CELL / 2 });
export const posToCell = (x, y) => ({
  c: Math.min(COLS - 1, Math.max(0, Math.floor(x / CELL))),
  r: Math.min(ROWS - 1, Math.max(0, Math.floor(y / CELL))),
});

// ---- Zones (px rects, for rendering the floor plan) ----
export const ZONES = {
  desks: { x: 2 * CELL, y: 2 * CELL, w: 15 * CELL, h: 9 * CELL, label: "Workstations", floor: "#111113" },
  meeting: { x: 20 * CELL, y: 2 * CELL, w: 9 * CELL, h: 6 * CELL, label: "Meeting Room", floor: "#121316" },
  breakroom: { x: 20 * CELL, y: 12 * CELL, w: 9 * CELL, h: 5 * CELL, label: "Break Room", floor: "#141316" },
  server: { x: 1 * CELL, y: 12 * CELL, w: 4 * CELL, h: 5 * CELL, label: "Server Rack", floor: "#0e0e10" },
};

// ---- Desks: 3x1 cells each, seat cell just below the desk ----
export const DESKS = [
  { c: 3, r: 3 },
  { c: 8, r: 3 },
  { c: 13, r: 3 },
  { c: 3, r: 8 },
  { c: 8, r: 8 },
  { c: 13, r: 8 },
];
export const deskRect = (d) => ({ x: d.c * CELL, y: d.r * CELL, w: 3 * CELL, h: CELL });
export const deskSeat = (d) => ({ c: d.c + 1, r: d.r + 1 });

// ---- Meeting table + chairs around it (for chained team rounds) ----
export const MEETING_TABLE = { c: 22, r: 3, w: 5, h: 3 };
export const MEETING_SPOTS = [
  { c: 21, r: 4 },
  { c: 27, r: 4 },
  { c: 23, r: 2 },
  { c: 25, r: 2 },
  { c: 23, r: 6 },
  { c: 25, r: 6 },
];

// ---- Break room: couch (blocked) + idle spots in front of it ----
export const COUCH = { c: 21, r: 13, w: 4, h: 1 };
export const IDLE_SPOTS = [
  { c: 21, r: 15 },
  { c: 22, r: 15 },
  { c: 23, r: 15 },
  { c: 24, r: 15 },
  { c: 26, r: 14 },
  { c: 27, r: 14 },
  { c: 26, r: 15 },
  { c: 27, r: 15 },
];

// ---- Server rack + debugging spots beside it (agents in error state) ----
export const RACK = { c: 2, r: 13, w: 2, h: 3 };
export const ERROR_SPOTS = [
  { c: 4, r: 13 },
  { c: 4, r: 14 },
  { c: 4, r: 15 },
  { c: 1, r: 13 },
  { c: 1, r: 14 },
  { c: 1, r: 15 },
];

// ---- Blocked-cell grid for pathfinding ----
function buildBlocked() {
  const blocked = Array.from({ length: ROWS }, () => Array(COLS).fill(false));
  const blockRect = (c, r, w, h) => {
    for (let rr = r; rr < r + h; rr++)
      for (let cc = c; cc < c + w; cc++)
        if (rr >= 0 && rr < ROWS && cc >= 0 && cc < COLS) blocked[rr][cc] = true;
  };
  // outer walls
  blockRect(0, 0, COLS, 1);
  blockRect(0, ROWS - 1, COLS, 1);
  blockRect(0, 0, 1, ROWS);
  blockRect(COLS - 1, 0, 1, ROWS);
  // furniture
  for (const d of DESKS) blockRect(d.c, d.r, 3, 1);
  blockRect(MEETING_TABLE.c, MEETING_TABLE.r, MEETING_TABLE.w, MEETING_TABLE.h);
  blockRect(COUCH.c, COUCH.r, COUCH.w, COUCH.h);
  blockRect(RACK.c, RACK.r, RACK.w, RACK.h);
  return blocked;
}

export const BLOCKED = buildBlocked();
