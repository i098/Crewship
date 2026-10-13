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
export function grid(g) {
  const { x0, z0, R, nx, nz } = g, N = nx * nz, S2 = Math.SQRT2;
  const fy = Float32Array.from(g.fy, (v) => (v === null ? NaN : v)), c = new Float32Array(N).fill(1e9);
  const ok = (k) => g.fy[k] !== null && !g.bl[k];
  for (let k = 0; k < N; k++) if (!ok(k) || g.soft?.[k]) c[k] = 0;
  const pass = (j0, j1, dj, i0, i1, di) => { // two-pass chamfer distance
    for (let j = j0; j !== j1; j += dj) for (let i = i0; i !== i1; i += di) {
      const k = j * nx + i, pi = i - di, pj = j - dj, inI = pi >= 0 && pi < nx, inJ = pj >= 0 && pj < nz;
      let v = c[k];
      if (inI) v = Math.min(v, c[k - di] + 1);
      if (inJ) { v = Math.min(v, c[k - dj * nx] + 1); if (inI) v = Math.min(v, c[k - dj * nx - di] + S2); if (i + di >= 0 && i + di < nx) v = Math.min(v, c[k - dj * nx + di] + S2); }
      c[k] = v;
    }
  };
  pass(0, nz, 1, 0, nx, 1); pass(nz - 1, -1, -1, nx - 1, -1, -1);
  for (let k = 0; k < N; k++) c[k] *= R;
  const idx = (x, z) => { const i = Math.floor((x - x0) / R), j = Math.floor((z - z0) / R); return i < 0 || j < 0 || i >= nx || j >= nz ? -1 : j * nx + i; };
  return { ...g, fy, c, idx, floor: (x, z) => fy[idx(x, z)] ?? NaN, clear: (x, z) => (idx(x, z) < 0 ? 0 : c[idx(x, z)]) };
}

