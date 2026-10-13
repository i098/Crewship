// Route planner and camera controller for a self-driven walk-through. No browser here: capture.mjs feeds it the
// page's real pose each frame and sends what it returns as real input (mouse-look deltas and the forward key).
//
// Grid (one per scene: outdoors, each room), dumped from the site's own floor and collision functions on a fine
// step: { x0, z0, R, nx, nz, fy: [floor height | null], bl: [1 = blocked], soft?: [1 = walkable but the camera
// must keep off: tree crowns, rails, posts, lamps] }, row-major by z then x.

const FPS = 60;
export const DT = 1 / FPS;
const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

// ---- grid: walkable flag, clearance (metres to the nearest blocked or soft cell) -----------------------------
const BACK = [[-1, 0, 1], [0, -1, 1], [-1, -1, Math.SQRT2], [1, -1, Math.SQRT2]]; // neighbours already visited
const STEPS = [[-1, -1], [0, -1], [1, -1], [-1, 0], [1, 0], [-1, 1], [0, 1], [1, 1]];
export function grid(g) {
  const { x0, z0, R, nx, nz } = g, N = nx * nz;
  const fy = Float32Array.from(g.fy, (v) => (v === null ? NaN : v)), c = new Float32Array(N).fill(1e9);
  for (let k = 0; k < N; k++) if (g.fy[k] === null || g.bl[k] || g.soft?.[k]) c[k] = 0;
  const inside = (i, j) => i >= 0 && j >= 0 && i < nx && j < nz;
  const relax = (k, s) => { // s = 1 forward, -1 backward: the two passes of a chamfer distance
    const i = k % nx, j = (k - i) / nx;
    for (const [di, dj, w] of BACK) if (inside(i + s * di, j + s * dj)) c[k] = Math.min(c[k], c[k + s * (dj * nx + di)] + w);
  };
  for (let k = 0; k < N; k++) relax(k, 1);
  for (let k = N - 1; k >= 0; k--) relax(k, -1);
  for (let k = 0; k < N; k++) c[k] *= R;
  const idx = (x, z) => { const i = Math.floor((x - x0) / R), j = Math.floor((z - z0) / R); return inside(i, j) ? j * nx + i : -1; };
  return { ...g, fy, c, idx, inside, floor: (x, z) => fy[idx(x, z)] ?? NaN, clear: (x, z) => (idx(x, z) < 0 ? 0 : c[idx(x, z)]) };
}

// A* over 8-connected cells; cost rises as clearance drops under `pref` m, so routes keep to open space.
// A step of more than `step` m between cells is a ledge, not a path.
export function astar(g, a, b, { pref = 1.6, min = 0.05, K = 10, step = 0.45 } = {}) {
  const ia = g.idx(...a), ib = g.idx(...b), N = g.c.length;
  if (ia < 0 || ib < 0) throw new Error(`astar: off grid ${a} -> ${b}`);
  const s = { g, ib, pref, min, K, step, gs: new Float64Array(N).fill(Infinity), from: new Int32Array(N).fill(-1), done: new Uint8Array(N), open: [[0, ia]] };
  s.gs[ia] = 0;
  for (let k = ia; s.open.length && k !== ib; ) {
    k = popMin(s.open);
    if (k !== ib && !s.done[k]) { s.done[k] = 1; expand(s, k); }
  }
  if (ia !== ib && s.from[ib] < 0) throw new Error(`astar: no path ${a} -> ${b}`);
  return trace(g, s.from, ib, a, b);
}
// ponytail: linear scan for the cheapest open cell, a heap if grids grow past ~1e6 cells
function popMin(open) {
  let m = 0;
  for (let n = 1; n < open.length; n++) if (open[n][0] < open[m][0]) m = n;
  return open.splice(m, 1)[0][1];
}
function expand(s, k) {
  const { g, ib, gs, from, done, open } = s, { nx, c, fy } = g, i = k % nx, j = (k - i) / nx;
  const cost = (q) => 1 + s.K * Math.max(0, 1 - c[q] / s.pref) ** 2;
  for (const [di, dj] of STEPS) {
    const q = (j + dj) * nx + i + di;
    if (!g.inside(i + di, j + dj) || done[q] || (c[q] < s.min && q !== ib) || Math.abs(fy[q] - fy[k]) > s.step) continue;
    const ng = gs[k] + (Math.hypot(di, dj) * (cost(k) + cost(q))) / 2;
    if (ng < gs[q]) { gs[q] = ng; from[q] = k; open.push([ng + Math.hypot((q % nx) - (ib % nx), Math.floor(q / nx) - Math.floor(ib / nx)), q]); }
  }
}
function trace(g, from, ib, a, b) {
  const { nx, R, x0, z0 } = g, pts = [];
  for (let k = ib; k >= 0; k = from[k]) pts.unshift([x0 + ((k % nx) + 0.5) * R, z0 + (Math.floor(k / nx) + 0.5) * R]);
  pts[0] = a; pts[pts.length - 1] = b;
  return pts;
}
const segClear = (g, a, b) => {
  const n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / 0.05)); let m = Infinity;
  for (let t = 0; t <= n; t++) m = Math.min(m, g.clear(a[0] + ((b[0] - a[0]) * t) / n, a[1] + ((b[1] - a[1]) * t) / n));
  return m;
};
// Shortcut a cell path to the farthest point seen with no less clearance than the path had (capped at `want`).
function shortcut(g, pts, want) {
  const out = [pts[0]];
  for (let i = 0; i < pts.length - 1;) {
    let best = i + 1, local = Infinity;
    for (let j = i + 1; j < pts.length; j++) { local = Math.min(local, g.clear(...pts[j])); if (segClear(g, pts[i], pts[j]) >= Math.min(want, local) - 0.03) best = j; }
    out.push(pts[best]); i = best;
  }
  return out;
}
function chaikin(pts, n) {
  for (let r = 0; r < n; r++) {
    const o = [pts[0]];
    for (let i = 0; i < pts.length - 1; i++) {
      const [a, b] = [pts[i], pts[i + 1]];
      if (i > 0) o.push([a[0] * 0.75 + b[0] * 0.25, a[1] * 0.75 + b[1] * 0.25]);
      if (i < pts.length - 2) o.push([a[0] * 0.25 + b[0] * 0.75, a[1] * 0.25 + b[1] * 0.75]);
    }
    o.push(pts[pts.length - 1]); pts = o;
  }
  return pts;
}
// Points every 5 cm with arc length: { pts, s, len }.
export function densify(pts, step = 0.05) {
  const o = [pts[0]];
  for (let i = 1; i < pts.length; i++) {
    const [a, b] = [pts[i - 1], pts[i]], n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / step));
    for (let t = 1; t <= n; t++) o.push([a[0] + ((b[0] - a[0]) * t) / n, a[1] + ((b[1] - a[1]) * t) / n]);
  }
  const s = [0];
  for (let i = 1; i < o.length; i++) s.push(s[i - 1] + Math.hypot(o[i][0] - o[i - 1][0], o[i][1] - o[i - 1][1]));
  return { pts: o, s, len: s[s.length - 1] };
}
// Hand-placed via points joined by A*, each stretch shortcut on its own (the via points stay), then smoothed.
// `push` adds a straight run past the end: a door, hatch or ladder the site moves you through.
export function path(g, via, push) {
  const keep = [via[0]];
  for (let i = 1; i < via.length; i++) keep.push(...shortcut(g, astar(g, via[i - 1], via[i]), 0.9).slice(1));
  const smooth = chaikin(keep, 3);
  return densify(push ? [...smooth, push] : smooth);
}