// A* over 8-connected cells; cost rises as clearance drops under `pref` m, so routes keep to open space.
// A step of more than `step` m between cells is a ledge, not a path.
export function astar(g, a, b, { pref = 1.6, min = 0.05, K = 10, step = 0.45 } = {}) {
  const { nx, nz, R, x0, z0, c, fy } = g, N = nx * nz, ia = g.idx(...a), ib = g.idx(...b);
  if (ia < 0 || ib < 0) throw new Error(`astar: off grid ${a} -> ${b}`);
  const cost = (k) => 1 + K * Math.max(0, 1 - c[k] / pref) ** 2, gs = new Float64Array(N).fill(Infinity);
  const from = new Int32Array(N).fill(-1), done = new Uint8Array(N), open = [[0, ia]];
  const bi = ib % nx, bj = Math.floor(ib / nx), h = (k) => Math.hypot((k % nx) - bi, Math.floor(k / nx) - bj);
  gs[ia] = 0;
  while (open.length) {
    let m = 0; for (let n = 1; n < open.length; n++) if (open[n][0] < open[m][0]) m = n; // ponytail: linear scan, a heap if grids grow past ~1e6 cells
    const [, k] = open.splice(m, 1)[0];
    if (done[k]) continue; done[k] = 1;
    if (k === ib) break;
    const i = k % nx, j = Math.floor(k / nx);
    for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) {
      const a2 = i + di, b2 = j + dj, q = b2 * nx + a2;
      if ((!di && !dj) || a2 < 0 || b2 < 0 || a2 >= nx || b2 >= nz || done[q]) continue;
      if ((c[q] < min && q !== ib) || Math.abs(fy[q] - fy[k]) > step) continue;
      const ng = gs[k] + Math.hypot(di, dj) * (cost(k) + cost(q)) / 2;
      if (ng < gs[q]) { gs[q] = ng; from[q] = k; open.push([ng + h(q), q]); }
    }
  }
  if (ia !== ib && from[ib] < 0) throw new Error(`astar: no path ${a} -> ${b}`);
  const pts = [];
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
    const leg = this.leg, slew = (cur, to, max) => cur + clamp(to - cur, -max * DT, max * DT);
    let vt = 0, wY = 3.6, slewY = 2.4, lapse = 1;
    if (this.done) { /* hold still */ } else if (this.phase === "look") {
      const L = leg.looks[this.look];
      const [yawT, pitT] = L.at ? [Math.atan2(L.at[0] - p.x, L.at[2] - p.z), Math.atan2(L.at[1] - p.eye, Math.hypot(L.at[0] - p.x, L.at[2] - p.z))] : [L.yaw, L.pitch];
      this.Yt = slew(this.Yt, this.Yt + wrap(yawT - this.Yt), slewY);
      this.Pt = slew(this.Pt, clamp(pitT, -1.15, 1.15), 1.4);
      if (this.hold > 0 || (Math.abs(wrap(yawT - this.Y)) < 0.04 && Math.abs(clamp(pitT, -1.15, 1.15) - this.P) < 0.04)) this.hold += DT;
      if (this.hold >= (L.hold ?? 1)) { this.look++; this.hold = 0; if (this.look >= leg.looks.length) this.next(); }
    } else {
      const { pts, s: S, len } = leg.path, g = leg.grid;
      let bi = this.si, bd = Infinity; // progress: nearest path point in a window ahead
      for (let i = this.si; i < Math.min(pts.length, this.si + 80); i++) { const d = Math.hypot(pts[i][0] - p.x, pts[i][1] - p.z); if (d < bd) { bd = d; bi = i; } }
      this.si = bi;
      const s = S[bi], remain = len - s, Lk = 0.9 + 0.3 * this.v;
      let li = bi; while (li < pts.length - 1 && S[li] - s < Lk) li++;
      let [tx, tz] = pts[li];
      if (li === pts.length - 1) { const a = pts[Math.max(0, li - 8)], d = Math.hypot(tx - a[0], tz - a[1]) || 1; tx += ((tx - a[0]) / d) * Lk; tz += ((tz - a[1]) / d) * Lk; }
      const yawT = Math.atan2(tx - p.x, tz - p.z), err = Math.abs(wrap(yawT - this.Y));
      let turn = 0, cl = g.clear(p.x, p.z);
      const head = (i) => { const j = Math.min(pts.length - 1, i + 3); return Math.atan2(pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]); };
      for (let i = bi, last = head(bi); i < pts.length - 4 && S[i] - s < 2.2; i += 4) { const n = head(i); turn += Math.abs(wrap(n - last)); last = n; if (S[i] - s < 1.6) cl = Math.min(cl, g.clear(...pts[i])); }
      const V = this.V * this.clock, crossing = leg.end === "cross" && remain < 2.2;
      const vClear = V * clamp((cl - 0.1) / 1.0, leg.narrow ? 0.62 : 0.3, 1), vTurn = V * clamp(1 - turn / 1.6, 0.25, 1);
      const vErr = V * clamp(1 - err / 0.5, 0, 1), vStop = leg.end === "stop" ? Math.sqrt(3 * Math.max(0, remain - 0.02)) : Infinity;
      if (this.phase === "pivot" && err < 0.25 && Math.abs(this.Yd) < 0.6) this.phase = "walk";
      // a crossing keeps walking pace: the close-up of the door or rungs before the site moves you lasts a few frames
      if (this.phase === "walk") { vt = crossing ? Math.min(V, vErr, Math.max(3, Math.min(vClear, vTurn))) : Math.min(V, vClear, vTurn, vErr, vStop); wY = 4.6; slewY = 2.2; }
      else wY = 3.0;
      this.Yt = slew(this.Yt, this.Yt + wrap(yawT - this.Yt), slewY);
      const hx = p.x + Math.sin(this.Y), hz = p.z + Math.cos(this.Y), slope = (g.floor(hx, hz) - g.floor(p.x, p.z)) || 0; // follow stairs and ramps, a little
      this.Pt = slew(this.Pt, crossing ? (leg.crossPitch ?? 0) : -0.05 + clamp(0.3 * Math.atan(clamp(slope, -2, 2)), -0.28, 0.28), 1.4);
      if (leg.end === "stop" && remain < 0.08 && this.v < 0.1 && this.phase === "walk") { this.v = 0; this.phase = "look"; if (!leg.looks?.length) this.next(); }
      if (leg.lapse) lapse = 1 + (leg.lapse - 1) * clamp((this.v - 2.6) / 0.8, 0, 1) * clamp((cl - 1.2) / 0.8, 0, 1) * clamp((remain - 6) / 6, 0, 1);
    }
    // speed eases up (at most 2 m/s²) and brakes down to the limit exactly (at most 2.4 m/s²)
    this.v = vt < this.v ? Math.max(vt, this.v - 2.4 * DT) : this.v + Math.min((vt - this.v) * 3 * DT, 2 * DT);
    this.clock += (lapse - this.clock) * (1 - Math.exp(-DT / 0.6));
    const spring = (x, v, to, w) => { v += (w * w * (to - x) - 2 * w * v) * DT; return [x + v * DT, v]; }; // critically damped
    [this.Y, this.Yd] = spring(this.Y, this.Yd, this.Yt, wY);
    [this.P, this.Pd] = spring(this.P, this.Pd, this.Pt, 3.0);
    return { yaw: this.Y, pitch: clamp(this.P, -1.19, 1.19), f: clamp(this.v / (this.V * this.clock), 0, 1), clock: this.clock };
  }
}