// ---- controller ------------------------------------------------------------------------------------------
// A leg: { name, scene, path, end: "stop" | "cross", looks?: [{ at: [x, y, z] } | { yaw, pitch }, hold s],
//   narrow?: speed floor between close rails, lapse?: page-clock multiplier on open ground, crossPitch? }.
// The walk only goes forward, so the travel direction is the facing. Yaw and pitch are critically damped springs
// on slew-limited targets; walking, the yaw target is a look-ahead point on the path. Speed is the lowest of the
// limits from clearance ahead, curvature ahead, heading error and stopping distance.
// step(pose) takes { x, z, yaw, pitch, eye } and returns { yaw, pitch, f, clock }: the wanted view, the forward-key
// duty (0..1 of full key speed) and the page clock multiplier. Call crossed(pose) when the site moved you.
export class Ctl {
  constructor(legs, { keySpeed = 3.4 } = {}) {
    Object.assign(this, { legs, V: keySpeed, li: 0, phase: legs[0]?.path ? "pivot" : "look", Y: null, Yd: 0, P: 0, Pd: 0, Yt: 0, Pt: 0, v: 0, clock: 1, si: 0, look: 0, hold: 0, done: false });
  }
  get leg() { return this.legs[this.li]; }
  next() {
    Object.assign(this, { si: 0, look: 0, hold: 0 });
    if (++this.li >= this.legs.length) this.done = true;
    else this.phase = this.leg.path ? "pivot" : "look";
  }
  crossed(p) { Object.assign(this, { Y: p.yaw, Yt: p.yaw, P: p.pitch, Pt: p.pitch, Yd: 0, Pd: 0 }); this.next(); }
  step(p) {
    if (this.Y === null) Object.assign(this, { Y: p.yaw, Yt: p.yaw, P: p.pitch, Pt: p.pitch });
    const m = this.done ? { vt: 0, wY: 3.6, lapse: 1 } : this.phase === "look" ? this.lookStep(p) : this.walkStep(p);
    // speed eases up (at most 2 m/s²) and brakes down to the limit exactly (at most 2.4 m/s²)
    this.v = m.vt < this.v ? Math.max(m.vt, this.v - 2.4 * DT) : this.v + Math.min((m.vt - this.v) * 3 * DT, 2 * DT);
    this.clock += (m.lapse - this.clock) * (1 - Math.exp(-DT / 0.6));
    [this.Y, this.Yd] = spring(this.Y, this.Yd, this.Yt, m.wY);
    [this.P, this.Pd] = spring(this.P, this.Pd, this.Pt, 3.0);
    return { yaw: this.Y, pitch: clamp(this.P, -1.19, 1.19), f: clamp(this.v / (this.V * this.clock), 0, 1), clock: this.clock };
  }
  // Standing still: turn to the look's point or view, hold it, then the next look or leg.
  lookStep(p) {
    const leg = this.leg, L = leg.looks[this.look], d = L.at && Math.hypot(L.at[0] - p.x, L.at[2] - p.z);
    const yawT = L.at ? Math.atan2(L.at[0] - p.x, L.at[2] - p.z) : L.yaw, pitT = clamp(L.at ? Math.atan2(L.at[1] - p.eye, d) : L.pitch, -1.15, 1.15);
    this.Yt = slew(this.Yt, this.Yt + wrap(yawT - this.Yt), 2.4);
    this.Pt = slew(this.Pt, pitT, 1.4);
    if (this.hold > 0 || (Math.abs(wrap(yawT - this.Y)) < 0.04 && Math.abs(pitT - this.P) < 0.04)) this.hold += DT;
    if (this.hold >= (L.hold ?? 1)) { this.look++; this.hold = 0; if (this.look >= leg.looks.length) this.next(); }
    return { vt: 0, wY: 3.6, lapse: 1 };
  }
  // Walking: aim at a look-ahead point on the path; speed is the lowest of the limits.
  walkStep(p) {
    const leg = this.leg, { len } = leg.path, bi = this.nearest(p), s = leg.path.s[bi], remain = len - s;
    const [tx, tz] = this.lookAhead(bi, s, 0.9 + 0.3 * this.v);
    const yawT = Math.atan2(tx - p.x, tz - p.z), err = Math.abs(wrap(yawT - this.Y));
    const { turn, cl } = this.ahead(p, bi, s), crossing = leg.end === "cross" && remain < 2.2;
    if (this.phase === "pivot" && err < 0.25 && Math.abs(this.Yd) < 0.6) this.phase = "walk";
    const walking = this.phase === "walk", vt = walking ? this.limit(leg, { cl, turn, err, remain, crossing }) : 0;
    this.Yt = slew(this.Yt, this.Yt + wrap(yawT - this.Yt), walking ? 2.2 : 2.4);
    this.Pt = slew(this.Pt, crossing ? (leg.crossPitch ?? 0) : this.slopePitch(p), 1.4);
    if (walking) this.arrive(remain);
    return { vt, wY: walking ? 4.6 : 3.0, lapse: this.lapse(cl, remain) };
  }
  // A little down while walking, plus a little of the floor's slope ahead: stairs and ramps.
  slopePitch(p) {
    const g = this.leg.grid, slope = g.floor(p.x + Math.sin(this.Y), p.z + Math.cos(this.Y)) - g.floor(p.x, p.z) || 0;
    return -0.05 + clamp(0.3 * Math.atan(clamp(slope, -2, 2)), -0.28, 0.28);
  }
  // A stop leg ends standing still at its end, then runs its looks.
  arrive(remain) {
    const leg = this.leg;
    if (leg.end !== "stop" || remain >= 0.08 || this.v >= 0.1) return;
    this.v = 0; this.phase = "look";
    if (!leg.looks?.length) this.next();
  }
  // The page-clock multiplier: a time-lapse only at full pace, in the open, and well before the end.
  lapse(cl, remain) {
    const k = this.leg.lapse;
    return k ? 1 + (k - 1) * clamp((this.v - 2.6) / 0.8, 0, 1) * clamp((cl - 1.2) / 0.8, 0, 1) * clamp((remain - 6) / 6, 0, 1) : 1;
  }
  // Progress: the nearest path point in a window ahead of the last one.
  nearest(p) {
    const { pts } = this.leg.path;
    let bi = this.si, bd = Infinity;
    for (let i = this.si; i < Math.min(pts.length, this.si + 80); i++) { const d = Math.hypot(pts[i][0] - p.x, pts[i][1] - p.z); if (d < bd) { bd = d; bi = i; } }
    return (this.si = bi);
  }
  // The point Lk metres along the path, or past its end along the last direction.
  lookAhead(bi, s, Lk) {
    const { pts, s: S } = this.leg.path;
    let li = bi; while (li < pts.length - 1 && S[li] - s < Lk) li++;
    const [tx, tz] = pts[li];
    if (li < pts.length - 1) return [tx, tz];
    const a = pts[Math.max(0, li - 8)], d = Math.hypot(tx - a[0], tz - a[1]) || 1;
    return [tx + ((tx - a[0]) / d) * Lk, tz + ((tz - a[1]) / d) * Lk];
  }
  // Heading change over the next 2.2 m and the least clearance over the next 1.6 m.
  ahead(p, bi, s) {
    const { pts, s: S } = this.leg.path, g = this.leg.grid;
    const head = (i) => { const j = Math.min(pts.length - 1, i + 3); return Math.atan2(pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]); };
    let turn = 0, cl = g.clear(p.x, p.z);
    for (let i = bi, last = head(bi); i < pts.length - 4 && S[i] - s < 2.2; i += 4) { const n = head(i); turn += Math.abs(wrap(n - last)); last = n; if (S[i] - s < 1.6) cl = Math.min(cl, g.clear(...pts[i])); }
    return { turn, cl };
  }
  // The walking speed: clearance, curvature, heading error and stopping distance each cap it. A crossing keeps
  // walking pace, so the close-up of the door or rungs before the site moves you lasts a few frames.
  limit(leg, { cl, turn, err, remain, crossing }) {
    const V = this.V * this.clock, vClear = V * clamp((cl - 0.1) / 1.0, leg.narrow ? 0.62 : 0.3, 1), vTurn = V * clamp(1 - turn / 1.6, 0.25, 1);
    const vErr = V * clamp(1 - err / 0.5, 0, 1), vStop = leg.end === "stop" ? Math.sqrt(3 * Math.max(0, remain - 0.02)) : Infinity;
    return crossing ? Math.min(V, vErr, Math.max(3, Math.min(vClear, vTurn))) : Math.min(V, vClear, vTurn, vErr, vStop);
  }
}
const slew = (cur, to, max) => cur + clamp(to - cur, -max * DT, max * DT);
const spring = (x, v, to, w) => { v += (w * w * (to - x) - 2 * w * v) * DT; return [x + v * DT, v]; }; // critically damped
