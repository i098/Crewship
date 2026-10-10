// Crewship harbor: a first-person 3D scene ray cast into a grid of text.
// Plain JavaScript, no dependencies. The world is a list of convex solids (sets of planes)
// plus the water plane; the ship's solids live in a frame that bobs and rolls at the dock.
const stage = document.getElementById("stage");
const canvas = document.getElementById("scene");
const ctx = canvas.getContext("2d");
const card = document.getElementById("card");
// With JavaScript the scene fills the screen and the plain page stays for screen readers only.
stage.hidden = false;
stage.focus({ preventScroll: true });
const pad = document.getElementById("pad");
const knob = pad.firstElementChild;
const reduced = matchMedia("(prefers-reduced-motion: reduce)");
const touchFirst = matchMedia("(pointer: coarse)");
// The intro keeps the camera, grid, and canvas at their final size.
let introStart = null, introProgress = reduced.matches ? 1 : 0;
stage.classList.toggle("loading", introProgress < 1);
function finishIntro() {
  introProgress = 1;
  stage.classList.remove("loading");
  dirty = true;
  for (const event of ["keydown", "pointerdown", "touchstart", "click", "wheel"]) removeEventListener(event, finishIntro, true);
}
for (const event of ["keydown", "pointerdown", "touchstart", "click", "wheel"]) addEventListener(event, finishIntro, { capture: true, passive: true });

// The features come from the plain list, so the scene and the list never disagree.
const spots = {};
for (const li of document.querySelectorAll("#manifest li[data-spot]")) {
  const a = li.querySelector("a");
  spots[li.dataset.spot] = { title: a.textContent, href: a.href, body: li.querySelector("p") };
}

// ---- World -------------------------------------------------------------------------------
const SX = -2.4; // ship centre line (x) and roll axis
const DECK = 2; // deck height in the ship frame
// The scene's one wind: the unit direction it blows toward on the ground plan (x, z), and its strength, where 1 fills
// the sails as drawn. The sails belly before it, and the flag and pennants stream along it.
const WIND = { x: Math.sin(-1.17), z: Math.cos(-1.17), strength: 1 };
const world = [];
const ship = [];
const room = [];
const cabinRoom = [];
let interior = null; // the room you are inside (HOUSE or CABIN), or null outdoors

function solid(list, planes, bb, mat, o) {
  const P = [];
  for (const [nx, ny, nz, px, py, pz] of planes) {
    const l = Math.hypot(nx, ny, nz);
    P.push(nx / l, ny / l, nz / l, (nx * px + ny * py + nz * pz) / l);
  }
  const s = { id: world.length + ship.length + room.length + cabinRoom.length + 1, P: new Float64Array(P), bb, mat, spot: null, solid: true, tex: null, ...o };
  list.push(s);
  return s;
}
function box(list, x0, y0, z0, x1, y1, z1, mat, o) {
  return solid(list, [[1, 0, 0, x1, 0, 0], [-1, 0, 0, x0, 0, 0], [0, 1, 0, 0, y1, 0],
    [0, -1, 0, 0, y0, 0], [0, 0, 1, 0, 0, z1], [0, 0, -1, 0, 0, z0]], [x0, y0, z0, x1, y1, z1], mat, o);
}
// A round column around a vertical axis, tapered from r0 at y0 to r1 at y1: masts, barrels, trunks, the lighthouse.
// Rays hit the true cone (smooth normals); the eight planes only serve the walking test and the culling box.
function column(list, cx, cz, r0, r1, y0, y1, mat, o) {
  const pl = [[0, 1, 0, 0, y1, 0], [0, -1, 0, 0, y0, 0]];
  const slope = (r0 - r1) / (y1 - y0);
  for (let i = 0; i < 8; i++) {
    const a = (i + 0.5) * Math.PI / 4, c = Math.cos(a), s = Math.sin(a);
    pl.push([c, slope, s, cx + c * r0, y0, cz + s * r0]);
  }
  const r = Math.max(r0, r1) * 1.09, b = (r1 - r0) / (y1 - y0);
  return solid(list, pl, [cx - r, y0, cz - r, cx + r, y1, cz + r], mat, { cone: [cx, cz, r0 - b * y0, b, y0, y1, r0, r1], ...o });
}
// An ellipsoid: rocks, pebbles and leafy canopies. Rays hit the true surface; the box planes serve walking and culling.
function blob(list, cx, cy, cz, rx, ry, rz, mat, o) {
  const s = box(list, cx - rx, cy - ry, cz - rz, cx + rx, cy + ry, cz + rz, mat, o);
  s.blob = [cx, cy, cz, rx, ry, rz];
  return s;
}
// Eight-sided disc facing along z (the helm wheel).
function disc(list, cx, cy, z0, z1, r, mat, o) {
  const pl = [[0, 0, 1, 0, 0, z1], [0, 0, -1, 0, 0, z0]];
  for (let i = 0; i < 8; i++) {
    const a = (i + 0.5) * Math.PI / 4, c = Math.cos(a), s = Math.sin(a);
    pl.push([c, s, 0, cx + c * r, cy + s * r, 0]);
  }
  return solid(list, pl, [cx - r * 1.09, cy - r * 1.09, z0, cx + r * 1.09, cy + r * 1.09, z1], mat, o);
}

// Rope or spar from a to b: a box of half-width r aligned with the segment.
function beam(list, a, b, mat, o = {}, r = 0.03) {
  const unit = (p) => { const l = Math.hypot(...p); return p.map((c) => c / l); };
  const cross = (p, q) => [p[1] * q[2] - p[2] * q[1], p[2] * q[0] - p[0] * q[2], p[0] * q[1] - p[1] * q[0]];
  const u = unit(b.map((c, i) => c - a[i]));
  const v = unit(cross(u, Math.abs(u[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0])), w = cross(u, v);
  const side = (n, s) => [...n.map((c) => c * s), ...a.map((c, i) => c + n[i] * s * r)];
  const planes = [[...u.map((c) => -c), ...a], [...u, ...b], side(v, 1), side(v, -1), side(w, 1), side(w, -1)];
  const bb = [...a.map((c, i) => Math.min(c, b[i]) - r), ...a.map((c, i) => Math.max(c, b[i]) + r)];
  return solid(list, planes, bb, mat, { solid: false, thin: true, ...o });
}
// Cloth hangs from `at`: u runs along the level unit (cu, su), v runs down, and the cloth stands out clothDepth along
// the level normal (-su, cu). size is [u0, u1, v1, w0, w1]: rays search the box that holds every shape the cloth takes,
// and clothInside trims that to the cloth's outline. shape sets half, the cloth's half width (a flag's length); the
// wind's belly and its resting value, base; how far the foot sags (sag, of v1) and the leeches bow out (bow, of half);
// or a flag's ripple and its phase. Every cloth has the same fields, so the ray tests stay monomorphic.
function cloth(list, at, cu, su, [u0, u1, v1, w0, w1], shape, mat, o) {
  const xs = [], zs = [];
  for (const u of [u0, u1]) for (const w of [w0, w1]) { xs.push(at[0] + u * cu - w * su); zs.push(at[2] + u * su + w * cu); }
  const s = box(list, Math.min(...xs), at[1] - v1, Math.min(...zs), Math.max(...xs), at[1], Math.max(...zs), mat, { solid: false, thin: true, ...o });
  s.cloth = { at, cu, su, u0, u1, v1, w0, w1, half: shape.half, ku: 1 / shape.half, kv: 1 / v1, base: 0, belly: 0, sag: 0, bow: 0,
    ripple: 0, phase: 0, ...shape };
  return s.cloth;
}
// How far cloth k stands out at (u, v): a polynomial belly, deepest low across the middle and shallower toward the
// corners, or a ripple that grows toward a flag's fly. Rays evaluate it often, so the belly uses products, not
// quotients or Math.sin.
function clothDepth(k, u, v) {
  const a = u * k.ku, b = v * k.kv;
  if (k.ripple) return k.ripple * a * Math.sin(u * 2.4 + v * 0.5 - k.phase);
  return k.belly * (Math.max(0, 1 - a * a) * b * (2.6 - 1.8 * b) + 0.3 * b * b);
}
// The change of clothDepth along u and along v, in SLOPE.
const SLOPE = new Float64Array(2);
function clothSlope(k, u, v) {
  const a = u * k.ku, b = v * k.kv, across = Math.max(0, 1 - a * a);
  if (k.ripple) {
    const p = u * 2.4 + v * 0.5 - k.phase, c = Math.cos(p);
    SLOPE[0] = k.ripple * k.ku * (Math.sin(p) + 2.4 * u * c); SLOPE[1] = k.ripple * k.ku * 0.5 * u * c;
    return;
  }
  SLOPE[0] = across > 0 ? -2 * a * b * (2.6 - 1.8 * b) * k.belly * k.ku : 0;
  SLOPE[1] = (across * (2.6 - 3.6 * b) + 0.6 * b) * k.belly * k.kv;
}
// How far down cloth k reaches at u: a sail's foot sags in an arc between its corners.
function clothFoot(k, u) {
  const a = u * k.ku;
  return k.v1 * (1 - k.sag * a * a);
}
// Is (u, v) on cloth k? Above the foot, and within the leeches, which bow out between the head and the corners; a
// flag's fly edge waves instead.
function clothInside(k, u, v) {
  const a = u * k.ku, c = Math.min(1, v * k.kv / (1 - k.sag));
  if (k.ripple) return a <= 0.9 + 0.1 * Math.sin(v * 5 - k.phase);
  return v <= clothFoot(k, u) && Math.abs(a) <= 1 + k.bow * 4 * c * (1 - c);
}
// The point of cloth k at (u, v), written into p.
function clothPoint(k, u, v, p = [0, 0, 0]) {
  const w = clothDepth(k, u, v);
  p[0] = k.at[0] + u * k.cu - w * k.su; p[1] = k.at[1] - v; p[2] = k.at[2] + u * k.su + w * k.cu;
  return p;
}
// A 3x5 pixel font for the painted signs.
const FONT = { A: "010101111101101", B: "110101110101110", C: "011100100100011", D: "110101101101110", E: "111100110100111",
  H: "101101111101101", I: "111010010010111", O: "010101101101010", P: "110101110100100",
  R: "110101110101101", S: "011100010001110", W: "101101101111101" };
// Paints `text` inside the rectangle [u0,u1] x [v0,v1] of a face, u running left to right as seen from the front.
function painted(text, u0, u1, v0, v1) {
  const cols = text.length * 4 - 1;
  const px = Math.min((u1 - u0) / cols, (v1 - v0) / 5);
  const left = (u0 + u1 - cols * px) / 2, top = (v0 + v1 + 5 * px) / 2;
  return (x, y) => {
    const c = Math.floor((x - left) / px), r = Math.floor((top - y) / px);
    if (c < 0 || r < 0 || c >= cols || r > 4 || c % 4 === 3) return false;
    return FONT[text[(c / 4) | 0]][r * 3 + (c % 4)] === "1";
  };
}
const hash = (a, b) => { const h = Math.sin(a * 127.1 + b * 311.7) * 43758.5453; return h - Math.floor(h); };

// Harbor: quay, breakwater, the dock and what stands on them.
// The road network: junctions and the links between them. It is drawn on the island and is the route
// the mini map walks you along (deck, gangway, dock, avenue, plaza, breakwater path).
const NODES = [[-0.3, -6], [-0.3, -1.2], [0.3, 5.5], [1.9, -1.2], [4.2, -1.2], [5, 13.5], [5, 19.6], [7.1, 24.6], [-5, 19.6],
  [-16, 19.6], [-28, 19.6], [-30, 10], [-30, -14], [14, 19.6], [20, 19.6], [7.1, 21.7]];
const LINKS = [[0, 1], [1, 2], [1, 3], [3, 4], [4, 5], [5, 6], [6, 15], [6, 8], [8, 9], [9, 10], [10, 11], [11, 12], [6, 13], [13, 14], [15, 7]];
// Island ways (the links past the dock): concrete from the dock head to the plaza and along the centre of
// the avenue, narrow dirt trails beyond. [ax, az, dx, dz, length², concrete, length]
const CONCRETE = new Set(["5,6", "6,15", "15,7", "6,8", "6,13"]);
const ROADS = LINKS.slice(5).map(([a, b]) => {
  const [ax, az] = NODES[a], dx = NODES[b][0] - ax, dz = NODES[b][1] - az;
  const l2 = dx * dx + dz * dz;
  return [ax, az, dx, dz, l2, CONCRETE.has(`${a},${b}`), Math.sqrt(l2)];
});
// Distance from (x, z) to the nearest way, how far along it you are, and whether it is concrete.
function roadAt(x, z) {
  let best = Infinity, along = 0, concrete = false;
  for (const [ax, az, dx, dz, l2, c, length] of ROADS) {
    const t = Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / l2)), ex = x - ax - t * dx, ez = z - az - t * dz;
    const d = ex * ex + ez * ez;
    if (d < best) { best = d; along = t * length; concrete = c; }
  }
  return [Math.sqrt(best), along, concrete];
}
const trailHalfWidth = (along) => 0.5 + 0.12 * Math.sin(along * 1.7) + 0.08 * hash(Math.floor(along * 3), 7);
// Staggered paving joints and individually divided stones around the round plaza.
function plazaCurb(x, z) {
  return (Math.atan2(z - 24.6, x - 5) + Math.PI) * 12 % 1 < 0.12 ? "t:" : "s=";
}
function plazaStone(x, z) {
  const row = Math.floor((z + 99) / 0.9), u = x + 99 + (row % 2) * 0.6;
  if (u % 1.2 < 0.09) return "s|";
  if ((z + 99) % 0.9 < 0.075) return "s-";
  return hash(Math.floor(u / 1.2), row) < 0.3 ? "t," : "t.";
}
function plazaPaving(x, z, radius) {
  return radius > 2.96 ? plazaCurb(x, z) : plazaStone(x, z);
}
// Island ground as material and glyph: a 3 m concrete road with kerbs and joints every 3 m, a tiled plaza,
// a 1 m dirt trail with uneven edges, ruts and footprints, and grass with a few flowers elsewhere.
function ground(x, y, z, nx, ny) {
  if (ny < 0.5) return null;
  const [d, along, concrete] = roadAt(x, z), plaza = Math.hypot(x - 5, z - 24.6);
  if (plaza < 3.2) return plazaPaving(x, z, plaza);
  if (concrete && d < 1.5) return d > 1.38 ? along % 0.8 < 0.08 ? "t:" : "s_" : along % 3 < 0.12 ? "t:" : "t.";
  if (!concrete && d < trailHalfWidth(along)) {
    if (Math.abs(d - 0.22) < 0.06) return "o:";
    return hash(Math.floor(along * 2.5), Math.floor(d * 6)) < 0.18 ? "o," : "o.";
  }
  const cx = Math.floor(x * 2), cz = Math.floor(z * 2), h = hash(cx, cz);
  if (h < 0.025 && Math.hypot(x * 2 - cx - 0.5, z * 2 - cz - 0.5) < 0.18) return ["r*", "b*", "s*"][Math.floor(h * 120)];
  if (h >= 0.025 && h < 0.13) {
    const dx = x * 2 - cx - 0.3 - h * 3, dz = z * 2 - cz - 0.3 - hash(cz, cx) * 0.4;
    if (dx * dx * 1.6 + dz * dz < 0.025 + h * 0.2) return h < 0.08 ? "t_" : "G'";
  }
  // Grass in three greens mixed blade by blade; shadeSolid draws it as blades swaying in the wind.
  const v = hash(Math.floor(x * 5), Math.floor(z * 5) + 50);
  return (v < 0.3 ? "M" : v < 0.65 ? "G" : "g") + "'";
}
// The island is one height field: a plateau at 1.2 m whose edges slope down through sand beaches into the sea
// all the way round, with a wobbly coastline, and a steep stone harbour wall only where the dock needs deep water.
const smooth = (t) => (t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t));
// Signed distance from (x, z) to a rounded rectangle; Math.sqrt, not Math.hypot, as it runs many times per ray.
function roundedBox(x, z, cx, cz, hx, hz, r) {
  const qx = Math.abs(x - cx) - hx + r, qz = Math.abs(z - cz) - hz + r, ox = Math.max(qx, 0), oz = Math.max(qz, 0);
  return Math.sqrt(ox * ox + oz * oz) + Math.min(Math.max(qx, qz), 0) - r;
}
function landDistance(x, z) {
  return Math.min(roundedBox(x, z, -8, 31, 53, 23, 12), roundedBox(x, z, -36, -11, 16, 31, 9)) + 0.6 * Math.sin(x * 0.19 + z * 0.07) + 0.45 * Math.sin(z * 0.23 - x * 0.13);
}
function terrainY(x, z) {
  const h = 1.2 - 2.8 * smooth((landDistance(x, z) + 6) / 7.5);
  const wall = smooth((x + 8) / 1.5) * smooth((9 - x) / 1.5), wallY = 1.2 - (14 - z) * 1.6;
  return Math.max(-1.6, wall > 0 && wallY < h ? h + (wallY - h) * wall : h);
}
// The ray march, the shoreline and the water depth read the island from a 0.25 m height grid, bilinear, filled a
// row at a time on first use. Above the waves it is within 6 cm of terrainY, which slope normals still use.
const HG = 4, HX0 = -70, HZ0 = -50, HW = 130 * HG + 1, HH = 110 * HG + 1, HEIGHTS = new Float32Array(HW * HH), HREADY = new Uint8Array(HH);
function heightRow(k) {
  for (let i = 0; i < HW; i++) HEIGHTS[k * HW + i] = terrainY(HX0 + i / HG, HZ0 + k / HG);
  HREADY[k] = 1;
}
function marchY(x, z) {
  const u = (x - HX0) * HG, w = (z - HZ0) * HG, i = Math.floor(u), k = Math.floor(w);
  if (i < 0 || k < 0 || i >= HW - 1 || k >= HH - 1) return -1.6;
  if (!HREADY[k]) heightRow(k);
  if (!HREADY[k + 1]) heightRow(k + 1);
  const fu = u - i, fw = w - k, p = k * HW + i;
  return (HEIGHTS[p] * (1 - fu) + HEIGHTS[p + 1] * fu) * (1 - fw) + (HEIGHTS[p + HW] * (1 - fu) + HEIGHTS[p + HW + 1] * fu) * fw;
}
// The stone harbour wall, only where the dock needs deep water.
const harbourWall = (x, y, z) => x > -8.5 && x < 9.5 && z < 14.3 && y < 1.15;
// Ground texture by where you are: the stone harbour wall, sand on the beaches, ground on the plateau.
function landTex(x, y, z, nx, ny) {
  if (harbourWall(x, y, z)) return "t:";
  return y < 1.12 ? sand(x, y, z, nx, ny) : ground(x, y, z, nx, ny);
}
const TERRAIN = { id: 4000, P: new Float64Array(0), bb: [-70, -1.6, -50, 60, 1.2, 60], mat: "g", spot: null, solid: false, tex: landTex };
// Sand: light and dotted when dry, darker and wet by the waterline, where the wash comes and goes, with a few shells.
function wetSand(x, y, z) {
  const wash = 0.12 + 0.08 * Math.sin(T * 0.9 + x * 0.3 + z * 0.2);
  if (Math.abs(y - wash) < 0.09) return "k~";
  return y < wash + 0.25 ? "n:" : null;
}
function sand(x, y, z, nx, ny) {
  if (ny < 0.5) return null;
  const wet = wetSand(x, y, z);
  if (wet) return wet;
  if (hash(Math.floor(x * 5), Math.floor(z * 5)) < 0.02) return "s*"; // a shell
  return hash(Math.floor(x * 6), Math.floor(z * 6)) < 0.15 ? "y:" : hash(Math.floor(x * 3), Math.floor(z * 3)) < 0.5 ? "y." : "y,";
}
// Rounded, weathered rocks with pebbles at their feet, and driftwood, on the sand.
const beachY = terrainY;
for (const [x, z, r] of [[-14, 10.1, 0.8], [-9, 10.8, 0.5], [-18, 10.4, 0.6], [15, 11, 0.9], [19, 10.4, 0.5], [26, 10.1, 0.7], [-23.6, -4, 0.8], [-23, -20, 0.6], [-24.4, 5, 0.5]]) {
  const y = beachY(x, z);
  blob(world, x, y + r * 0.25, z, r, r * 0.6, r * 0.85, "t", { dim: 2.2, tex: (x, y) => (hash(Math.floor(x * 6), Math.floor(y * 6)) < 0.25 ? "-" : null) });
  for (let k = 0; k < 3; k++) {
    const a = k * 2.1 + r, px = x + Math.cos(a) * (r + 0.4), pz = z + Math.sin(a) * (r + 0.3), pr = 0.08 + 0.06 * hash(k, r);
    blob(world, px, beachY(px, pz) + pr * 0.3, pz, pr, pr * 0.6, pr, "t", { solid: false });
  }
}
for (const [a, b] of [[[-11, 12.6], [-8.8, 12.2]], [[17, 12.9], [19.6, 13.3]], [[-24.7, -12], [-24.1, -9.8]]]) {
  beam(world, [a[0], beachY(...a) + 0.1, a[1]], [b[0], beachY(...b) + 0.1, b[1]], "o", {}, 0.11);
}
const seam = (u) => ((u + 99) % 0.45 < 0.07 ? "-" : null);
box(world, 3, 0.85, -16, 7, 1.2, 14, "t", { solid: false, tex: (x, y, z, nx, ny) => (ny > 0.5 ? seam(z) : null) });
for (const z of [-15.6, -11, -6, 3, 8, 13.4]) {
  box(world, 3.05, -1, z, 3.35, 1.55, z + 0.3, "o");
  box(world, 6.65, -1, z, 6.95, 1.55, z + 0.3, "o");
}
column(world, 3.55, -8, 0.18, 0.15, 1.2, 1.65, "t");
column(world, 3.55, 5, 0.18, 0.15, 1.2, 1.65, "t");
for (const z of [-4, 9]) {
  box(world, 6.4, 1.2, z, 6.56, 4.2, z + 0.16, "t");
  box(world, 6.24, 4.2, z - 0.14, 6.72, 4.65, z + 0.3, "l");
}
const ribs = (x, y, z, nx, ny, nz) => (Math.sin((Math.abs(nz) > 0.5 ? x : z) * 10) > 0.45 ? "-" : null);
box(world, 9, 1.2, 16, 15, 3.8, 18.5, "r", { spot: "containers", tex: ribs });
box(world, 9.4, 3.8, 16.2, 15.4, 6.4, 18.7, "b", { spot: "containers", tex: ribs });
box(world, 16.2, 1.2, 15.6, 22.2, 3.8, 18.1, "b", { spot: "containers", tex: ribs });
const officeText = painted("HARBOR", -7.6, -2.4, 4.15, 5.05);
const officeFrontWindows = [[-8.2, -6.6], [-3.4, -1.8]];
const officeSideWindows = [[22.5, 24], [25, 26.5]];
function officeWindow(u, y, spans) {
  if (y < 2.28 || y > 3.72) return null;
  for (const [a, b] of spans) {
    if (u < a - 0.12 || u > b + 0.12) continue;
    // The frame and crossbars stay dark; only the four inset panes emit light.
    if (u < a || u > b || y < 2.4 || y > 3.6 || Math.abs(u - (a + b) / 2) < 0.055 || Math.abs(y - 3) < 0.055) return "o";
    return "l";
  }
  return null;
}
function officeWall(x, y, z, nx, ny, nz) {
  if (ny > 0.5) return null;
  const front = nz < -0.5, u = Math.abs(nz) > 0.5 ? x : z;
  if (front && officeText(x, y)) return "r";
  if (front && x > -5.6 && x < -4.4 && y < 3.6) {
    if (Math.hypot(x + 4.6, y - 2.35) < 0.07) return "t";
    return Math.abs(x + 5) > 0.46 || Math.abs(y - 2.35) < 0.08 || y < 1.55 || y > 3.35 ? "o" : "o:";
  }
  const window = officeWindow(u, y, Math.abs(nz) > 0.5 ? officeFrontWindows : officeSideWindows);
  if (window) return window;
  return (y - 1.2) % 0.32 < 0.025 ? "-" : null;
}
box(world, -9, 1.2, 21, -1, 5.4, 28, "s", { spot: "office", tex: officeWall });
solid(world, [[0, -1, 0, 0, 5.4, 0], [0, 0, 1, 0, 0, 28.4], [0, 0, -1, 0, 0, 20.6],
  [-2, 4.4, 0, -9.4, 5.4, 0], [2, 4.4, 0, -0.6, 5.4, 0]], [-9.4, 5.4, 20.6, -0.6, 7.4, 28.4], "r", { spot: "office",
  tex: (x, y, z, nx, ny, nz) => {
    if (Math.abs(nz) > 0.5) return (y - 5.4) % 0.25 < 0.035 ? "o:" : "o";
    const row = Math.floor((y - 5.4) / 0.22);
    return (y - 5.4) % 0.22 < 0.035 || (z + 99 + (row % 2) * 0.25) % 0.5 < 0.035 ? "-" : null;
  } });
// Raised details do not change the walking bounds, map footprint or feature anchor.
const officeDetail = { spot: "office", anchor: false, solid: false, thin: true };
for (const x of [-9, -1]) {
  for (const z of [21, 28]) beam(world, [x, 1.25, z], [x, 5.4, z], "o", officeDetail, 0.12);
  for (const y of [1.4, 3.95, 5.3]) beam(world, [x, y, 21], [x, y, 28], "o", officeDetail, 0.09);
  beam(world, [x < -5 ? -9.4 : -0.6, 5.4, 20.6], [x < -5 ? -9.4 : -0.6, 5.4, 28.4], "s", officeDetail, 0.1);
  for (const [a, b] of officeSideWindows) box(world, x - 0.2, 2.23, a - 0.18, x + 0.2, 2.4, b + 0.18, "o", officeDetail);
}
for (const z of [21, 28]) {
  for (const y of [1.4, 3.95, 5.3]) beam(world, [-9, y, z], [-1, y, z], "o", officeDetail, 0.09);
  for (const [a, b] of officeFrontWindows) box(world, a - 0.18, 2.23, z - 0.2, b + 0.18, 2.4, z + 0.2, "o", officeDetail);
}
for (const z of [20.6, 28.4]) {
  beam(world, [-9.4, 5.4, z], [-5, 7.4, z], "s", officeDetail, 0.1);
  beam(world, [-5, 7.4, z], [-0.6, 5.4, z], "s", officeDetail, 0.1);
}
beam(world, [-5, 7.4, 20.6], [-5, 7.4, 28.4], "o", officeDetail, 0.1);
for (const x of [-5.72, -4.28]) beam(world, [x, 1.4, 20.92], [x, 3.72, 20.92], "o", officeDetail, 0.1);
beam(world, [-5.82, 3.72, 20.92], [-4.18, 3.72, 20.92], "o", officeDetail, 0.1);
box(world, -5.85, 1.2, 20.55, -4.15, 1.4, 21.05, "t", officeDetail);
box(world, -2.6, 6, 24, -2.45, 10.5, 24.15, "t", { spot: "antenna" });
box(world, -3.3, 9.4, 24, -1.75, 9.52, 24.15, "t", { spot: "antenna" });
box(world, -3, 8.5, 24, -2.05, 8.62, 24.15, "t", { spot: "antenna" });
const antennaLamp = box(world, -2.68, 10.5, 23.93, -2.37, 10.8, 24.22, "l", { spot: "antenna" });
// Lighthouse on the breakwater, striped, with a lamp that turns.
column(world, -36, -24, 1.9, 1.15, 1, 13, "s", { spot: "lighthouse",
  tex: (x, y) => (Math.floor((y - 1) / 2.4) % 2 ? "r" : null) });
const beacon = column(world, -36, -24, 1.2, 1.2, 13, 14.6, "l", { spot: "lighthouse" });
column(world, -36, -24, 1.5, 0.2, 14.6, 16, "r", { spot: "lighthouse" });
// A town on the far shore.
for (let i = 0; i < 16; i++) {
  const x = -95 + i * 12.5, w = 6 + hash(i, 1) * 5, h = 4 + hash(i, 2) * 14, z = 95 + hash(i, 3) * 12;
  box(world, x, 0, z, x + w, h, z + 8, "f", { solid: false, tex: (x, y, z, nx, ny, nz) =>
    (nz < -0.5 && (y % 2.2) > 1 && (x % 2) > 0.9 && hash(Math.floor(x / 2), Math.floor(y / 2.2)) < 0.3 ? "l" : null) });
}

// Harbor detail, kept to the edges so the walk stays clear: cargo, rope, boats, rocks, palms, lamps.
const crateSlats = (x, y, z, nx, ny, nz) => (Math.abs(nx) + Math.abs(nz) > 0.5 && ((x + z + y) * 4 + 99) % 1 < 0.15 ? "-" : null);
for (const [x, z, h] of [[6.2, -9.5, 0.8], [6.2, -8.6, 0.8], [6.25, -9.1, 1.6], [12, 21.2, 0.9], [13, 21.3, 0.9], [12.5, 21.2, 1.8]]) {
  box(world, x, h - 0.8 + 1.2, z, x + 0.75, h + 1.2, z + 0.75, "o", { tex: crateSlats });
}
for (const [x, z] of [[6.5, 0.6], [6.5, 1.3], [5.9, 0.9], [6.5, 10.8], [15.5, 21.4], [16.2, 21.3]]) {
  column(world, x, z, 0.3, 0.27, 1.2, 2.1, "o", { spot: "barrels", tex: (x, y) => (Math.abs(y - 1.42) < 0.06 || Math.abs(y - 1.88) < 0.06 ? "-" : null) });
}
for (const [x, z] of [[3.6, -4.6], [3.6, 6.4], [6.4, -13]]) column(world, x, z, 0.38, 0.38, 1.2, 1.36, "s", { solid: false });
// Small boats ride the waves: each frame their planes are lifted and tilted to the sea surface under them.
const boats = [];
function boat(cx, z0, w, len, mat, spot = null) {
  const z1 = z0 + len, zb = z1 - w, top = 0.45;
  const s = solid(world, [[0, 1, 0, 0, top, 0], [0, -1, 0, 0, -0.3, 0], [0, 0, -1, 0, 0, z0], [1, -0.4, 0, cx + w / 2, top, 0],
    [-1, -0.4, 0, cx - w / 2, top, 0], [w, 0, w / 2, cx + w / 2, 0, zb], [-w, 0, w / 2, cx - w / 2, 0, zb]],
  [cx - w / 2 - 0.5, -0.8, z0 - 0.3, cx + w / 2 + 0.5, top + 0.5, z1 + 0.3], mat, { spot, solid: false, tex: (x, y) => (y - s.dy > 0.25 && y - s.dy < 0.35 ? "s" : null) });
  Object.assign(s, { base: Float64Array.from(s.P), c: [cx, 0, (z0 + z1) / 2], dy: 0 });
  boats.push(s);
}
function floatBoats() {
  for (const s of boats) {
    const [cx, , cz] = s.c;
    s.dy = seaHeight(cx, cz) * 0.9;
    seaNormal(cx, cz);
    const az = -Math.atan2(seaN[0], seaN[1]) * 0.8, ax = Math.atan2(seaN[2], seaN[1]) * 0.8;
    const cz1 = Math.cos(az), sz1 = Math.sin(az), cx1 = Math.cos(ax), sx1 = Math.sin(ax);
    for (let i = 0; i < s.P.length; i += 4) {
      const n0 = s.base[i], n1 = s.base[i + 1], n2 = s.base[i + 2], off = s.base[i + 3] - (n0 * cx + n2 * cz);
      // Tilt the normal: about z (roll), then about x (pitch).
      const r0 = cz1 * n0 - sz1 * n1, r1 = sz1 * n0 + cz1 * n1, q1 = cx1 * r1 - sx1 * n2, q2 = sx1 * r1 + cx1 * n2;
      s.P[i] = r0; s.P[i + 1] = q1; s.P[i + 2] = q2; s.P[i + 3] = off + r0 * cx + q1 * s.dy + q2 * cz;
    }
  }
}
boat(-8, 3.6, 1.3, 3.6, "r", "lifeboat");
boat(-11.5, 3, 1.2, 3.2, "b", "tender");
boat(9.5, 3, 1.4, 4, "o");
for (let z = -32; z < 12; z += 5.5) column(world, -26.6, z + hash(z, 4) * 2, 0.9 + hash(z, 5) * 0.5, 0.35, 0.2, 1.3 + hash(z, 6) * 0.8, "t");
// Palms: curved-looking trunks (two leaning segments) with drooping fronds, on the quay and along the beaches.
for (const [x, z, y0] of [[21, 24, 1.2], [-16, 23.5, 1.2], [-30, 2, 1], [-20, 12.6, beachY(-20, 12.6)], [23, 12.4, beachY(23, 12.4)], [-24, -14, beachY(-24, -14)]]) {
  const lean = 0.6 * hash(x, z) - 0.3, tx = x + lean * 1.4, top = y0 + 6;
  const rings = (px, py) => (py * 4 + 99) % 1 < 0.18 ? "-" : "o.";
  beam(world, [x, y0, z], [x + lean * 0.5, y0 + 3.2, z], "o", { tex: rings }, 0.2);
  beam(world, [x + lean * 0.5, y0 + 3.2, z], [tx, top, z + 0.2], "o", { tex: rings }, 0.15);
  for (let a = 0; a < 7; a++) {
    const c = Math.cos(a * 0.9), s = Math.sin(a * 0.9);
    beam(world, [tx, top, z + 0.2], [tx + 1.5 * c, top + 0.5, z + 0.2 + 1.5 * s], "g");
    beam(world, [tx + 1.5 * c, top + 0.5, z + 0.2 + 1.5 * s], [tx + 2.8 * c, top - 0.7, z + 0.2 + 2.8 * s], "G");
  }
}
for (const x of [-4, 12]) {
  box(world, x, 1.2, 14.4, x + 0.16, 4.2, 14.56, "t");
  box(world, x - 0.16, 4.2, 14.26, x + 0.32, 4.65, 14.7, "l");
}
// A mailbox by the office and a notice board on the quay that leads to how this page is built.
box(world, -0.55, 1.2, 21.4, -0.45, 2.2, 21.5, "t", { spot: "mailbox", post: true });
box(world, -0.8, 2.2, 21.2, -0.2, 2.7, 21.7, "r", { spot: "mailbox" });

// Plaza fountain: an octagonal stone basin, a raised rim, and four falling streams.
// Water changes texture with the existing clock; reduced motion freezes that clock.
function fountainWater(x, y, z) {
  if (y > 1.75) return Math.sin(y * 14 - T * 5) > 0.7 ? "m:" : "w|";
  const ripple = Math.sin(Math.hypot(x - 5, z - 24.6) * 16 - T * 3);
  return ripple > 0.65 ? "m~" : "w.";
}
function fountain() {
  const basin = column(world, 5, 24.6, 1.5, 1.5, 1.2, 1.64, "s",
    { tex: (x, y, z, nx, ny) => ny < 0.5 && y < 1.38 ? "-" : null });
  column(world, 5, 24.6, 1.29, 1.29, 1.64, 1.7, "w",
    { solid: false, dim: 2.4, tex: fountainWater });
  for (let i = 0; i < 8; i++) {
    const a = i * Math.PI / 4, b = (i + 1) * Math.PI / 4;
    const end = (angle, y) => [5 + 1.42 * Math.cos(angle), y, 24.6 + 1.42 * Math.sin(angle)];
    beam(world, end(a, 1.73), end(b, 1.73), "s", {}, 0.17);
    beam(world, end(a, 1.94), end(b, 1.94), "t", {}, 0.09);
  }
  column(world, 5, 24.6, 0.4, 0.24, 1.7, 2.55, "s",
    { tex: (x, y) => Math.abs(y - 1.95) < 0.06 || Math.abs(y - 2.4) < 0.04 ? "-" : null });
  column(world, 5, 24.6, 0.24, 0.5, 2.55, 2.75, "t");
  column(world, 5, 24.6, 0.065, 0.04, 2.75, 3.35, "m", { solid: false, dim: 2.4, tex: fountainWater });
  for (let i = 0; i < 4; i++) {
    const a = i * Math.PI / 2, c = Math.cos(a), s = Math.sin(a);
    const crest = [5 + c * 0.48, 3.1, 24.6 + s * 0.48];
    beam(world, [5, 3.35, 24.6], crest, "m", { dim: 2.4, tex: fountainWater }, 0.04);
    beam(world, crest, [5 + c * 0.95, 1.73, 24.6 + s * 0.95], "m",
      { dim: 2.4, tex: fountainWater }, 0.04);
  }
  return basin;
}
const fountainBasin = fountain();
// Landscaping: hedges round the plaza, round trees, lamps along the avenue, a fence on the quay front.
const plazaHedges = [];
for (const [x0, x1, z0, z1] of [[1, 2.2, 22, 27.4], [7.8, 9, 22, 27.4], [2.2, 3.4, 27.6, 28.4], [6.6, 7.8, 27.6, 28.4]]) {
  const hedge = box(world, x0, 1.2, z0, x1, 1.9, z1, "g", { tex: (x, y, z) => (hash(Math.floor(x * 3), Math.floor(z * 3 + y * 3)) < 0.3 ? "-" : null) });
  plazaHedges.push(hedge);
}
// Broadleaf trees: a barked trunk, three branches and a layered canopy of leafy ellipsoids that sway.
const canopies = [];
const leaves = (x, y, z) => { const h = hash(Math.floor(x * 4), Math.floor(y * 4 + z * 4)); return h < 0.3 ? "-" : h > 0.88 ? "G" : null; };
for (const [x, z, h] of [[-10, 23, 6.5], [0, 25, 5.5], [11, 24, 6], [17, 27, 7], [-22, 24, 6.2]]) {
  const width = h / 6 * (0.85 + hash(x, z) * 0.3), angle = hash(z, x) * 6.28, c = Math.cos(angle), sn = Math.sin(angle);
  const bark = (px, py, pz) => Math.sin(Math.atan2(pz - z, px - x) * 13 + Math.sin(py * 2) * 0.6) > 0.25 ? "-" : "o,";
  column(world, x, z, 0.3 * width, 0.17 * width, 1.2, 1.2 + h * 0.72, "o", { tex: bark });
  for (let a = 0; a < 3; a++) beam(world, [x, 1.2 + h * 0.45, z], [x + 1.3 * width * Math.cos(a * 2.1 + angle), 1.2 + h * 0.72, z + 1.3 * width * Math.sin(a * 2.1 + angle)], "o", { tex: bark }, 0.07);
  for (const [ox, oy, oz, r] of [[0, 0.85, 0, 1.7], [1, 0.72, 0.4, 1.1], [-0.8, 0.75, 0.7, 1.15], [0.2, 0.74, -1, 1.05], [0, 1.02, 0.1, 1]]) {
    const cx = x + (ox * c - oz * sn) * width, cz = z + (ox * sn + oz * c) * width, radius = r * width;
    const s = blob(world, cx, 1.2 + h * oy, cz, radius, radius * (0.6 + hash(x, oy) * 0.25), radius * (0.8 + hash(z, oy) * 0.35), oy < 0.8 ? "M" : oy > 1 ? "G" : "g", { dim: oy < 0.8 ? 0.8 : 1.25, tex: leaves });
    s.bb[0] -= 0.25; s.bb[3] += 0.25; s.bb[2] -= 0.25; s.bb[5] += 0.25;
    canopies.push({ s, x: cx, z: cz, phase: hash(x, oz) * 6 });
  }
}
// Canopies sway in the wind, higher leaves more.
function swayTrees() {
  for (const { s, x, z, phase } of canopies) {
    s.blob[0] = x + 0.18 * Math.sin(T * 1.1 + phase);
    s.blob[2] = z + 0.12 * Math.sin(T * 0.9 + phase * 1.7);
  }
}
for (const x of [-20, -10, 0, 10, 18]) {
  box(world, x, 1.2, 20.9, x + 0.14, 4, 21.04, "t");
  box(world, x - 0.14, 4, 20.76, x + 0.28, 4.4, 21.18, "l");
}
for (let x = -25; x < -6; x += 2.5) box(world, x, 1.2, 15.6, x + 0.12, 2.1, 15.72, "o");
box(world, -25, 1.75, 15.62, -6.3, 1.85, 15.7, "o");
box(world, -25, 1.45, 15.62, -6.3, 1.53, 15.7, "o");
const howText = painted("HOW", 7.4, 8.7, 2.45, 3.25);
for (const x of [7.35, 8.6]) box(world, x, 1.2, 16.72, x + 0.15, 2.4, 16.85, "o", { spot: "how", post: true });
box(world, 7.2, 2.35, 16.6, 8.9, 3.35, 16.72, "o", { spot: "how", tex: (x, y, z, nx, ny, nz) => (nz < -0.5 ? (howText(x, y) ? "l" : "-") : null) });
const docsText = painted("DOCS", -1.9, 0.3, 2.45, 3.25);
for (const x of [-1.95, 0.25]) box(world, x, 1.2, 16.72, x + 0.15, 2.4, 16.85, "o", { spot: "docsboard", post: true });
box(world, -2.1, 2.35, 16.6, 0.5, 3.35, 16.72, "o", { spot: "docsboard", tex: (x, y, z, nx, ny, nz) => (nz < -0.5 ? (docsText(x, y) ? "l" : "-") : null) });

// Ship stations [z, half breadth, sheer height, keel height]. The bow narrows and rises out of the water.
const HULL = [[-15, 2.35, 3.2, -0.5], [-12, 3.1, 2.8, -1.5], [-8, 3.1, DECK, -1.5],
  [4, 3.1, DECK, -1.5], [9, 2, 2.5, -0.1], [13, 0.18, 3, 2.7]];
function hullPortTone(y, z) {
  if (z > -7.5 && z < 4.5 && y > 0.65 && y < 1.4) {
    const port = Math.abs((z + 9) % 3 - 0.6);
    if (port < 0.45) return gunPortTone(y, port);
  }
  return null;
}
function gunPortTone(y, port) {
  return port > 0.31 || y < 0.78 || y > 1.27 ? "l" : "p";
}
function hullTexture(x, y, z, nx, ny, sheer) {
  if (ny > 0.6) return seam(x);
  const port = Math.abs(nx) > 0.6 ? hullPortTone(y, z) : null;
  if (port) return port;
  return Math.abs(y - sheer + 0.35) < 0.14 ? "s" : (y + 9) % 0.3 < 0.045 ? "-" : null;
}
function hullSection(a, b) {
  const [z0, w0, h0, k0] = a, [z1, w1, h1, k1] = b, dz = z1 - z0;
  const dh = (h1 - h0) / dz, dw = (w1 - w0) / dz, dk = (k1 - k0) / dz, rake = dw - 0.45 * dh;
  return solid(ship, [[0, 1, -dh, 0, h0, z0], [0, -1, dk, 0, k0, z0],
    [1, -0.45, -rake, SX + w0, h0, z0], [-1, -0.45, -rake, SX - w0, h0, z0],
    [0, 0, -1, 0, 0, z0], [0, 0, 1, 0, 0, z1]],
  [SX - Math.max(w0, w1), Math.min(k0, k1), z0, SX + Math.max(w0, w1), Math.max(h0, h1), z1],
  "o", { solid: false, tex: (x, y, z, nx, ny) => hullTexture(x, y, z, nx, ny, h0 + dh * (z - z0)), hull: true, fill: 0.48 });
}
function shipProfile(z) {
  for (let i = 1; i < HULL.length; i++) {
    const a = HULL[i - 1], b = HULL[i];
    if (z < a[0] || z > b[0]) continue;
    const t = (z - a[0]) / (b[0] - a[0]);
    return [a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
  }
  return null;
}
function shipRail(a, b, side) {
  const [z0, w0, y0] = a, [z1, w1, y1] = b, dz = z1 - z0;
  const x0 = SX + side * w0, dx = side * (w1 - w0) / dz, dy = (y1 - y0) / dz;
  solid(ship, [[1, 0, -dx, x0 + 0.06, 0, z0], [-1, 0, dx, x0 - 0.06, 0, z0],
    [0, 1, -dy, 0, y0 + 0.8, z0], [0, -1, dy, 0, y0, z0],
    [0, 0, 1, 0, 0, z1], [0, 0, -1, 0, 0, z0]],
  [Math.min(x0, SX + side * w1) - 0.06, Math.min(y0, y1), z0,
    Math.max(x0, SX + side * w1) + 0.06, Math.max(y0, y1) + 0.8, z1],
  "s", { solid: false, thin: true, fill: 0.75, rail: [z0, y0, dy, dz / Math.ceil(dz / 2)] });
}
for (let i = 1; i < HULL.length; i++) {
  const a = HULL[i - 1], b = HULL[i];
  hullSection(a, b);
  shipRail(a, b, -1);
  if (a[0] === -8) {
    shipRail(a, [-1.8, 3.1, DECK], 1);
    shipRail([-0.6, 3.1, DECK], b, 1);
  } else shipRail(a, b, 1);
}
beam(ship, [SX - 2.35, 3.95, -15], [SX + 2.35, 3.95, -15], "s", { fill: 0.58 }, 0.065);
// Recessed dark gun ports and iron barrels share the same gun-deck stations, below the walking deck.
for (const z of [-5.4, -2.4, 0.6, 3.6]) {
  for (const side of [-1, 1]) {
    const x = SX + side * (3.1 - 0.45 * (DECK - 1.02));
    beam(ship, [x - side * 0.35, 1.02, z], [x + side * 0.5, 1.02, z], "t", { fill: 0.32 }, 0.14);
  }
}
// The stern castle is the cabin. It follows the tapered transom, not a box hung over the water: planked walls with a
// strap-hinged door, framed windows on the front, down each side and across the stern, and pale trim. Its roof is the
// stern deck.
solid(ship, [[0, 1, 0, 0, 4.8, 0], [0, -1, 0, 0, DECK, 0],
  [0, 0, -1, 0, 0, -14.6], [0, 0, 1, 0, 0, -9],
  [1, 0, -0.08, SX + 2.1, 0, -14.6], [-1, 0, -0.08, SX - 2.1, 0, -14.6]],
[SX - 2.55, DECK, -14.6, SX + 2.55, 4.8, -9], "o", { spot: "cabin", tex: cabinWall, fill: 0.48 });
// Window centres: x from the centre line on the front and the stern, z along the sides.
const CABIN_WINDOWS = { front: [-1.6], side: [-10.6, -12.9], stern: [-1.3, 0, 1.3] };
// Deck seams on the roof; framed windows and horizontal planks on the walls.
function cabinWall(x, y, z, nx, ny, nz) {
  if (ny > 0.5) return seam(x);
  const side = Math.abs(nx) > 0.5, u = side ? z : x - SX;
  return cabinWindow(u, y, side ? CABIN_WINDOWS.side : nz > 0.5 ? CABIN_WINDOWS.front : CABIN_WINDOWS.stern) ||
    ((y - DECK) % 0.25 < 0.035 ? "-" : null);
}
// Two brass strap hinges and a ring handle on the dark painted door leaf.
function cabinDoor(x, y) {
  const u = x - SX;
  return (u - 0.3) ** 2 + (y - 3) ** 2 < 0.0049 || (u < -0.1 && (Math.abs(y - 2.35) < 0.045 || Math.abs(y - 3.6) < 0.045)) ? "y" : "-";
}
// A pale frame and crossbars round four lit panes.
function cabinWindow(u, y, centres) {
  if (y < 2.9 || y > 3.9) return null;
  for (const c of centres) {
    const d = Math.abs(u - c);
    if (d <= 0.4) return d > 0.33 || y < 2.97 || y > 3.83 || d < 0.035 || Math.abs(y - 3.4) < 0.035 ? "s" : "l";
  }
  return null;
}
// Raised trim does not change the walking bounds, map footprint, feature anchor or shadows.
const cabinTrim = { spot: "cabin", anchor: false, solid: false, thin: true, fill: 0.55, shadow: false };
box(ship, SX - 0.5, DECK, -9.01, SX + 0.5, 3.95, -8.97, "f", { ...cabinTrim, fill: 0.5, tex: cabinDoor });
for (const x of [-0.58, 0.58]) beam(ship, [SX + x, DECK, -8.96], [SX + x, 4.02, -8.96], "s", cabinTrim, 0.07);
beam(ship, [SX - 0.66, 4, -8.96], [SX + 0.66, 4, -8.96], "s", cabinTrim, 0.08);
for (const side of [-1, 1]) {
  beam(ship, [SX + side * 2.55, DECK, -9.02], [SX + side * 2.55, 4.8, -9.02], "s", cabinTrim, 0.08);
  beam(ship, [SX + side * 2.14, 4.72, -14.6], [SX + side * 2.59, 4.72, -9], "s", cabinTrim, 0.07);
  shipRail([-14.6, 2.1, 4.8], [-9, 2.55, 4.8], side);
  shipLantern(SX + side * 2.5, 4.8, -14.3, false, SX + side * 2.1);
}
beam(ship, [SX - 2.62, 4.72, -8.96], [SX + 2.62, 4.72, -8.96], "s", cabinTrim, 0.07);
beam(ship, [SX - 2.1, 5.55, -14.6], [SX + 2.1, 5.55, -14.6], "s", { fill: 0.58 }, 0.06);
// A wall lantern hangs between the door and the stairs. Its glass glows like the windows but adds no light: another
// ship light costs more per frame than its pool of lamplight shows.
beam(ship, [SX + 0.88, 4.02, -9], [SX + 0.88, 4.02, -8.69], "t", cabinTrim, 0.03);
box(ship, SX + 0.74, 3.92, -8.86, SX + 1.02, 3.99, -8.58, "t", cabinTrim);
box(ship, SX + 0.77, 3.62, -8.83, SX + 0.99, 3.92, -8.61, "t", { ...cabinTrim, tex: () => "l" });
function shipLantern(x, y, z, anchor = false, mountX = x) {
  beam(ship, [mountX, y, z], [mountX, y + 1.13, z], "o", { fill: 0.4 }, 0.045);
  if (mountX !== x) beam(ship, [mountX, y + 1.13, z], [x, y + 1.13, z], "o", { fill: 0.4 }, 0.045);
  box(ship, x - 0.2, y + 0.7, z - 0.2, x + 0.2, y + 1.05, z + 0.2, "l", { spot: "lantern", anchor });
  box(ship, x - 0.25, y + 1.05, z - 0.25, x + 0.25, y + 1.13, z + 0.25, "t", { solid: false });
}
shipLantern(1.15, DECK, 3, false, 0.7);
shipLantern(SX - 3.55, DECK, -4, false, SX - 3.1);
shipLantern(SX, 2.63, 10, true);
// Square canvas hangs from horizontal yards braced round on each mast, and the wind across a sail fills it to leeward:
// the head stays on its yard, the belly is deepest across the middle low down, the foot sags in an arc between the
// corners, and the leeches bow out.
const SAILS = [];
function squareSail(z, top, width, drop) {
  const c = Math.cos(0.6), s = Math.sin(0.6), belly = 0.45 * width * WIND.strength * (WIND.z * c - WIND.x * s);
  // The corners hang drop - 0.1 below the yard, and the foot sags 13% lower between them. The deepest canvas stands
  // 1.13 bellies out, and up to 10% more as the sail breathes.
  const sag = 0.13, bow = 0.08, v1 = (drop - 0.1) / (1 - sag), deep = 1.25 * belly;
  beam(ship, [SX - (width + 0.2) * c, top, z - (width + 0.2) * s],
    [SX + (width + 0.2) * c, top, z + (width + 0.2) * s],
    "o", { spot: "mast", anchor: false, fill: 0.5 }, 0.075);
  const sail = cloth(ship, [SX, top - 0.1, z], c, s, [-width * (1 + bow), width * (1 + bow), v1, Math.min(0, deep), Math.max(0, deep)],
    { half: width, base: belly, belly, sag, bow }, "s", { tex: sailTexture, fill: 0.8 });
  SAILS.push(sail);
  return sail;
}
// Two reef bands, each about one cell (`cell` metres) thick, cross the canvas parallel to its sagging foot. Farther off,
// where cells grow past a quarter metre, the bands would cover much of the canvas, so they are left out.
function sailTexture(u, v, cell, k) {
  const foot = clothFoot(k, u), s = 3 * v / foot;
  return cell < 0.25 && s > 0.5 && s < 2.5 && Math.abs(s - Math.round(s)) * foot / 3 < cell * 0.6 ? "-" : null;
}
const RIGGING = [], CLEWS = [];
function shipMast(z, foot, height, width) {
  column(ship, SX, z, 0.16, 0.16, foot, height, "o", { spot: "mast", fill: 0.42 });
  const topsail = squareSail(z, height - 2.3, width * 0.7, 3.8), course = squareSail(z, height - 7.2, width, 5.5);
  for (const side of [-1, 1]) {
    for (const dz of [-1.6, 1.6]) {
      const [w, y] = shipProfile(z + dz);
      shipRope([SX, height - 3, z], [SX + side * w, y + 0.3, z + dz]);
    }
    sheet(topsail, side, clothPoint(course, side * course.half, 0));
    sheet(course, side);
  }
}
// A sheet runs taut from a sail's lower corner, which moves as the canvas fills, to `to`: by default the rail
// 2.5 m aft of the corner.
function sheet(sail, side, to) {
  const clew = clothPoint(sail, side * sail.half, clothFoot(sail, side * sail.half));
  CLEWS.push([sail, side, clew]);
  if (!to) {
    const z = clew[2] - 2.5, [w, y] = shipProfile(z);
    to = [SX + side * (w - 0.05), y + 0.75, z];
  }
  shipRope(clew, to);
}
shipMast(-3, DECK, 20.5, 5.1);
shipMast(6, 2.2, 18.2, 4.3);
shipRope([SX, 20, -3], [SX, 17.8, 6]);
shipRope([SX, 20, -3], [SX, 4.8, -14.3]);
shipRope([SX, 17.8, 6], [SX, 4.3, 18.5]);
function shipRope(a, b, cls) {
  RIGGING.push([a, b, cls]);
}
// Screen column and row (fractional) and depth of a world point, written into `out`.
function viewPoint(x, y, z, out) {
  x -= cam.x; y -= cam.y; z -= cam.z;
  const d = x * cam.f[0] + y * cam.f[1] + z * cam.f[2], div = Math.max(0.001, d);
  out[0] = ((x * cam.r[0] + z * cam.r[2]) / div / cam.tanH + 1) * cols / 2;
  out[1] = (1 - (x * cam.u[0] + y * cam.u[1] + z * cam.u[2]) / div / cam.tanV) * rows / 2;
  out[2] = d;
  return out;
}
// Project the stays and the stair rails into the depth buffer once, rather than ray-testing their large diagonal boxes.
function ropePoint(p) {
  const lx = p[0] - SX;
  return viewPoint(SX + rc * lx - rs * p[1], rs * lx + rc * p[1] + bob, p[2], [0, 0, 0]);
}
function ropeEnds(a, b) {
  let p = ropePoint(a), q = ropePoint(b);
  if (p[2] < 0.2 && q[2] < 0.2) return null;
  if (p[2] < 0.2) { const t = (0.2 - p[2]) / (q[2] - p[2]); p = ropePoint(a.map((v, i) => v + (b[i] - v) * t)); }
  if (q[2] < 0.2) { const t = (0.2 - q[2]) / (p[2] - q[2]); q = ropePoint(b.map((v, i) => v + (a[i] - v) * t)); }
  return [p, q];
}
function ropeSpan(p, q) {
  let lo = 0, hi = 1;
  for (let k = 0; k < 2; k++) {
    const d = q[k] - p[k], max = k ? rows : cols;
    if (Math.abs(d) < 0.001) { if (p[k] < -1 || p[k] > max) return null; continue; }
    const a = (-1 - p[k]) / d, b = (max - p[k]) / d;
    lo = Math.max(lo, Math.min(a, b)); hi = Math.min(hi, Math.max(a, b));
  }
  return lo > hi ? null : [lo, hi];
}
function ropeCell(i, j, depth, ch, cls) {
  if (i < 0 || i >= cols || j < 0 || j >= rows) return;
  const c = j * cols + i, h = ((2 * i + 1) / cols - 1) * cam.tanH, v = (1 - (2 * j + 1) / rows) * cam.tanV;
  const distance = depth * Math.sqrt(1 + h * h + v * v);
  if (distance > D[c] + 0.05) return;
  put(c, ch, cls, -1, distance); SP[c] = null;
}
function drawRope(p, q, cls = "o3") {
  const span = ropeSpan(p, q);
  if (!span) return;
  const [lo, hi] = span, dx = q[0] - p[0], dy = q[1] - p[1];
  const n = Math.max(1, Math.ceil(Math.max(Math.abs(dx), Math.abs(dy)) * (hi - lo)));
  const ch = Math.abs(dx) < Math.abs(dy) * 0.5 ? "|" : Math.abs(dy) < Math.abs(dx) * 0.5 ? "-" : dx * dy > 0 ? "\\" : "/";
  for (let k = 0; k <= n; k++) {
    const t = lo + (hi - lo) * k / n, depth = 1 / ((1 - t) / p[2] + t / q[2]);
    ropeCell(Math.floor(p[0] + dx * t), Math.floor(p[1] + dy * t), depth, ch, cls);
  }
}
function drawRigging() {
  for (const [a, b, cls] of RIGGING) {
    const ends = ropeEnds(a, b);
    if (ends) drawRope(...ends, cls);
  }
}
column(ship, SX, -3, 0.8, 0.85, 13.7, 14.4, "o", { spot: "nest", tex: (x, y) => (y < 13.85 ? "-" : null) });
// The flagstaff tops the main mast. The black flag streams downwind from it, rippling out to its wavy fly.
column(ship, SX, -3, 0.055, 0.055, 20.5, 23.4, "o", { solid: false, fill: 0.42 });
const FLAG = cloth(ship, [SX, 22.9, -3], WIND.x, WIND.z, [0, 5.2, 3, -0.15, 0.15], { half: 5.2, ripple: 0.12 }, "p",
  { flag: true, tex: pirateFlag });
// The Jolly Roger in the flag's (u, v): a pale skull with dark eyes and a jaw over two crossed bones, which keep about
// a cell (`cell` metres) thick and take the slanted glyph of their direction.
function pirateFlag(u, v, cell) {
  const x = (u - 2.5) / 0.7, y = (v - 1.12) / 0.56, bx = u - 2.5, by = v - 1.8, thick = Math.max(0.15, cell * 0.6);
  if (x * x + y * y < 1) return Math.abs(Math.abs(x) - 0.42) < 0.24 && Math.abs(y + 0.05) < 0.3 ? " " : "@";
  if (Math.abs(x) < 0.5 && y >= 1 && y < 1.55) return "@";
  if (Math.abs(bx) > 1.45) return null;
  return Math.abs(by - 0.55 * bx) < thick ? "\\" : Math.abs(by + 0.55 * bx) < thick ? "/" : null;
}
// Red pennants stream downwind from the mastheads and wave more toward the tip; like the stays, they are projected lines.
const PENNANTS = [[SX, 23.35, -3], [SX, 18.15, 6]];
function drawPennants() {
  for (const [x, y, z] of PENNANTS) {
    let a = [x, y, z];
    for (let k = 1; k <= 6; k++) {
      const f = k / 6, side = 0.3 * f * Math.sin(k * 1.2 - T * 3.4);
      const b = [x + 4 * f * WIND.x - side * WIND.z, y - 0.3 * f * f, z + 4 * f * WIND.z + side * WIND.x];
      const ends = ropeEnds(a, b);
      if (ends) drawRope(...ends, "r4");
      a = b;
    }
  }
}
// The wind breathes: each sail fills and eases a little, slowly, its sheets follow, and the flag's ripples run out.
function billow() {
  for (const sail of SAILS) sail.belly = sail.base * (1 + 0.1 * Math.sin(T * 1.1 - sail.at[2] * 0.25 - sail.at[1] * 0.1));
  for (const [sail, side, clew] of CLEWS) clothPoint(sail, side * sail.half, clothFoot(sail, side * sail.half), clew);
  FLAG.phase = T * 2.8;
}
// The bowsprit extends forward along the keel, away from the breakwater tower.
beam(ship, [SX, 2.6, 10], [SX, 4.3, 18.5], "o", {}, 0.12);
beam(ship, [SX, 2.8, 12.7], [SX, 4.3, 18.5], "o");
// A carved figurehead sits under the bowsprit at the stem, facing out to sea.
blob(ship, SX, 3.1, 13.4, 0.28, 0.65, 0.3, "o", { solid: false, dim: 1.7 });
blob(ship, SX, 3.8, 13.55, 0.22, 0.23, 0.24, "s", { solid: false });
beam(ship, [SX - 0.25, 3.4, 13.4], [SX + 0.25, 3.45, 13.9], "o", {}, 0.07);
const nameText = painted("CREWSHIP", -0.8, 4.2, 1.7, 2.05);
box(ship, 0.7, 1.62, -0.8, 0.76, 2.1, 4.2, "o", { spot: "sign", tex: (x, y, z, nx) => (nx > 0.5 && nameText(z, y) ? "s" : null) });
box(ship, SX - 0.1, DECK, -7.05, SX + 0.1, 3.1, -6.85, "o", { spot: "helm" });
disc(ship, SX, 3.3, -6.85, -6.72, 0.62, "o", { spot: "helm", tex: (x, y) => {
  const dx = x - SX, dy = y - 3.3, rr = Math.hypot(dx, dy);
  return rr > 0.42 || rr < 0.12 || Math.abs(Math.sin(4 * Math.atan2(dy, dx))) < 0.25 ? null : "-";
} });
box(ship, -3.6, DECK, 0.8, -1.2, 2.55, 3.2, "o", { spot: "hold",
  tex: (x, y, z, nx, ny) => (ny > 0.5 && ((x + 9) % 0.4 < 0.07 || (z + 9) % 0.4 < 0.07) ? "-" : null) });
beam(ship, [-3.5, 4.8, -11.5], [-3.5, 5.55, -11.5], "o", { spot: "spyglass" }, 0.05);
beam(ship, [-3.8, 5.45, -12.1], [-3, 5.8, -10.8], "t", { spot: "spyglass" }, 0.1);
box(ship, -3.4, 2.2, 6, -3.25, 3.8, 6.15, "o", { spot: "bell" });
column(ship, -3.32, 6.07, 0.3, 0.12, 3.05, 3.65, "r", { spot: "bell" });
box(ship, -4.8, DECK, 0.3, -4.3, 2.5, 0.9, "t", { spot: "strongbox", tex: (x, y) => (Math.abs(y - 2.3) < 0.05 ? "-" : null) });
// Ten steps climb from the main deck to the stern castle's roof, each a pale tread over a darker riser. Under each step
// the block is cut along the slope of the flight, so from the side the steps sit on one straight stringer and the
// soffit below is open. The hand rails are projected lines, like the rigging. The walking lane matches the treads.
const STERN_STEPS = [];
const RISE = 0.28, RUN = 0.35, STAIR_X0 = SX + 1.15, STAIR_X1 = SX + 2.25;
for (let k = 1; k <= 10; k++) {
  const front = -5.5 - (k - 1) * RUN, height = DECK + k * RISE;
  solid(ship, [[1, 0, 0, STAIR_X1, 0, 0], [-1, 0, 0, STAIR_X0, 0, 0], [0, 1, 0, 0, height, 0], [0, -1, 0, 0, DECK, 0],
    [0, 0, 1, 0, 0, front], [0, 0, -1, 0, 0, front - RUN], [0, -1, -RISE / RUN, 0, DECK - 0.3, -5.5]],
  [STAIR_X0, Math.max(DECK, height - RISE - 0.3), front - RUN, STAIR_X1, height, front], "o", { solid: false, fill: 0.55, tex: (x, y, z, nx, ny) => (ny > 0.5 ? "s" : "-") });
  STERN_STEPS.push([SX + 1.45, SX + 1.95, front - RUN, front, (x) => bob + height * rc + rs * (x - SX)]);
}
for (const x of [STAIR_X0 - 0.03, STAIR_X1 + 0.03]) {
  const foot = [x, DECK + RISE + 0.85, -5.47], head = [x, 4.8 + 0.85, -8.68];
  shipRope([x, DECK, -5.47], foot, "s5");
  shipRope(foot, head, "s5");
  shipRope([x, 4.8, -8.68], head, "s5");
}
const SHIP_BOUNDS = [Infinity, Infinity, Infinity, -Infinity, -Infinity, -Infinity];
for (const { bb } of ship) {
  for (let k = 0; k < 3; k++) {
    SHIP_BOUNDS[k] = Math.min(SHIP_BOUNDS[k], bb[k]);
    SHIP_BOUNDS[k + 3] = Math.max(SHIP_BOUNDS[k + 3], bb[k + 3]);
  }
}

// The gangway hinges between the rocking deck and the dock, so its planes are rebuilt per frame.
const gangway = solid(world, [[0, 1, 0, 0, 0, 0], [0, -1, 0, 0, 0, 0], [1, 0, 0, 3.1, 0, 0],
  [-1, 0, 0, 0.55, 0, 0], [0, 0, 1, 0, 0, -0.6], [0, 0, -1, 0, 0, -1.8]], [0.55, 0, -1.8, 3.1, 0, -0.6], "o",
{ spot: "gangway", solid: false, tex: (x) => ((x + 9) % 0.5 < 0.07 ? "-" : null) });

// ---- Interiors: the house and the ship's cabin, separate rooms with the same materials and glyph renderer ----
function roomFloor(x, y, z) {
  return (x + 9) % 0.55 < 0.025 || (z + 9) % 2 < 0.025 ? "-" : null;
}
function roomWindow(x, y) {
  return hash(Math.floor(x * 12), Math.floor(y * 12)) > 0.985 ? "*" : ".";
}
// A flame's glyph and colour at height y in its box b, from the base to the tip: an orange core, golden flame and
// pale tips. Flames keep these glyphs, so the idle room still needs no redraws; the room light carries the glow.
const FLAME = [["#", "rw6"], ["*", "l6"], ["'", "l7"]];
function roomFlame(y, b) {
  return FLAME[Math.min(2, 3 * (y - b[1]) / (b[4] - b[1]) | 0)];
}
// Big brick courses with staggered joints, along whichever horizontal axis the face runs. Each joint starts
// another colour run in a text row, so the bricks stay large and only line the firebox.
function brickBond(x, y, z) {
  const u = x + z + (Math.floor((y + 9) / 0.2) % 2) * 0.25;
  return (y + 9) % 0.2 < 0.025 || (u + 9) % 0.5 < 0.03 ? "-" : null;
}
// A row of books standing at height y0, at most h tall: eight spine colours, uneven heights and dark gaps,
// along whichever horizontal axis the row runs.
const SPINES = "rbgoynhM";
function bookRow(x0, y0, z0, x1, h, z1) {
  box(room, x0, y0, z0, x1, y0 + h, z1, "n", { tex: (x, y, z) => {
    const u = (x + z + 9) * 15, k = Math.floor(u);
    return u - k < 0.12 || y - y0 > h * (0.6 + 0.4 * hash(k, 5)) ? "p" : SPINES[Math.floor(hash(k, 7) * SPINES.length)];
  } });
}
// A fireplace on the right wall: hearth, brick jambs and lintel, sooty back, mantel, a smooth brick-red chimney
// breast, and a fire of embers, logs and flames.
function fireplace() {
  const brick = { tex: brickBond, dim: 0.75 };
  box(room, 2.2, 0, 3.55, 3, 0.06, 5.25, "t");
  for (const z of [3.7, 4.8]) box(room, 2.62, 0.06, z, 3, 1.15, z + 0.3, "r", brick);
  box(room, 2.62, 0.85, 4, 3, 1.15, 4.8, "r", brick);
  box(room, 2.92, 0.06, 4, 3, 0.85, 4.8, "p", { dim: 0.15 });
  box(room, 2.5, 1.15, 3.6, 3, 1.25, 5.2, "o");
  box(room, 2.68, 1.25, 3.75, 3, 3.4, 5.05, "r", { dim: 0.55 });
  box(room, 2.66, 0.06, 4.1, 2.9, 0.1, 4.7, "r");
  for (const x of [2.68, 2.8]) box(room, x, 0.1, 4.15, x + 0.1, 0.2, 4.65, "n", { dim: 0.5 });
  for (const [x, z, r, h] of [[2.84, 4.18, 0.07, 0.3], [2.76, 4.3, 0.1, 0.5], [2.79, 4.44, 0.13, 0.62], [2.76, 4.57, 0.09, 0.45], [2.84, 4.66, 0.06, 0.28]]) {
    column(room, x, z, r, 0.01, 0.2, 0.2 + h, "l", { tex: roomFlame });
  }
}
// A bookcase against the back wall, left of the window, with a row of books on each shelf.
function bookcase() {
  for (const x of [-2.95, -1.85]) box(room, x, 0, 5.58, x + 0.05, 2.3, 6, "o");
  box(room, -2.97, 2.3, 5.55, -1.78, 2.36, 6, "o");
  for (const [y, end, h] of [[0, -1.95, 0.42], [0.6, -2.2, 0.34], [1.12, -1.92, 0.38], [1.62, -2.35, 0.3]]) {
    box(room, -2.9, y, 5.6, -1.9, y + 0.05, 6, "o");
    bookRow(-2.88, y + 0.05, 5.66, end, h, 5.96);
  }
}
// A wooden chair at (x, z) facing +z (facing 1) or -z (facing -1): four legs, a seat and a back.
function chair(x, z, facing) {
  for (const dx of [-0.2, 0.16]) for (const dz of [-0.2, 0.16]) box(room, x + dx, 0, z + dz, x + dx + 0.04, 0.45, z + dz + 0.04, "o");
  box(room, x - 0.22, 0.45, z - 0.22, x + 0.22, 0.5, z + 0.22, "o");
  const back = z - facing * 0.2;
  box(room, x - 0.22, 0.5, back - 0.025, x + 0.22, 1, back + 0.025, "o");
}
// A leather armchair facing +z from its corner at (x0, z0): seat, back and arms.
function armchair(x0, z0) {
  box(room, x0, 0, z0, x0 + 0.75, 0.42, z0 + 0.7, "n");
  box(room, x0, 0, z0, x0 + 0.75, 0.95, z0 + 0.18, "n");
  for (const x of [x0, x0 + 0.61]) box(room, x, 0.42, z0 + 0.18, x + 0.14, 0.62, z0 + 0.7, "n");
}
// A clay pot with a two-tier leafy crown standing at height y, `size` times a 1 m plant. The crown uses cones, not
// ellipsoids: an ellipsoid would add another object shape to the room's ray loop and slow every room frame.
function plant(x, z, y, size) {
  const top = y + 0.36 * size;
  column(room, x, z, 0.16 * size, 0.2 * size, y, top, "r");
  column(room, x, z, 0.34 * size, 0.08 * size, top, top + 0.6 * size, "M");
  column(room, x, z, 0.24 * size, 0.01, top + 0.4 * size, top + size, "M");
}
// A woven rug flat on the floor: a pale border, a brown band, then pale diamonds on red. It does not block walking.
function rug(x0, z0, x1, z1) {
  box(room, x0, 0, z0, x1, 0.015, z1, "r", { tex: (x, y, z) => {
    const edge = Math.min(x - x0, x1 - x, z - z0, z1 - z);
    if (edge < 0.2) return edge < 0.12 ? "y" : "n";
    return Math.abs((x + 9) * 2 % 1 - 0.5) + Math.abs((z + 9) * 2 % 1 - 0.5) < 0.2 ? "y" : null;
  } });
}
// A sea chart in a wooden frame, flat on a wall, in a box that is thin across the wall: pale coasts and blue
// water under a grid. Charts do not block walking.
function chart(x0, y0, z0, x1, y1, z1) {
  const alongX = x1 - x0 > z1 - z0, a0 = alongX ? x0 : z0, a1 = alongX ? x1 : z1;
  box(room, x0, y0, z0, x1, y1, z1, "y", { solid: false, tex: (x, y, z) => {
    const u = alongX ? x : z;
    if (Math.min(y - y0, y1 - y, u - a0, a1 - u) < 0.05) return "o";
    if ((u + 9) * 6 % 1 < 0.08 || (y + 9) * 6 % 1 < 0.08) return "t";
    return Math.sin(u * 5) + Math.sin(y * 7 + u * 2) > 0.9 ? null : "b";
  } });
}
function buildRoom() {
  box(room, -3.2, -0.2, -0.2, 3.2, 0, 6.2, "o", { tex: roomFloor, dim: 0.4 });
  const plaster = { dim: 0.32 };
  box(room, -3.2, 3.4, -0.2, 3.2, 3.6, 6.2, "s", plaster);
  for (const [x0, x1] of [[-3.2, -3], [3, 3.2]]) box(room, x0, 0, 0, x1, 3.4, 6, "s", plaster);
  box(room, -3, 0, 6, 3, 3.4, 6.2, "s", plaster);
  for (const [x0, x1] of [[-3, -0.7], [0.7, 3]]) box(room, x0, 0, -0.2, x1, 3.4, 0, "s", plaster);
  box(room, -0.7, 2.4, -0.2, 0.7, 3.4, 0, "s", plaster);
  box(room, -0.7, 0, -0.15, 0.7, 2.4, -0.1, "d", { solid: false });
  for (const x of [-0.75, 0.65]) box(room, x, 0, 0, x + 0.1, 2.45, 0.12, "o");
  box(room, -0.75, 2.4, 0, 0.75, 2.5, 0.12, "o");
  box(room, -1.5, 1.3, 5.84, 1.5, 2.8, 5.95, "d", { tex: roomWindow });
  for (const x of [-1.6, -0.04, 1.5]) box(room, x, 1.2, 5.75, x + 0.1, 2.9, 6, "o");
  for (const y of [1.2, 2.1, 2.8]) box(room, -1.6, y, 5.75, 1.6, y + 0.1, 6, "o");
  // The bed faces the doorway; the right aisle stays clear for walking to the window.
  box(room, -2.6, 0.9, 2.4, -1.1, 1.05, 3.6, "o");
  for (const x of [-2.5, -1.3]) for (const z of [2.5, 3.4]) box(room, x, 0, z, x + 0.12, 0.9, z + 0.12, "o");
  box(room, -0.6, 0.3, 3.2, 1, 0.6, 5.4, "o");
  box(room, -0.6, 0.6, 3.2, 1, 0.85, 5.4, "b");
  box(room, -0.4, 0.85, 4.8, 0.8, 1.05, 5.25, "s");
  box(room, -0.7, 0.3, 5.4, 1.1, 1.2, 5.52, "o");
  box(room, -0.7, 0.3, 3.08, 1.1, 0.75, 3.2, "o");
  for (const x of [-0.55, 0.85]) for (const z of [3.2, 5.3]) box(room, x, 0, z, x + 0.1, 0.3, z + 0.1, "o");
  column(room, -2.2, 2.9, 0.12, 0.1, 1.05, 1.7, "t");
  column(room, -2.2, 2.9, 0.35, 0.2, 1.7, 2.1, "l");
  // Furniture stands against the walls; the middle of the room and the right aisle stay clear.
  fireplace();
  bookcase();
  chair(-1.85, 2.12, 1);
  chair(-1.85, 3.88, -1);
  armchair(1.85, 1.75);
  for (const b of [[2.15, 0, 0.08, 2.85, 0.62, 0.72], [2.25, 0.62, 0.14, 2.75, 1.06, 0.6], [1.5, 0, 0.1, 2.05, 0.5, 0.6]]) {
    box(room, ...b, "o", { tex: crateSlats });
  }
  plant(2.55, 5.5, 0, 1.15);
  plant(1.1, 5.87, 1.3, 0.45);
  rug(-0.9, 1.15, 1.3, 2.85);
  chart(-3, 1.3, 0.7, -2.97, 2.1, 1.85);
  chart(2.97, 1.35, 1.4, 3, 2.05, 2.5);
  chart(1.85, 1.6, 5.97, 2.85, 2.35, 6);
  // By the door: a sea chest under a wall shelf of books and a glass jar.
  box(room, -2.5, 0, 0.06, -1.45, 0.42, 0.6, "o", { dim: 0.7, tex: crateSlats });
  box(room, -2.54, 0.42, 0.04, -1.41, 0.52, 0.64, "n");
  box(room, -2.6, 1.45, 0, -1.3, 1.5, 0.28, "o");
  bookRow(-2.55, 1.5, 0.03, -1.75, 0.3, 0.25);
  column(room, -1.5, 0.14, 0.07, 0.06, 1.5, 1.72, "h");
}
buildRoom();
// A sea chart in its own plane (u, v): a grid and wavy coastlines.
function chartLine(u, v) {
  return (u + 9) % 0.16 < 0.012 || (v + 9) % 0.16 < 0.012 || Math.abs((v + 9) % 0.5 - 0.25 - 0.08 * Math.sin(u * 9)) < 0.015 ? "-" : null;
}
// The cabin under the stern deck: plank walls and deck beams, starry windows where the outside shows them, a chart
// table under a hanging lantern, a chair, a bunk along the port wall and a sea chest.
function buildCabin() {
  const wood = { dim: 0.36, tex: (x, y) => ((y + 9) % 0.22 < 0.02 ? "-" : null) }, pane = { tex: roomWindow, solid: false };
  box(cabinRoom, -2.4, -0.2, -0.2, 2.4, 0, 5.4, "o", { tex: roomFloor, dim: 0.4 });
  box(cabinRoom, -2.4, 2.45, -0.2, 2.4, 2.65, 5.4, "o", { dim: 0.28 });
  for (const z of [1.2, 2.5, 3.8]) box(cabinRoom, -2.2, 2.3, z, 2.2, 2.45, z + 0.16, "o", { dim: 0.45 });
  for (const [x0, x1] of [[-2.4, -2.2], [2.2, 2.4]]) box(cabinRoom, x0, 0, 0, x1, 2.45, 5.2, "o", wood);
  box(cabinRoom, -2.2, 0, 5.2, 2.2, 2.45, 5.4, "o", wood);
  for (const [x0, x1] of [[-2.2, -0.55], [0.55, 2.2]]) box(cabinRoom, x0, 0, -0.2, x1, 2.45, 0, "o", wood);
  box(cabinRoom, -0.55, 1.95, -0.2, 0.55, 2.45, 0, "o", wood);
  box(cabinRoom, -0.55, 0, -0.15, 0.55, 1.95, -0.1, "f", { solid: false, tex: (x, y) => ((x + 0.3) ** 2 + (y - 1) ** 2 < 0.0049 ? "y" : null) });
  for (const x of [-0.62, 0.52]) box(cabinRoom, x, 0, 0, x + 0.1, 2.02, 0.1, "o");
  box(cabinRoom, -0.62, 1.95, 0, 0.62, 2.05, 0.1, "o");
  box(cabinRoom, 1.27, 0.9, 0, 1.93, 1.8, 0.06, "d", pane);
  for (const x of [-2.2, 2.14]) for (const z of [1.6, 3.9]) box(cabinRoom, x, 0.9, z - 0.33, x + 0.06, 1.8, z + 0.33, "d", pane);
  for (const x of [-1.3, 0, 1.3]) {
    box(cabinRoom, x - 0.33, 0.9, 5.14, x + 0.33, 1.8, 5.2, "d", pane);
    box(cabinRoom, x - 0.03, 0.9, 5.1, x + 0.03, 1.8, 5.2, "o");
  }
  box(cabinRoom, -1.7, 1.33, 5.1, 1.7, 1.39, 5.2, "o");
  box(cabinRoom, -1.76, 0.84, 5.02, 1.76, 0.9, 5.2, "o");
  box(cabinRoom, -2.2, 0.95, 2.1, -2.16, 1.75, 3.4, "y", { tex: (x, y, z) => chartLine(z, y), solid: false });
  box(cabinRoom, -0.85, 0.72, 2.7, 0.85, 0.8, 3.7, "o");
  for (const x of [-0.78, 0.7]) for (const z of [2.77, 3.55]) box(cabinRoom, x, 0, z, x + 0.08, 0.72, z + 0.08, "o");
  box(cabinRoom, -0.62, 0.8, 2.82, 0.22, 0.81, 3.42, "y", { tex: (x, y, z) => chartLine(x, z) });
  box(cabinRoom, 0.02, 0.8, 3, 0.66, 0.815, 3.58, "y", { tex: (x, y, z) => chartLine(x + 0.4, z), dim: 0.85 });
  beam(cabinRoom, [-0.7, 0.85, 3.6], [0.05, 0.85, 3.62], "y", {}, 0.035);
  box(cabinRoom, -0.28, 0, 4.05, 0.28, 0.48, 4.55, "o");
  box(cabinRoom, -0.28, 0.48, 4.47, 0.28, 1.1, 4.55, "o");
  beam(cabinRoom, [0, 2.45, 3.2], [0, 2, 3.2], "t", {}, 0.015);
  box(cabinRoom, -0.15, 1.94, 3.05, 0.15, 2, 3.35, "t", { solid: false });
  box(cabinRoom, -0.12, 1.64, 3.08, 0.12, 1.94, 3.32, "l", { solid: false });
  box(cabinRoom, -0.14, 1.58, 3.06, 0.14, 1.64, 3.34, "t", { solid: false });
  box(cabinRoom, 1.35, 0, 0.9, 2.2, 0.42, 2.9, "o", { tex: (x, y, z) => (Math.abs(y - 0.21) < 0.015 || Math.abs(z - 1.9) < 0.015 ? "-" : null) });
  box(cabinRoom, 1.4, 0.42, 0.95, 2.2, 0.58, 2.85, "r");
  box(cabinRoom, 1.5, 0.58, 2.4, 2.15, 0.7, 2.8, "s");
  box(cabinRoom, 1.35, 0.42, 0.9, 1.4, 0.72, 2.9, "o");
  for (const z of [0.9, 2.84]) box(cabinRoom, 1.35, 0.42, z, 2.2, 0.95, z + 0.06, "o");
  box(cabinRoom, -2.15, 0, 1, -1.45, 0.5, 1.6, "o", {
    tex: (x, y, z) => (Math.abs(z - 1.12) < 0.03 || Math.abs(z - 1.48) < 0.03 ? "t" : Math.abs(y - 0.38) < 0.015 ? "-" : null) });
}
buildCabin();
// Each room's door is at its origin and the room runs along +z. `door` is the outside threshold [x, z, the direction
// you walk along z to enter]; `exit` puts you back outside [x, z, yaw], facing away from the door. `lights` light the
// room without shadow rays: x, y, z, intensity and reach of each (the house's table lamp and hearth fire, the cabin's
// hanging lantern).
const HOUSE = { solids: room, floor: [-2.75, 2.75, 0.25, 5.75], lights: [-2.2, 1.9, 2.9, 0.85, 9, 2.5, 0.35, 4.4, 0.55, 3.2],
  door: [-5, 20.75, 1], exit: [-5, 20.35, Math.PI] };
const CABIN = { solids: cabinRoom, floor: [-1.95, 1.95, 0.25, 4.95], lights: [0, 1.79, 3.2, 0.85, 9], door: [SX, -8.75, -1], exit: [SX, -8.35, 0] };

function roomFloorAt(x, z) {
  const f = interior.floor;
  return x >= f[0] && x <= f[1] && z >= f[2] && z <= f[3] ? 0 : null;
}
function roomBlocked(x, z, fy) {
  return interior.solids.some((s) => walkingSolid(s, fy) && x > walkBound(s.bb, 0) && x < walkBound(s.bb, 3) &&
    z > walkBound(s.bb, 2) && z < walkBound(s.bb, 5));
}
// The room whose outside door the step from (me.x, me.z) to (x, z) walks through, or null.
function doorAhead(x, z) {
  return [HOUSE, CABIN].find(({ door: [dx, dz, dir] }) => Math.abs(x - dx) < 0.42 &&
    dir * (me.z - dz) <= 0 && dir * (z - dz) > 0 && dir * (z - dz) < 0.45) || null;
}
function crossDoor(x, z) {
  const next = !interior ? doorAhead(x, z) : me.z >= 0.35 && z < 0.35 && Math.abs(x) < 0.42 ? null : interior;
  if (next === interior) return false;
  Object.assign(me, next ? { x: 0, z: 0.8, yaw: 0, pitch: 0 } : { x: interior.exit[0], z: interior.exit[1], yaw: interior.exit[2], pitch: 0 });
  interior = next;
  probeMs = -1;
  slow = fast = 0;
  layoutDirty = true;
  doorInputHeld = true;
  walkPath = []; walkTo = jumped = null;
  setMap(0); mapBox = null; MAPCELLS.clear(); LINE.clear();
  moved = dirty = true;
  show(null);
  return true;
}
function movePlayer(x, z, here) {
  if (doorInputHeld) return;
  if (crossDoor(x, z)) return;
  const fy = floorAt(x, z);
  if (fy !== null && Math.abs(fy - here) <= 0.6 && !blocked(x, z, fy)) { me.x = x; me.z = z; }
}
// The room fill and each room's lights share the same warm colour.
function roomLight(x, y, z, nx, ny, nz) {
  const L = interior.lights;
  let warm = 0.28;
  for (let k = 0; k < L.length; k += 5) {
    const lx = L[k] - x, ly = L[k + 1] - y, lz = L[k + 2] - z, d = Math.sqrt(lx * lx + ly * ly + lz * lz);
    warm += L[k + 3] * Math.max(0, 1 - d / L[k + 4]) * (0.35 + 0.65 * Math.max(0, (nx * lx + ny * ly + nz * lz) / d));
  }
  return warm;
}
function castRoom(c, i, odd, dx, dy, dz) {
  hitT = Infinity; hitS = null; SP[c] = null;
  trace(rowWorld, i, cam.x, cam.y, cam.z, dx, dy, dz);
  if (hitS && hitS.tex === roomWindow) {
    // Panes in a side wall face along x, so their stars spread along z.
    const across = Math.abs(hitS.P[hitK]) > 0.5 ? cam.z + dz * hitT : cam.x + dx * hitT;
    const star = roomWindow(across, cam.y + dy * hitT) === "*";
    put(c, star ? "*" : ".", star ? "m5" : "d2", hitS.id * 16 + (hitK >> 2), hitT);
  } else if (hitS && hitS.tex === roomFlame) {
    const [ch, cls] = roomFlame(cam.y + dy * hitT, hitS.bb);
    put(c, ch, cls, hitS.id * 16, hitT);
  } else if (hitS) shadeRoom(c, odd, dx, dy, dz);
  else shadeSky(c, dx, dy, dz);
}
// Shades a room surface like the lit solids outside: warm light, a contact shadow toward the floor, and fog. The room
// has no ship, terrain or blinking lights, and it builds no arrays or strings per cell, so furnished frames stay cheap.
function shadeRoom(c, odd, dx, dy, dz) {
  const s = hitS, k = hitK, t = hitT;
  const nx = k >= 0 ? s.P[k] : hitN[0], ny = k >= 0 ? s.P[k + 1] : hitN[1], nz = k >= 0 ? s.P[k + 2] : hitN[2];
  const x = cam.x + dx * t, y = cam.y + dy * t, z = cam.z + dz * t;
  const tex = s.tex && s.tex(x, y, z, nx, ny, nz), mat = tex && tex !== "-" ? tex[0] : s.mat;
  let ch = "@", cls = "l7";
  if (mat !== "l") {
    const warm = roomLight(x, y, z, nx, ny, nz), lit = warm + 0.06, dim = (tex === "-" ? 0.55 : 1) * (s.dim || 1);
    const ao = ny > 0.7 ? 1 : Math.min(1, 0.55 + 0.5 * y), fog = Math.exp(-t * 0.016);
    const b = (lit * dim * ao * (0.8 + 0.2 * Math.max(0, -(nx * dx + ny * dy + nz * dz)))) * fog + 0.02 * (1 - fog);
    // Keep the bed, chart water, and blue book spines blue under warm room light.
    cls = CLASS[mat][(mat !== "b" && warm / lit > 0.55 && b > 0.2 ? 8 : 0) + Math.min(7, Math.floor(b * 9))];
    ch = glyph(b, odd);
  }
  put(c, ch, cls, (ny > 0.7 ? -1 : 1) * (s.id * 16 + (k >= 0 ? k >> 2 : 12 - k)), t);
}

// ---- Motion state ------------------------------------------------------------------------
let T = 0, bob = 0, roll = 0, rc = 1, rs = 0;
const deckAt = (x) => bob + DECK * rc + rs * (x - SX);
function setGangway() {
  const y0 = deckAt(0.7), y1 = 1.2, dx = 3.1 - 0.7, dy = y1 - y0, l = Math.hypot(dx, dy);
  const nx = -dy / l, ny = dx / l, P = gangway.P;
  P[0] = nx; P[1] = ny; P[3] = nx * 0.7 + ny * y0;
  P[4] = -nx; P[5] = -ny; P[7] = -(nx * 0.7 + ny * (y0 - 0.12));
  gangway.bb[1] = Math.min(y0, y1) - 0.2; gangway.bb[4] = Math.max(y0, y1) + 0.05;
}
// Walkable deck uses the same tapered stations as the hull, inset from the rails.
function shipFloor(x, z) {
  const p = shipProfile(z);
  if (!p || Math.abs(x - SX) > p[0] - 0.25) return null;
  const roof = z >= -14.6 && z < -9 && Math.abs(x - SX) <= 2.1 + (z + 14.6) * 0.08 - 0.25;
  return bob + (roof ? 4.8 : p[1]) * rc + rs * (x - SX);
}
// Walkable areas [x0, x1, z0, z1, height at x]: gangway and dock; elsewhere deck or island.
const FLOORS = [
  ...STERN_STEPS,
  [0.45, 3.1, -1.8, -0.6, (x) => deckAt(0.7) + (1.2 - deckAt(0.7)) * Math.min(1, Math.max(0, (x - 0.7) / 2.4))],
  [3, 7, -16, 14, () => 1.2],
];
function floorAt(x, z) {
  if (interior) return roomFloorAt(x, z);
  const f = FLOORS.find(([x0, x1, z0, z1]) => x >= x0 && x < x1 && z >= z0 && z < z1);
  if (f) return f[4](x, z);
  const deck = shipFloor(x, z);
  if (deck !== null) return deck;
  const y = terrainY(x, z);
  return y > 0.1 ? y : null;
}
const walkBound = (b, k) => b[k] + (k < 3 ? -0.25 : 0.25);
const walkingSolid = (s, fy, lift = 0) => s.solid && s.bb[1] + lift < fy + 1.7 && s.bb[4] + lift > fy + 0.3;
function blocked(x, z, fy) {
  if (interior) return roomBlocked(x, z, fy);
  for (const list of [world, ship]) {
    const lift = list === ship ? bob : 0;
    for (const s of list) {
      const b = s.bb;
      if (walkingSolid(s, fy, lift) && x > walkBound(b, 0) && x < walkBound(b, 3) &&
        z > walkBound(b, 2) && z < walkBound(b, 5)) return true;
    }
  }
  return false;
}

// ---- Tall grass ---------------------------------------------------------------------------
// Grass reads the ground only here: [height, metres outside the nearest way (negative on it), whether that way is
// paved, rise per metre], or null on wet sand, the harbour wall and in the sea. Dry sand above the wash carries
// dune grass.
function grassGround(x, z) {
  const y = terrainY(x, z), e = 0.5;
  if (y < 0.55 || harbourWall(x, y, z)) return null;
  const [way, along, concrete] = roadAt(x, z), road = way - (concrete ? 1.5 : trailHalfWidth(along)), plaza = Math.hypot(x - 5, z - 24.6) - 3.2;
  const slope = Math.hypot(terrainY(x + e, z) - terrainY(x - e, z), terrainY(x, z + e) - terrainY(x, z - e)) / (2 * e);
  return [y, Math.min(road, plaza), concrete || plaza < road, slope];
}
// Chance of a clump: none on paving, few on trails, most along the edges of the ways and on slopes, patches elsewhere.
function grassChance(x, z, edge, paved, slope) {
  if (edge < (paved ? 0.3 : 0)) return paved ? 0 : 0.1;
  const patch = smooth(Math.sin(x * 0.29 + Math.sin(z * 0.21) * 2) * Math.sin(z * 0.33 - x * 0.12) * 2 + 0.3);
  return Math.min(1, 0.06 + 0.8 * patch + 1.2 * Math.exp(-edge * edge) + 3 * slope);
}
// Keep clumps outside solid footprints: walls, hedges, trunks, posts, crates.
const grassFree = (solids, x, y, z) => !solids.some((s) => x > s.bb[0] && x < s.bb[3] && z > s.bb[2] && z < s.bb[5] && walkingSolid(s, y));
// Seeded clumps on a jittered 0.9 m grid, the same on every visit: [x, y, z, height, seed] each.
function plantGrass() {
  const clumps = [], solids = world.filter((s) => s.solid);
  for (let gx = -62; gx < 46; gx += 0.9) {
    for (let gz = -43; gz < 55; gz += 0.9) {
      const x = gx + hash(gx, gz) * 0.9, z = gz + hash(gz, gx) * 0.9, g = grassGround(x, z);
      const p = g ? grassChance(x, z, g[1], g[2], g[3]) : 0;
      if (hash(x * 1.7, z * 2.3) < p && grassFree(solids, x, g[0], z)) clumps.push(x, g[0], z, 0.4 + 0.6 * p * hash(z, x * 1.3), hash(x * 3.3, z));
    }
  }
  return Float32Array.from(clumps);
}
const GRASS = plantGrass();
// Colour classes by brightness: dark roots, green blades and pale moonlit tips.
const grassTones = (mat) => Array.from({ length: 8 }, (_, i) => mat + i);
const GRASS_ROOT = grassTones("M"), GRASS_BLADE = grassTones("g"), GRASS_TIP = grassTones("G"), GP = [0, 0, 0];
// Quantize wind time to limit grass animation changes in a still view.
const swayTime = () => Math.floor(T * 12) / 12;
// Project clumps into the depth buffer, like the rigging.
// Cap their height before cell rounding so near grass does not fill the view.
// Moonlight brightens the blades when the moon is behind you; distance dims them.
function drawGrass() {
  const sway = swayTime(), lit = 0.5 - 0.5 * (cam.f[0] * MOON[0] + cam.f[2] * MOON[2]), cap = rows / 14;
  const tall = rows / (2 * cam.tanV), wide = cols / (2 * cam.tanH); // rows and columns per metre, 1 m away
  const across = WIND.x * cam.r[0] + WIND.z * cam.r[2]; // the part of the wind that blows across the view
  for (let k = 0; k < GRASS.length; k += 5) {
    viewPoint(GRASS[k], GRASS[k + 1], GRASS[k + 2], GP);
    const d = GP[2], h = GRASS[k + 3], s = GRASS[k + 4], full = h * tall / d, rise = Math.min(cap, full);
    if (d < 0.5 || full < 1 || GP[1] < 0 || GP[1] - rise > rows) continue;
    const scale = rise / full, half = 0.35 * wide / d * scale, b = (0.42 + 0.12 * lit) * Math.exp(-d * 0.02);
    if (GP[0] + half < -3 || GP[0] - half > cols + 3) continue;
    const gust = Math.round(1.5 + 1.5 * Math.sin(sway * 1.7 - (GRASS[k] * WIND.x + GRASS[k + 2] * WIND.z) * 0.35 + s * 1.2)) / 3;
    drawTuft(s, rise, half, across * h * (0.03 + 0.15 * gust) * wide / d * scale, b, b + 0.35 * Math.exp(-d / 30));
  }
}
// Blades fan out from a tight root, with the tallest blades in the middle.
// Draw outer blades first so middle blades cover them.
// Wind bends each blade more toward its tip; distant tufts use fewer blades.
function drawTuft(s, rise, half, lean, b, pale) {
  const n = Math.min(7 + 2 * Math.floor(s * 3), 1 + 2 * Math.floor(half * 1.2)), tone = Math.min(7, Math.floor(b * 9));
  const root = GRASS_ROOT[tone], blade = GRASS_BLADE[tone], tip = GRASS_TIP[Math.min(7, Math.floor(pale * 9))];
  for (let k = 0; k < n; k++) {
    const u = n > 1 ? (k & 1 ? 1 : -1) * (1 - 2 * (k >> 1) / (n - 1)) : 0;
    const high = Math.max(1, Math.round(rise * (1 - 0.45 * u * u) * (0.7 + 0.3 * ((s * 13 + k * 0.61) % 1))));
    drawGrassBlade(GP[0] + u * half * 0.25, u * half * 0.75, lean * high / rise, high, root, blade, tip);
  }
}
function drawGrassBlade(foot, fan, bend, high, root, blade, tip) {
  const crown = high > 4 ? high - 2 : high - 1;
  for (let r = 0; r < high; r++) {
    const t = (r + 0.5) / high, slope = (fan + 2 * bend * t) / high;
    ropeCell(Math.floor(foot + fan * t + bend * t * t), Math.floor(GP[1]) - r, GP[2], grassBladeGlyph(slope, t, high), r >= crown ? tip : r ? blade : root);
  }
}
function grassBladeGlyph(slope, t, high) {
  const a = Math.abs(slope);
  if (a >= 0.9) return slope > 0 ? "/" : "\\";
  if (a >= 0.45 && t > 0.6 && high > 3) return slope > 0 ? ")" : "(";
  return "|";
}

const me = { x: 6.5, z: -15, yaw: -0.6, pitch: 0.4 };
const keys = new Set();
const stick = { x: 0, y: 0 };
let moved = false;
let doorInputHeld = false;
function releaseDoorInput() {
  if (!keys.has("f") && !keys.has("b") && !keys.has("l") && !keys.has("r") && !stick.x && !stick.y) doorInputHeld = false;
}

// ---- Ray casting -------------------------------------------------------------------------
let hitT, hitS, hitK;
const hitN = [0, 1, 0], entryN = [0, 1, 0];
// Entry distance of the ray into a bounding box, or Infinity when it misses.
function boxEntry(b, ox, oy, oz, ix, iy, iz) {
  let a = (b[0] - ox) * ix, c = (b[3] - ox) * ix;
  let t0 = Math.min(a, c), t1 = Math.max(a, c);
  a = (b[1] - oy) * iy; c = (b[4] - oy) * iy;
  t0 = Math.max(t0, Math.min(a, c)); t1 = Math.min(t1, Math.max(a, c));
  a = (b[2] - oz) * iz; c = (b[5] - oz) * iz;
  t0 = Math.max(t0, Math.min(a, c)); t1 = Math.min(t1, Math.max(a, c));
  return t1 < 0 || t0 > t1 ? Infinity : t0;
}
// Ray against one convex solid: the last plane it enters before it leaves any plane, or Infinity.
let entryK = -1;
function entry(P, ox, oy, oz, dx, dy, dz) {
  let tn = -Infinity, tf = Infinity;
  for (let i = 0; i < P.length && tn <= tf; i += 4) {
    const den = P[i] * dx + P[i + 1] * dy + P[i + 2] * dz;
    const dist = P[i + 3] - (P[i] * ox + P[i + 1] * oy + P[i + 2] * oz), t = dist / den;
    if (den < 0) { if (t > tn) { tn = t; entryK = i; } } else if (den > 0) tf = Math.min(tf, t);
    else if (dist < 0) tf = -Infinity; // parallel to the plane and outside it
  }
  return tn <= tf && tn > 1e-3 ? tn : Infinity;
}
// Ray against a round column: the side of the cone or one of its caps. Sets entryK (-1 side, -2 top,
// -3 bottom) and entryN (the normal).
function coneEntry(cone, ox, oy, oz, dx, dy, dz) {
  const cx = cone[0], cz = cone[1], a = cone[2], b = cone[3], y0 = cone[4], y1 = cone[5], r0 = cone[6], r1 = cone[7];
  const X = ox - cx, Z = oz - cz, R = a + b * oy, bd = b * dy;
  const A = dx * dx + dz * dz - bd * bd, B = 2 * (X * dx + Z * dz - R * bd), C = X * X + Z * Z - R * R, disc = B * B - 4 * A * C;
  let best = Infinity;
  if (disc >= 0 && Math.abs(A) > 1e-9) {
    const sq = Math.sqrt(disc);
    for (let n = 0; n < 2; n++) {
      const t = (-B + (n ? sq : -sq)) / (2 * A), y = oy + t * dy;
      if (t > 1e-3 && t < best && y >= y0 && y <= y1 && R + t * bd >= 0) {
        const nx = X + t * dx, nz = Z + t * dz, ny = -b * (a + b * y), l = Math.sqrt(nx * nx + ny * ny + nz * nz);
        best = t; entryK = -1; entryN[0] = nx / l; entryN[1] = ny / l; entryN[2] = nz / l;
      }
    }
  }
  for (let n = 0; n < 2 && dy !== 0; n++) {
    const yc = n ? y0 : y1, rr = n ? r0 : r1, t = (yc - oy) / dy, x = X + t * dx, z = Z + t * dz;
    if (t > 1e-3 && t < best && x * x + z * z <= rr * rr) { best = t; entryK = n ? -3 : -2; entryN[0] = 0; entryN[1] = n ? -1 : 1; entryN[2] = 0; }
  }
  return best;
}
const hit = (s, ox, oy, oz, dx, dy, dz) => (s.rail ? railEntry(s, ox, oy, oz, dx, dy, dz) : s.blob ? blobEntry(s.blob, ox, oy, oz, dx, dy, dz) : s.cone ? coneEntry(s.cone, ox, oy, oz, dx, dy, dz) : s.cloth ? clothEntry(s.cloth, ox, oy, oz, dx, dy, dz) : entry(s.P, ox, oy, oz, dx, dy, dz));
// One perforated slab per railing replaces individual posts without filling the open spaces.
function railEntry(s, ox, oy, oz, dx, dy, dz) {
  const t = entry(s.P, ox, oy, oz, dx, dy, dz);
  if (!Number.isFinite(t)) return t;
  const [z0, y0, slope, spacing] = s.rail, z = oz + dz * t - z0;
  const y = oy + dy * t - y0 - slope * z, post = z % spacing;
  return y < 0.06 || y > 0.7 || Math.abs(y - 0.3) < 0.05 || post < 0.05 || post > spacing - 0.05 ? t : Infinity;
}
// Ray against an ellipsoid: solve in the space where it is a unit sphere. Sets entryK -4 and entryN.
function blobEntry(e, ox, oy, oz, dx, dy, dz) {
  const qx = (ox - e[0]) / e[3], qy = (oy - e[1]) / e[4], qz = (oz - e[2]) / e[5], vx = dx / e[3], vy = dy / e[4], vz = dz / e[5];
  const A = vx * vx + vy * vy + vz * vz, B = 2 * (qx * vx + qy * vy + qz * vz), C = qx * qx + qy * qy + qz * qz - 1, disc = B * B - 4 * A * C;
  if (disc < 0) return Infinity;
  const sq = Math.sqrt(disc), t = (-B - sq) / (2 * A) > 1e-3 ? (-B - sq) / (2 * A) : (-B + sq) / (2 * A);
  if (t <= 1e-3) return Infinity;
  const nx = (qx + t * vx) / e[3], ny = (qy + t * vy) / e[4], nz = (qz + t * vz) / e[5], l = Math.sqrt(nx * nx + ny * ny + nz * nz);
  entryK = -4; entryN[0] = nx / l; entryN[1] = ny / l; entryN[2] = nz / l;
  return t;
}
const RAY = new Float64Array(6); // the ray in the cloth's frame: origin u, v, w, then direction u, v, w
const clothGap = (k, t) => RAY[2] + t * RAY[5] - clothDepth(k, RAY[0] + t * RAY[3], RAY[1] + t * RAY[4]);
function clothEntry(k, ox, oy, oz, dx, dy, dz) {
  const qx = ox - k.at[0], qz = oz - k.at[2], u = qx * k.cu + qz * k.su, v = k.at[1] - oy, w = qz * k.cu - qx * k.su;
  const du = dx * k.cu + dz * k.su, dw = dz * k.cu - dx * k.su, iu = 1 / du, iv = -1 / dy, iw = 1 / dw;
  const u0 = (k.u0 - u) * iu, u1 = (k.u1 - u) * iu, v0 = -v * iv, v1 = (k.v1 - v) * iv, w0 = (k.w0 - w) * iw, w1 = (k.w1 - w) * iw;
  const near = Math.max(1e-3, Math.min(u0, u1), Math.min(v0, v1), Math.min(w0, w1));
  const far = Math.min(Math.max(u0, u1), Math.max(v0, v1), Math.max(w0, w1));
  entryK = -1;
  if (!(near < far)) return Infinity;
  RAY[0] = u; RAY[1] = v; RAY[2] = w; RAY[3] = du; RAY[4] = -dy; RAY[5] = dw;
  const m = (near + far) / 2, fa = clothGap(k, near), fm = clothGap(k, m);
  const slope = k.ripple ? k.ripple * ((k.ku + 2.4) * Math.abs(du) + 0.5 * Math.abs(dy))
    : Math.abs(k.belly) * (1.88 * k.ku * Math.abs(du) + 2.6 * k.kv * Math.abs(dy));
  if (Math.abs(dw) >= slope) {
    if (fa === 0 || fm === 0 || (fa <= 0) !== (fm <= 0)) return clothRoot(k, near, fa, m, fm);
    const fb = clothGap(k, far);
    return fb === 0 || (fm <= 0) !== (fb <= 0) ? clothRoot(k, m, fm, far, fb) : Infinity;
  }
  const p = 2.4 * du - 0.5 * dy, a = du * k.ku, b = dy * k.kv;
  const curve = k.ripple ? k.ripple * (2 * Math.abs(a * p) + p * p)
    : Math.abs(k.belly) * (1.88 * a * a + 10.4 * Math.abs(a * b) + 3 * b * b);
  const jump = k.ripple ? 0 : 1.88 * Math.abs(k.belly * a);
  const first = clothSearch(k, near, fa, m, fm, curve, jump);
  return Number.isFinite(first) ? first : clothSearch(k, m, fm, far, clothGap(k, far), curve, jump);
}
function clothSearch(k, a, fa, b, fb, curve, jump) {
  const span = b - a, ua = RAY[0] + a * RAY[3], ub = RAY[0] + b * RAY[3];
  let bends = 0;
  if (jump) {
    const lo = Math.min(ua, ub), hi = Math.max(ua, ub);
    if (lo < -k.half && hi > -k.half) bends += jump;
    if (lo < k.half && hi > k.half) bends += jump;
  }
  const error = curve * span * span / 8 + bends * span / 4;
  if ((fa <= 0) === (fb <= 0) && Math.min(Math.abs(fa), Math.abs(fb)) > error) return Infinity;
  if (fa === 0 && clothInside(k, ua, RAY[1] + a * RAY[4])) return a;
  if ((fa <= 0) !== (fb <= 0) && Math.abs(fb - fa) / span > curve * span + 2 * bends) {
    return clothRoot(k, a, fa, b, fb);
  }
  if (span * (Math.abs(RAY[3]) + Math.abs(RAY[4]) + Math.abs(RAY[5])) < 1e-5) {
    return fa === 0 || fb === 0 || (fa <= 0) !== (fb <= 0) ? clothRoot(k, a, fa, b, fb) : Infinity;
  }
  const m = (a + b) / 2, fm = clothGap(k, m);
  const first = clothSearch(k, a, fa, m, fm, curve, jump);
  return Number.isFinite(first) ? first : clothSearch(k, m, fm, b, fb, curve, jump);
}
function clothRoot(k, a, fa, b, fb) {
  if (fa === 0) return clothInside(k, RAY[0] + a * RAY[3], RAY[1] + a * RAY[4]) ? a : Infinity;
  if (fb === 0) return clothInside(k, RAY[0] + b * RAY[3], RAY[1] + b * RAY[4]) ? b : Infinity;
  const h = (a + b) / 2, fh = clothGap(k, h);
  if ((fa <= 0) === (fh <= 0)) { a = h; fa = fh; } else { b = h; fb = fh; }
  const m = a + (b - a) * fa / (fa - fb), fm = clothGap(k, m);
  const t = (fa <= 0) === (fm <= 0) ? m + (b - m) * fm / (fm - fb) : a + (m - a) * fa / (fa - fm);
  const u = RAY[0] + t * RAY[3], v = RAY[1] + t * RAY[4];
  return clothInside(k, u, v) ? t : Infinity;
}
// Which side of cloth k a ray (dx, dy, dz) meets at (u, v), as face 13 or 14 from the sign of the cloth's normal along
// the ray, so an edge marks where the cloth folds out of sight.
function clothSide(k, u, v, dx, dy, dz) {
  clothSlope(k, u, v);
  const du = SLOPE[0];
  return (-du * k.cu - k.su) * dx + SLOPE[1] * dy + (k.cu - du * k.su) * dz > 0 ? 13 : 14;
}
// Solids come nearest first, so once the nearest possible point of the next one is past the hit, none can come closer.
function trace(list, col, ox, oy, oz, dx, dy, dz) {
  const ix = 1 / dx, iy = 1 / dy, iz = 1 / dz;
  for (const s of list) {
    if (s.closest >= hitT) break;
    if (col < s.i0 || col > s.i1 || boxEntry(s.bb, ox, oy, oz, ix, iy, iz) > hitT) continue;
    const t = hit(s, ox, oy, oz, dx, dy, dz);
    if (t < hitT) { hitT = t; hitK = entryK; hitS = s; if (entryK < 0) { hitN[0] = entryN[0]; hitN[1] = entryN[1]; hitN[2] = entryN[2]; } }
  }
}

// ---- Night lighting ----------------------------------------------------------------------
// Lamps, lit windows, the ship's lanterns, and the beacon light what is near them, falling off
// with distance, and the solids near each light cast its shadows. The moon adds a dim, soft fill; the
// lighthouse beam sweeps the harbor.
let shadows = !touchFirst.matches;
// Solids marked shadow: false (thin raised trim) cast no shadows; their shadows are too fine for the glyph grid.
function casters(list, x, y, z, r) {
  return list.filter(({ bb: b, shadow }) => {
    const ex = Math.max(b[0] - x, 0, x - b[3]), ey = Math.max(b[1] - y, 0, y - b[4]), ez = Math.max(b[2] - z, 0, z - b[5]);
    return shadow !== false && ex + ey + ez > 0 && ex * ex + ey * ey + ez * ez < r * r; // near the light but not around it
  });
}
function lamp(x, y, z, i, r, inShip = false) {
  return { x, y, z, i, r2: r * r, inShip, near: casters(inShip ? ship : world, x, y, z, r), tiles: new Map(), wx: x, wy: y, wz: z };
}
const centre = ({ bb: b }) => [(b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2];
const LIGHTS = [
  ...world.filter((s) => s.mat === "l" && s !== beacon && s !== antennaLamp).map((s) => lamp(...centre(s), 1, 10)),
  ...ship.filter((s) => s.mat === "l").map((s) => lamp(...centre(s), 0.9, 9, true)),
  lamp(-7.4, 3, 20.8, 0.22, 2.3), lamp(-2.6, 3, 20.8, 0.22, 2.3), lamp(-0.8, 3, 23.2, 0.22, 2.3), lamp(-0.8, 3, 25.7, 0.22, 2.3),
  lamp(...centre(beacon), 1.1, 16),
];
const BEAM = { x: -36, y: 13.8, z: -24, reach: 95 };
// Lights reaching each 8 m tile of the ground plan, so a point checks only the few lamps near it.
const TILE = 8, LIGHTGRID = new Map();
for (const L of LIGHTS) {
  const r = Math.sqrt(L.r2) + 1;
  for (let i = Math.floor((L.x - r) / TILE); i <= Math.floor((L.x + r) / TILE); i++) {
    for (let k = Math.floor((L.z - r) / TILE); k <= Math.floor((L.z + r) / TILE); k++) {
      const key = i * 1000 + k;
      if (!LIGHTGRID.has(key)) LIGHTGRID.set(key, []);
      LIGHTGRID.get(key).push(L);
    }
  }
}
const NONE = [];
// Moves the ship's lights with the ship and turns the beam, once per frame.
function moveLights() {
  for (const L of LIGHTS) {
    if (!L.inShip) continue;
    const lx = L.x - SX;
    L.wx = SX + rc * lx - rs * L.y; L.wy = rs * lx + rc * L.y + bob; L.wz = L.z;
  }
  BEAM.a = T * 0.5; BEAM.dx = Math.cos(BEAM.a); BEAM.dz = Math.sin(BEAM.a);
}
// Light reaching a point with normal n: [brightness, share of it from lamps].
function lightAt(x, y, z, nx, ny, nz) {
  const moon = 0.035 + 0.17 * Math.max(0, nx * MOON[0] + ny * MOON[1] + nz * MOON[2]) + 0.04 * Math.max(0, ny);
  let warm = 0;
  for (const L of LIGHTGRID.get(Math.floor(x / TILE) * 1000 + Math.floor(z / TILE)) || NONE) {
    const lx = L.wx - x, ly = L.wy - y, lz = L.wz - z, d2 = lx * lx + ly * ly + lz * lz;
    if (d2 > L.r2) continue;
    const d = Math.sqrt(d2), ndl = (nx * lx + ny * ly + nz * lz) / d, f = 1 - d2 / L.r2;
    const add = ndl > 0 ? L.i * f * f * (0.35 + 0.65 * ndl) : 0;
    if (add > 0.02 && !(shadows && shadowed(L, x + nx * 0.03, y + ny * 0.03, z + nz * 0.03, lx / d, ly / d, lz / d, d))) warm += add;
  }
  const beam = beamOn(x, z) * Math.max(0.3, ny + 0.5);
  return [moon + warm + beam, (warm + beam) / (moon + warm + beam)];
}
// Is the way from a point to a light blocked by one of the solids near the light? Every solid is convex and the light
// faces the point, so the solid being shaded (hitS) cannot block its own light.
function shadowed(L, ox, oy, oz, dx, dy, dz, dist) {
  if (L.inShip) {
    const x = ox - SX, y = oy - bob;
    [ox, oy, dx, dy] = [rc * x + rs * y + SX, -rs * x + rc * y, rc * dx + rs * dy, -rs * dx + rc * dy];
  }
  const ix = 1 / dx, iy = 1 / dy, iz = 1 / dz;
  for (const s of tileCasters(L, ox, oz)) if (s !== hitS && boxEntry(s.bb, ox, oy, oz, ix, iy, iz) < dist && hit(s, ox, oy, oz, dx, dy, dz) < dist) return true;
  return false;
}
// The light's casters that can stand between it and any point above or below the 1 m plan tile at (x, z): those whose box
// meets the plan rectangle spanning the tile and the light. Boxes already allow for swaying and floating.
function tileCasters(L, x, z) {
  const tx = Math.floor(x), tz = Math.floor(z), key = tx * 4096 + tz;
  let list = L.tiles.get(key);
  if (!list) {
    const x0 = Math.min(tx, L.x), x1 = Math.max(tx + 1, L.x), z0 = Math.min(tz, L.z), z1 = Math.max(tz + 1, L.z);
    list = L.near.filter(({ bb: b }) => b[0] <= x1 && b[3] >= x0 && b[2] <= z1 && b[5] >= z0);
    L.tiles.set(key, list);
  }
  return list;
}
// Brightness of the sweeping beam where it falls on the ground at (x, z).
function beamOn(x, z) {
  const hx = x - BEAM.x, hz = z - BEAM.z, d = Math.sqrt(hx * hx + hz * hz);
  if (d < 3 || d > BEAM.reach) return 0;
  const off = Math.abs(hx * BEAM.dz - hz * BEAM.dx) / d, ahead = hx * BEAM.dx + hz * BEAM.dz;
  return ahead > 0 && off < 0.07 ? 0.8 * (1 - off / 0.07) * (1 - d / BEAM.reach) : 0;
}

// Density ramp of shading glyphs, from empty to solid; letters stay for labels and signs only.
const RAMP = " .`',:;~-=+*#%@▒▓█";
// One sparse 8x8 tile keeps intro drawing cheap; frames only shift these cached glyphs.
const INTRO_NOISE = Array.from({ length: 64 }, (_, c) => {
  const seed = (c * 37) % 97;
  return seed % 3 ? " " : RAMP[1 + seed % (RAMP.length - 1)];
});
const RANGE = { lighthouse: 400, nest: 30, office: 40, antenna: 50, containers: 40, lifeboat: 25, tender: 25 };
const MOON = (() => { const v = [0.2, 0.3, 0.93], l = Math.hypot(...v); return v.map((c) => c / l); })();
// Objects whose feature is not in the page's list are scenery.
for (const s of [...world, ...ship]) if (s.spot && !spots[s.spot]) s.spot = null;
const anchors = {};
for (const [list, lift] of [[world, 0], [ship, 1]]) {
  for (const s of list) {
    if (!s.spot || s.anchor === false) continue;
    const b = s.bb, a = (anchors[s.spot] ||= { x: 0, y: 0, z: 0, n: 0, r: 0, ship: lift });
    a.x += (b[0] + b[3]) / 2; a.y += (b[1] + b[4]) / 2; a.z += (b[2] + b[5]) / 2; a.n++;
    a.r = Math.max(a.r, (b[3] - b[0]) / 2, (b[5] - b[2]) / 2, (b[4] - b[1]) / 3);
    if (s.post) (a.posts ||= []).push({ x: (b[0] + b[3]) / 2, y: b[4], z: (b[2] + b[5]) / 2 });
  }
}
for (const a of Object.values(anchors)) {
  a.x /= a.n; a.y /= a.n; a.z /= a.n;
  if (a.posts) a.post = {
    x: a.posts.reduce((n, p) => n + p.x, 0) / a.posts.length,
    y: a.posts.reduce((n, p) => n + p.y, 0) / a.posts.length,
    z: a.posts.reduce((n, p) => n + p.z, 0) / a.posts.length
  };
}

let cols = 0, rows = 0, cellW = 8, cellH = 13, scale = 1, target = null, padX = 0, padY = 0, aspect = 1, viewW = 0, viewH = 0;
const safe = { left: 0, right: 0, top: 0, bottom: 0 };
const MONO = getComputedStyle(document.documentElement).getPropertyValue("--mono");
const BASE = { "": "#5c6a88", k: "#e9eefb", w: "#3f78b8", d: "#22406a", m: "#a9c8f0", o: "#dba66b", s: "#efe6cf",
  t: "#a3adc2", l: "#ffd479", r: "#e0705f", b: "#62a8e0", f: "#3a4562", h: "#7ee0c3", g: "#6fbf73", y: "#e3d3a3", n: "#9b8a62",
  G: "#a5d36e", M: "#4f8a4a", p: "#17171c" };
// Each colour in four tiers for the night lighting: dark, dim, bright, and warmed by lamplight.
const mix = (a, b, f) => "#" + [1, 3, 5].map((i) => Math.round(parseInt(a.slice(i, i + 2), 16) * (1 - f) + parseInt(b.slice(i, i + 2), 16) * f).toString(16).padStart(2, "0")).join("");
const COLORS = {};
for (const [k, c] of Object.entries(BASE)) {
  Object.assign(COLORS, { [k]: c, [k + "w"]: mix(c, "#ffd479", 0.45) });
  // Eight levels from near black to full colour (and a little past it for the brightest), plus warm ones.
  for (let i = 0; i < 8; i++) {
    const lv = i < 7 ? mix("#060a14", c, Math.min(1, 0.12 + (i + 1) * 0.15)) : mix(c, "#ffffff", 0.25);
    Object.assign(COLORS, { [k + i]: lv, [k + "w" + i]: mix(lv, "#ffd479", 0.45) });
  }
}
// Colour class names per material: levels 0 to 7, then the same levels warmed, so room shading builds no strings.
const CLASS = {};
for (const k of Object.keys(BASE)) CLASS[k] = Array.from({ length: 16 }, (_, i) => k + (i > 7 ? "w" : "") + (i & 7));
function measure() {
  // Phones and tablets draw at most 2 device pixels per CSS pixel: a 3x canvas costs more memory than it shows.
  // Cap the backing-store area, not each dimension; large high-DPR windows otherwise exceed browser canvas limits.
  const w = stage.clientWidth, h = stage.clientHeight;
  dpr = Math.min(touchFirst.matches ? 2 : Infinity, devicePixelRatio || 1, Math.sqrt(4096 * 4096 / (w * h)));
  // Reset the backing store only for a real size change, immediately before drawing; flooring keeps the cap.
  if (canvas.width !== Math.floor(w * dpr)) canvas.width = Math.floor(w * dpr);
  if (canvas.height !== Math.floor(h * dpr)) canvas.height = Math.floor(h * dpr);
  const px = Math.max(6.5, Math.min(11, innerWidth * 0.0068)) * (interior ? scale : 1);
  aspect = w / h;
  viewW = w; viewH = h;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = BACKGROUND; ctx.fillRect(0, 0, canvas.width / dpr, canvas.height / dpr);
  ctx.font = `${px}px ${MONO}`;
  ctx.textBaseline = "top";
  cellW = ctx.measureText("M").width; cellH = px;
  cols = Math.max(20, Math.floor(w / cellW));
  rows = Math.max(12, Math.floor(h / cellH));
  padX = (w - cols * cellW) / 2; padY = (h - rows * cellH) / 2;
  const style = getComputedStyle(stage);
  for (const edge of Object.keys(safe)) safe[edge] = parseFloat(style.getPropertyValue(`--safe-${edge}`)) || 0;
  signWidth = 0;
  G = new Array(cols * rows); C = new Array(cols * rows);
  ID = new Int32Array(cols * rows); D = new Float32Array(cols * rows); SP = new Array(cols * rows);
  DG = new Array(cols * rows); DC = new Array(cols * rows);
  dirty = true; // Grid measurement clears the canvas, including an idle room's last frame.
}

// Per-cell glyph, colour class, surface id (solid and face) and depth; the edge pass reads them.
let G, C, ID, D, SP;
const cam = {};
function render() {
  const tanV = 0.62, tanH = tanV * aspect;
  const cy = Math.cos(me.yaw), sy = Math.sin(me.yaw), cp = Math.cos(me.pitch), sp = Math.sin(me.pitch);
  const fx = sy * cp, fy = sp, fz = cy * cp, rx = cy, rz = -sy, ux = -sp * sy, uy = cp, uz = -sp * cy;
  Object.assign(cam, { x: me.x, y: me.eye, z: me.z, f: [fx, fy, fz], r: [rx, 0, rz], u: [ux, uy, uz], tanH, tanV });
  // Camera origin in the ship frame (rotate by -roll about the ship's long axis, after the bob).
  cam.lx = rc * (me.x - SX) + rs * (me.eye - bob) + SX; cam.ly = -rs * (me.x - SX) + rc * (me.eye - bob);
  gatherClouds(performance.now() / 100);
  const scenery = interior ? interior.solids : world, vessel = interior ? NONE : ship;
  const seenWorld = cull(scenery, false), seenShip = cull(vessel, true);
  for (let j = 0; j < rows; j++) castRow(j, seenWorld, seenShip);
  if (!interior) {
    drawGrass();
    drawRigging();
    drawPennants();
    gulls();
  }
  const mid = (rows >> 1) * cols + (cols >> 1);
  const spot = SP[mid], looked = spot && D[mid] < (RANGE[spot] || 12);
  show(moved ? jumped || (looked ? spot : nearby()) : null);
  minimap();
  labelTarget(spot, looked);
  draw(mid);
}
function labelTarget(spot, looked) {
  // Seat posted signs on their world-space support tops, not the aimed surface.
  const a = target && anchors[target], post = !interior && a?.post;
  const tops = post && a.posts.map(p => project(p, Math.floor));
  const at = post ? project(post, Math.floor) : looked && spot === target ? [cols >> 1, rows >> 1] : a && project(a);
  const span = at && tops && tops.every(Boolean) ? Math.max(...tops.map(p => Math.abs(p[0] - at[0]))) * 2 + 3 : 0;
  if (span) at[1] = Math.max(...tops.map(p => p[1]));
  label(at, span);
}
// Each tile of one row by TILE_W columns keeps only the solids whose screen rectangle reaches it.
function castRow(j, seenWorld, seenShip) {
  const [fx, fy, fz] = cam.f, [rx, , rz] = cam.r, [ux, uy, uz] = cam.u;
  const v = (1 - (2 * j + 1) / rows) * cam.tanV;
  const inRowWorld = seenWorld.filter((s) => s.j0 <= j && j <= s.j1), inRowShip = seenShip.filter((s) => s.j0 <= j && j <= s.j1);
  for (let a = 0, c = j * cols; a < cols; a += TILE_W) {
    const b = a + TILE_W - 1;
    rowWorld = inRowWorld.filter((s) => s.i0 <= b && a <= s.i1); rowShip = inRowShip.filter((s) => s.i0 <= b && a <= s.i1);
    for (let i = a; i <= b && i < cols; i++, c++) {
      // Cells behind the noise are not visible yet; cast only the live scene revealed by the sweep.
      if (introProgress < 1 && introDistance(i, j) > 0) {
        put(c, " ", "f", 0, Infinity); SP[c] = null;
        continue;
      }
      const h = ((2 * i + 1) / cols - 1) * cam.tanH;
      const dx = fx + rx * h + ux * v, dy = fy + uy * v, dz = fz + rz * h + uz * v, n = Math.sqrt(dx * dx + dy * dy + dz * dz);
      cast(c, i, (i + j) & 1, dx / n, dy / n, dz / n);
    }
  }
}

// Screen rectangle of each solid's bounding box this frame, so a ray only tests solids that can cover its cell,
// and the solids in view, nearest first by the distance from the camera to their box.
let rowWorld = [], rowShip = []; // the solids of the screen tile being cast
const TILE_W = 8;
const boxView = new Float64Array(24), NEAR = 0.01; // per box corner: right and up offsets from the camera, and depth
const rect = [0, 0, 0, 0]; // screen columns and rows a box covers: i0, i1, j0, j1
// Grows `rect` by a point `a` right, `u` up and `d` ahead of the camera.
function grow(a, u, d) {
  const si = (a / d / cam.tanH + 1) * cols / 2, sj = (1 - u / d / cam.tanV) * rows / 2;
  rect[0] = Math.min(rect[0], si); rect[1] = Math.max(rect[1], si); rect[2] = Math.min(rect[2], sj); rect[3] = Math.max(rect[3], sj);
}
// Puts the corners of box b in boxView and grows `rect` by those in front; returns how many are behind the near plane.
function viewCorners(b, inShip) {
  const [f0, f1, f2] = cam.f, [r0, , r2] = cam.r, [u0, u1, u2] = cam.u;
  let behind = 0;
  for (let k = 0; k < 8; k++) {
    let x = k & 1 ? b[3] : b[0], y = k & 2 ? b[4] : b[1];
    const z = k & 4 ? b[5] : b[2];
    if (inShip) { const lx = x - SX; x = SX + rc * lx - rs * y; y = rs * lx + rc * y + bob; }
    const px = x - cam.x, py = y - cam.y, pz = z - cam.z, d = px * f0 + py * f1 + pz * f2;
    boxView[k * 3] = px * r0 + pz * r2; boxView[k * 3 + 1] = px * u0 + py * u1 + pz * u2; boxView[k * 3 + 2] = d;
    if (d < NEAR) behind++;
    else grow(boxView[k * 3], boxView[k * 3 + 1], d);
  }
  return behind;
}
// A box partly behind you: the box edges that cross the near plane bound the rest. A box at least 0.2 m away has
// nothing on screen closer than NEAR in depth, so the clipped box covers every cell it can.
function growClipped() {
  for (let k = 0; k < 8; k++) {
    for (let bit = 1; bit < 8; bit <<= 1) {
      const n = k | bit, dk = boxView[k * 3 + 2], dn = boxView[n * 3 + 2], f = (NEAR - dk) / (dn - dk);
      if (n !== k && (dk < NEAR) !== (dn < NEAR)) grow(boxView[k * 3] + f * (boxView[n * 3] - boxView[k * 3]), boxView[k * 3 + 1] + f * (boxView[n * 3 + 1] - boxView[k * 3 + 1]), NEAR);
    }
  }
}
function cull(list, inShip) {
  const ox = inShip ? cam.lx : cam.x, oy = inShip ? cam.ly : cam.y, oz = cam.z, seen = [];
  for (const s of list) {
    const b = s.bb;
    const ex = Math.max(b[0] - ox, 0, ox - b[3]), ey = Math.max(b[1] - oy, 0, oy - b[4]), ez = Math.max(b[2] - oz, 0, oz - b[5]);
    s.closest = Math.sqrt(ex * ex + ey * ey + ez * ez);
    rect[0] = rect[2] = Infinity; rect[1] = rect[3] = -Infinity;
    const behind = viewCorners(b, inShip);
    if (behind === 8) continue; // wholly behind you
    if (s.closest < 0.2) { s.i0 = s.j0 = -1; s.i1 = cols; s.j1 = rows; } // around you: test everywhere
    else {
      if (behind) growClipped();
      s.i0 = Math.floor(rect[0]) - 1; s.i1 = Math.ceil(rect[1]) + 1; s.j0 = Math.floor(rect[2]) - 1; s.j1 = Math.ceil(rect[3]) + 1;
    }
    if (s.i1 < 0 || s.i0 >= cols || s.j1 < 0 || s.j0 >= rows) continue; // beside, above or below the view
    seen.push(s);
  }
  return seen.sort((a, c) => a.closest - c.closest);
}

// A few gulls circle over the harbor, drawn only where they are against the sky.
function gulls() {
  for (let g = 0; g < 5; g++) {
    const a = T * 0.22 + g * 1.3, r = 10 + g * 4;
    const p = project({ x: Math.cos(a) * r - 4, y: 13 + g * 1.6 + Math.sin(T + g), z: 6 + Math.sin(a) * r });
    const c = p && p[0] >= 0 && p[0] < cols && p[1] >= 0 && p[1] < rows ? p[1] * cols + p[0] : -1;
    if (c >= 0 && ID[c] === 0) { G[c] = "^"; C[c] = "k"; }
  }
}

// Screen cell of an anchor (possibly off screen), or null when it is behind you.
function project(a, snap = Math.round) {
  const p = [a.x - cam.x, a.y + (a.ship ? bob : 0) - cam.y, a.z - cam.z];
  const dot = (v) => v[0] * p[0] + v[1] * p[1] + v[2] * p[2], z = dot(cam.f);
  if (z < 0.3) return null;
  return [snap(((dot(cam.r) / z / cam.tanH + 1) / 2) * cols), snap(((1 - dot(cam.u) / z / cam.tanV) / 2) * rows)];
}

// Signs use scene cells.
const LINE = new Map();
let signBox = null, signRows = [], signLinks = [], signWidth = "", signInset = 2;
function signLayout(width, mode, available) {
  const key = `${width}/${mode}/${available}`;
  if (key === signWidth) return;
  signWidth = key;
  signInset = mode ? 1 : 2;
  signRows = [];
  signLinks = [];
  const wrap = (text, cls) => {
    while (text.length > width) {
      const space = text.lastIndexOf(" ", width);
      const end = space > 0 ? space : width;
      signRows.push([text.slice(0, end), cls]);
      text = text.slice(end).trimStart();
    }
    signRows.push([text, cls]);
  };
  const short = (text) => text.length > width ? text.slice(0, width - 1) + "…" : text;
  const links = [...card.querySelectorAll("a")];
  const body = mode < 3 || available >= links.length + 4;
  wrap(mode >= 2 ? short(card.querySelector("h3").textContent) : card.querySelector("h3").textContent, "l");
  if (body) wrap(mode >= 2 ? short(card.querySelector("p").textContent) : card.querySelector("p").textContent, "k");
  if (touchFirst.matches) {
    signRows.push(["", "t"]);
    const texts = links.map((a) => `[${a.textContent}]`);
    const inline = texts.join(" ").length <= width;
    // A stacked link row is at least 12px tall; one blank row makes a 24px target.
    const rowHeight = inline ? 1 : Math.max(1, 12 / cellH);
    const height = inline ? Math.ceil(44 / cellH) : rowHeight * 2;
    let left = signInset;
    links.forEach((a, n) => {
      const text = short(texts[n]);
      const row = signRows.length + (inline ? 0 : n * height + (rowHeight - 1) / 2);
      signLinks.push({ row, start: row - (height - 1) / 2, height, left, width: text.length, text, a });
      left = inline ? left + text.length + 1 : signInset;
    });
    return;
  }
  if (!mode) signRows.push(["", "t"]);
  for (const a of links) {
    const start = signRows.length;
    wrap(mode === 3 ? short(`[${a.textContent}]`) : `[${a.textContent}]`, "h");
    const height = signRows.length - start;
    signLinks.push({ start, height, a });
  }
}
function label(at, span = 0) {
  LINE.clear();
  signBox = null;
  card.hidden = mapMode === 2;
  if (card.hidden || !card.firstChild) return;
  const {top, right, bottom, left} = safe;
  const i0 = Math.max(1, Math.ceil((left - padX) / cellW));
  const i1 = Math.min(cols - 1, Math.floor((stage.clientWidth - right - padX) / cellW));
  const j0 = Math.max(1, Math.ceil((top - padY) / cellH));
  const j1 = Math.min(rows - 1, Math.floor((stage.clientHeight - bottom - padY) / cellH));
  const controls = pad.offsetParent ? pad.getBoundingClientRect() : null;
  const padLeft = controls ? Math.floor((controls.left - 12 - padX) / cellW) : i1;
  const padTop = controls ? Math.floor((controls.top - 12 - padY) / cellH) : j1;
  const below = mapBox ? Math.max(j0, mapBox.oj + mapBox.h + 1) : j0;
  const side = Math.min(i1, mapBox ? mapBox.oi - 1 : i1, padLeft);
  const anchor = at && [Math.max(i0, Math.min(i1 - 1, at[0])), Math.max(j0, Math.min(j1 - 1, at[1]))];
  const areas = [
    [i0, below, i1, Math.min(j1, padTop)],
    [i0, below, Math.min(i1, padLeft), j1],
    [i0, j0, side, j1]
  ];
  if (span) {
    const obstacles = [];
    if (mapBox) obstacles.push([mapBox.oi - 1, mapBox.oj - 1, mapBox.oi + mapBox.w + 1, mapBox.oj + mapBox.h + 1]);
    if (controls) obstacles.push([padLeft, padTop, Math.ceil((controls.right + 12 - padX) / cellW), Math.ceil((controls.bottom + 12 - padY) / cellH)]);
    signBox = signPlace(at, [[i0, j0, i1, j1]], span, obstacles);
  }
  signBox ||= signPlace(anchor, areas);
  if (!signBox) {
    const clearLeft = controls ? Math.max(i0, Math.ceil((controls.right + 12 - padX) / cellW)) : i0;
    signBox = signFit(anchor, clearLeft, j0, i1, j1, 3);
  }
  if (signBox && anchor && !signBox.seated) signLeader(...anchor);
}
function signPlace(at, areas, span = 0, obstacles = []) {
  for (let mode = 0; mode < 3; mode++) {
    for (const area of areas) {
      const fit = signFit(at, ...area, mode, span, obstacles);
      if (fit) return fit;
    }
  }
  return null;
}
function signFit(at, i0, j0, i1, j1, mode = 0, span = 0, obstacles = []) {
  const width = Math.min(52, i1 - i0 - (mode ? 2 : 4));
  if (width < 1 || j1 <= j0) return null;
  signLayout(width, mode, j1 - j0);
  const w = Math.max(span, ...signRows.map(([text]) => text.length + signInset * 2),
    ...signLinks.map((link) => (link.left || signInset) + (link.width || 0) + signInset));
  const h = Math.ceil(Math.max(signRows.length, ...signLinks.map((link) => link.row === undefined ? link.start + link.height : link.row + 1))) + 2;
  const hitTop = Math.min(0, ...signLinks.map((link) => link.start + 1));
  const hitBottom = Math.max(h, ...signLinks.map((link) => link.start + link.height + 1));
  if (hitBottom - hitTop > j1 - j0) return null;
  if (span) return seatBoard(at, w, h, hitTop, hitBottom, i0, j0, i1, j1, obstacles);
  const [ai, aj] = at || [i0, j0];
  const i = at ? ai + 4 + w > i1 ? ai - 4 - w : ai + 4 : i0;
  const j = at ? aj - h - 2 < j0 ? aj + 2 : aj - h - 2 : j0;
  return { i: Math.max(i0, Math.min(i1 - w, i)), j: Math.max(j0 - hitTop, Math.min(j1 - hitBottom, j)), w, h, overlay: mode === 3, seated: false };
}
function seatBoard(at, w, h, hitTop, hitBottom, i0, j0, i1, j1, obstacles) {
  const i = at[0] - Math.floor(w / 2), j = at[1] - h + 1;
  if (i < i0 || i + w > i1 || j + hitTop < j0 || j + hitBottom > j1) return null;
  if (obstacles.some(([x0, y0, x1, y1]) => i < x1 && i + w > x0 && j + hitTop < y1 && j + hitBottom > y0)) return null;
  return { i, j, w, h, overlay: false, seated: true };
}
function signLeader(ai, aj) {
  const { i, j, w, h } = signBox;
  // Leader from the object to the nearest frame cell.
  const ei = Math.max(i, Math.min(i + w - 1, ai)), ej = Math.max(j, Math.min(j + h - 1, aj));
  let x = ai, y = aj;
  const dx = Math.abs(ei - x), dy = Math.abs(ej - y), sx = Math.sign(ei - x), sy = Math.sign(ej - y);
  LINE.set(y * cols + x, "*");
  for (let err = dx - dy, n = Math.max(dx, dy); n > 1; n--) {
    const e2 = 2 * err, mx = e2 > -dy, my = e2 < dx;
    if (mx) { err -= dy; x += sx; }
    if (my) { err += dx; y += sy; }
    LINE.set(y * cols + x, mx && my ? (sx === sy ? "\\" : "/") : mx ? "-" : "|");
  }
}
function signHit(x, y) {
  if (!signBox) return null;
  const r = canvas.getBoundingClientRect();
  const i = (x - r.left - padX) / cellW - signBox.i;
  const j = (y - r.top - padY) / cellH - signBox.j - 1;
  if (i < 1 || i >= signBox.w - 1) return null;
  return signLinks.find((link) => j >= link.start && j < link.start + link.height
    && (link.left === undefined || i >= link.left && i < link.left + link.width))?.a || null;
}

// ---- Mini map: the island in text, every point of interest, and you; M picks, M again fills the screen.
const ORDER = Object.keys(spots).filter((id) => anchors[id]);
if (ORDER.length < Object.keys(spots).length) console.warn("harbor: no scene object for", Object.keys(spots).filter((id) => !anchors[id]).join(", "));
const WORLD = { x0: -62, x1: 48, z0: -44, z1: 56 };
const MAPCELLS = new Map();
let mapMode = 0, pick = 0, jumped = null, mapBox = null; // mapMode: 0 idle, 1 picking, 2 full screen
function minimap() {
  MAPCELLS.clear();
  if (interior) { mapBox = null; return; }
  const left = Math.max(1, Math.ceil((safe.left - padX) / cellW)), right = Math.max(1, Math.ceil((safe.right - padX) / cellW));
  const top = Math.max(1, Math.ceil((safe.top - padY) / cellH)), bottom = Math.max(1, Math.ceil((safe.bottom - padY) / cellH));
  const full = mapMode === 2, w = full ? cols - left - right : Math.min(30, cols - left - right), h = full ? rows - top - bottom : Math.min(15, rows - top - bottom);
  mapBox = { oi: full ? left : cols - w - right, oj: top, w, h, iw: w - 2, ih: h - 3 };
  mapFrame();
  mapTerrain();
  mapMarks();
}
// Puts a glyph at (i, j) of the map box, frame included.
const mapPut = (i, j, ch, cls) => MAPCELLS.set((mapBox.oj + j) * cols + mapBox.oi + i, [ch, cls]);
function mapFrame() {
  const { w, h, iw } = mapBox, full = mapMode === 2;
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) mapPut(i, j, j === 0 || j === h - 1 ? "-" : i === 0 || i === w - 1 ? "|" : " ", "t");
  const tip = mapMode ? `< ${spots[ORDER[pick]].title} > Enter` : touchFirst.matches ? "tap: map" : "M: map";
  [...(full ? tip + "   M or Esc closes" : tip).slice(0, iw)].forEach((ch, i) => mapPut(i + 1, h - 2, ch, "h"));
  if (touchFirst.matches) mapPut(w - 2, 0, full ? "x" : "+", "h");
}
// The island seen from above: plateau with roads and grass, beach and shallow-water bands, deep sea.
function mapTerrain() {
  for (let j = 0; j < mapBox.ih; j++) {
    for (let i = 0; i < mapBox.iw; i++) {
      const [x, z] = fromMap(i + 0.5, j + 0.5), y = terrainY(x, z);
      let cell = [(i + j) % 6 ? " " : "~", "d"];
      if (y > 1.12) cell = roadAt(x, z)[0] < 1.4 || Math.hypot(x - 5, z - 24.6) < 3.2 ? ["+", "s"] : [",", "g"];
      else if (y > 0) cell = [".", "y"];
      else if (y > -1.2) cell = ["~", "w"];
      mapPut(i + 1, j + 1, ...cell);
    }
  }
}
// Every landmark at its true footprint: buildings and boxes, round things, canopies, rocks, the dock, boats and
// the ship with its deck details; then the points of interest, their names on the big map, and you.
function mapMarks() {
  for (const s of world) footprint(s, s.mat === "l" ? "l" : s.mat);
  for (const s of ship) footprint(s, s.mat === "l" ? "l" : "o");
  const f = toMap(5, 24.6);
  if (mapInside(f)) mapPut(f[0] + 1, f[1] + 1, "O", "w");
  ORDER.forEach(mapPoint);
  if (mapMode === 2) mapLabels();
  const p = toMap(me.x, me.z);
  if (mapInside(p)) mapPut(p[0] + 1, p[1] + 1, "^>v<"[Math.round(((me.yaw % 6.283) + 6.283) / 1.5708) % 4], "k");
}
const mapInside = ([i, j]) => i >= 0 && i < mapBox.iw && j >= 0 && j < mapBox.ih;
function footprint(s, cls) {
  const b = s.bb;
  if (s.thin || b[3] - b[0] > 40 || b[4] < 0.5) return;
  const [i0, j0] = toMap(b[0], b[5]), [i1, j1] = toMap(b[3], b[2]);
  const ch = s.blob ? (s.mat === "t" ? "@" : "%") : s.cone ? "@" : s.mat === "o" ? "=" : "#";
  for (let j = Math.max(0, j0); j <= Math.min(mapBox.ih - 1, j1); j++) {
    for (let i = Math.max(0, i0); i <= Math.min(mapBox.iw - 1, i1); i++) {
      if (s.hull && !mapHullCell(i, j)) continue;
      mapPut(i + 1, j + 1, ch, cls);
    }
  }
}
function mapHullCell(i, j) {
  const [x, z] = fromMap(i + 0.5, j + 0.5), p = shipProfile(z);
  return p && Math.abs(x - SX) <= p[0];
}
function mapPoint(id, n) {
  const p = toMap(anchors[id].x, anchors[id].z), picked = mapMode && n === pick;
  if (mapInside(p)) mapPut(p[0] + 1, p[1] + 1, picked ? "@" : "*", picked ? "h" : "l");
}
// Names on the big map, right of their point, else left of it, else left out where the ship crowds them.
function mapLabels() {
  const taken = new Set(ORDER.map((id) => toMap(anchors[id].x, anchors[id].z).join()));
  const f = toMap(5, 24.6);
  taken.add(f.join());
  ORDER.forEach((id, n) => {
    const p = toMap(anchors[id].x, anchors[id].z), text = spots[id].title.slice(0, 16);
    const free = (i0) => i0 >= 0 && i0 + text.length < mapBox.iw && [...text].every((_, k) => !taken.has(`${i0 + k},${p[1]}`));
    const places = [p[0] + 2, p[0] - 1 - text.length];
    if (p[1] === f[1]) {
      if (places[0] <= f[0] && f[0] < places[0] + text.length) places[0] = f[0] + 1;
      if (places[1] <= f[0] && f[0] < places[1] + text.length) places[1] = f[0] - text.length;
    }
    const i0 = places.find(free);
    if (!mapInside(p) || i0 === undefined) return;
    [...text].forEach((ch, k) => { taken.add(`${i0 + k},${p[1]}`); mapPut(i0 + k + 1, p[1] + 1, ch, mapMode && n === pick ? "h" : "k"); });
  });
}
const toMap = (x, z) => [Math.floor(((x - WORLD.x0) / (WORLD.x1 - WORLD.x0)) * mapBox.iw), Math.floor(((WORLD.z1 - z) / (WORLD.z1 - WORLD.z0)) * mapBox.ih)];
const fromMap = (i, j) => [WORLD.x0 + (i / mapBox.iw) * (WORLD.x1 - WORLD.x0), WORLD.z1 - (j / mapBox.ih) * (WORLD.z1 - WORLD.z0)];
// Find a free viewing spot on the same level; ship landmarks must fit on the narrow deck.
function standFor(a) {
  for (const r of [2.5, 4, 6, 8, 12, 16].filter((r) => a.ship || r >= Math.min(a.r * 2.5, 16))) {
    for (let k = 0; k < 8; k++) {
      const x = a.x + r * Math.sin(k * 0.785), z = a.z - r * Math.cos(k * 0.785), fy = floorAt(x, z);
      if (fy !== null && (fy > 1.6) === !!a.ship && !blocked(x, z, fy)) return [x, z];
    }
  }
  return null;
}
// Walks to a point of interest along the roads (or jumps there with reduced motion), then faces it.
let walkPath = [], walkTo = null;
function go(id) {
  const stand = standFor(anchors[id]);
  setMap(0); moved = true; dirty = true; jumped = null;
  walkPath = []; walkTo = null;
  if (!stand) return;
  if (reduced.matches) { me.x = stand[0]; me.z = stand[1]; me.eye = floorAt(...stand) + 1.6; face(id); return; }
  const path = route(nearestNode(me.x, me.z), nearestNode(...stand));
  if (!path.length) return;
  const points = [[me.x, me.z], ...path, stand], steps = [];
  for (let i = 1; i < points.length; i++) {
    const leg = approach(points[i - 1], points[i]);
    if (!leg.length) return;
    steps.push(...leg);
  }
  walkPath = steps;
  walkTo = id;
}
function face(id) {
  const a = anchors[id];
  me.yaw = Math.atan2(a.x - me.x, a.z - me.z);
  me.pitch = Math.max(-1.1, Math.min(1.1, Math.atan2(a.y + (a.ship ? bob : 0) - me.eye, Math.hypot(a.x - me.x, a.z - me.z))));
  jumped = id;
}
function shipDockPoint([x, z]) {
  return x >= SX - 3.1 && x <= 7 && z >= -16 && z < 14;
}
function nearestNode(x, z) {
  if (shipDockPoint([x, z])) return x >= 3 ? 4 : 1;
  return NODES.reduce((b, n, i) => (Math.hypot(n[0] - x, n[1] - z) < Math.hypot(NODES[b][0] - x, NODES[b][1] - z) ? i : b), 0);
}
// Exact slab test against the same open walking bounds used by blocked().
function slabInterval(a, c, b) {
  let enter = 0, exit = 1;
  for (const k of [0, 2]) {
    const p = a[k / 2], d = c[k / 2] - p, low = walkBound(b, k), high = walkBound(b, k + 3);
    if (d === 0) {
      if (p <= low || p >= high) return null;
    } else {
      const t0 = (low - p) / d, t1 = (high - p) / d;
      enter = Math.max(enter, Math.min(t0, t1));
      exit = Math.min(exit, Math.max(t0, t1));
      if (enter >= exit) return null;
    }
  }
  return enter < exit ? [enter, exit] : null;
}
const alongSegment = (a, c, t) => [a[0] + (c[0] - a[0]) * t, a[1] + (c[1] - a[1]) * t];
function edgeCut(a, c, p, q) {
  const dx = c[0] - a[0], dz = c[1] - a[1], ex = q[0] - p[0], ez = q[1] - p[1];
  const det = dx * ez - dz * ex;
  if (det === 0) return null;
  const px = p[0] - a[0], pz = p[1] - a[1];
  const t = (px * ez - pz * ex) / det, u = (px * dz - pz * dx) / det;
  return u >= 0 && u <= 1 ? t : null;
}
function shipFloorEdges() {
  const edges = [];
  const sections = [HULL.map(([z, w]) => [z, w - 0.25]),
    [[-14.6, 2.1 - 0.25], [-9, 2.1 + 5.6 * 0.08 - 0.25]]];
  for (const stations of sections) {
    for (let i = 1; i < stations.length; i++) {
      const [z0, w0] = stations[i - 1], [z1, w1] = stations[i];
      edges.push([[SX - w0, z0], [SX + w0, z0]], [[SX - w1, z1], [SX + w1, z1]]);
      for (const side of [-1, 1]) edges.push([[SX + side * w0, z0], [SX + side * w1, z1]]);
    }
  }
  return edges;
}
const SHIP_FLOOR_EDGES = shipFloorEdges();
function floorCuts(a, c, enter = 0, exit = 1) {
  const cuts = [enter, exit];
  for (const f of FLOORS) {
    for (let k = 0; k < 4; k++) {
      const axis = k >> 1, d = c[axis] - a[axis], t = (f[k] - a[axis]) / d;
      if (d !== 0 && t > enter && t < exit) cuts.push(t);
    }
  }
  if (Math.min(a[0], c[0]) <= SX + 3.1 && Math.max(a[0], c[0]) >= SX - 3.1 &&
      Math.min(a[1], c[1]) <= 13 && Math.max(a[1], c[1]) >= -15) {
    for (const [p, q] of SHIP_FLOOR_EDGES) {
      const t = edgeCut(a, c, p, q);
      if (t !== null && t > enter && t < exit) cuts.push(t);
    }
  }
  return cuts.sort((a, b) => a - b);
}
function terrainRange(a, c) {
  const x = (a[0] + c[0]) / 2, z = (a[1] + c[1]) / 2;
  const radius = Math.hypot(c[0] - a[0], c[1] - a[1]) / 2;
  const distance = landDistance(x, z), spread = radius * 1.25;
  const low = 1.2 - 2.8 * smooth((distance + spread + 6) / 7.5);
  const high = 1.2 - 2.8 * smooth((distance - spread + 6) / 7.5);
  const x0 = Math.min(a[0], c[0]), x1 = Math.max(a[0], c[0]);
  const wallMin = smooth((x0 + 8) / 1.5) * smooth((9 - x1) / 1.5);
  const wallMax = smooth((x1 + 8) / 1.5) * smooth((9 - x0) / 1.5);
  const y0 = 1.2 - (14 - Math.min(a[1], c[1])) * 1.6;
  const y1 = 1.2 - (14 - Math.max(a[1], c[1])) * 1.6;
  return [Math.max(-1.6, low + Math.min(0, y0 - low) * wallMax),
    Math.max(-1.6, high + Math.min(0, y1 - high) * wallMin)];
}
function floorRange(a, c) {
  const [x, z] = alongSegment(a, c, 0.5);
  const f = FLOORS.find(([x0, x1, z0, z1]) => x >= x0 && x < x1 && z >= z0 && z < z1);
  let y0, y1;
  if (f) {
    y0 = f[4](...a); y1 = f[4](...c);
  } else if (shipFloor(x, z) !== null) {
    const roof = z >= -14.6 && z < -9 && Math.abs(x - SX) <= 2.1 + (z + 14.6) * 0.08 - 0.25;
    y0 = bob + (roof ? 4.8 : shipProfile(a[1])[1]) * rc + rs * (a[0] - SX);
    y1 = bob + (roof ? 4.8 : shipProfile(c[1])[1]) * rc + rs * (c[0] - SX);
  } else return terrainRange(a, c);
  return [Math.min(y0, y1), Math.max(y0, y1)];
}
function floorIntervalCovered(a, c) {
  if (floorRange(a, c)[0] > 0.1) return true;
  const middle = alongSegment(a, c, 0.5);
  if (floorAt(...middle) === null || Math.hypot(c[0] - a[0], c[1] - a[1]) < 1e-7) return false;
  return floorIntervalCovered(a, middle) && floorIntervalCovered(middle, c);
}
function floorCovered(a, c) {
  const cuts = floorCuts(a, c);
  for (let i = 1; i < cuts.length; i++) {
    if (floorAt(...alongSegment(a, c, cuts[i])) === null) return false;
    const before = floorAt(...alongSegment(a, c, Math.max(cuts[i - 1], cuts[i] - 1e-9)));
    const after = floorAt(...alongSegment(a, c, Math.min(1, cuts[i] + 1e-9)));
    if (before === null || after === null || Math.abs(after - before) > 0.6) return false;
    if (!floorIntervalCovered(alongSegment(a, c, cuts[i - 1]), alongSegment(a, c, cuts[i]))) return false;
  }
  return true;
}
function solidInterval(a, c, s, lift) {
  const [low, high] = floorRange(a, c);
  if (s.bb[1] + lift >= high + 1.7 || s.bb[4] + lift <= low + 0.3) return false;
  const middle = alongSegment(a, c, 0.5), fy = floorAt(...middle);
  if (fy !== null && walkingSolid(s, fy, lift)) return true;
  if (Math.hypot(c[0] - a[0], c[1] - a[1]) < 1e-7) return true;
  return solidInterval(a, middle, s, lift) || solidInterval(middle, c, s, lift);
}
function segmentBlocked(a, c, s) {
  const interval = slabInterval(a, c, s.bb);
  if (!interval) return false;
  const cuts = floorCuts(a, c, ...interval), lift = ship.includes(s) ? bob : 0;
  for (const t of cuts) {
    if (t <= interval[0] || t >= interval[1]) continue;
    const fy = floorAt(...alongSegment(a, c, t));
    if (fy !== null && walkingSolid(s, fy, lift)) return true;
  }
  for (let i = 1; i < cuts.length; i++) {
    if (solidInterval(alongSegment(a, c, cuts[i - 1]), alongSegment(a, c, cuts[i]), s, lift)) return true;
  }
  return false;
}
function walkable([x, z]) {
  const fy = floorAt(x, z);
  return fy !== null && !blocked(x, z, fy);
}
function routeObstacle(s, lift) {
  if (!s.solid) return false;
  const b = s.bb, a = [walkBound(b, 0), walkBound(b, 2)], c = [walkBound(b, 3), walkBound(b, 5)];
  let [low, high] = terrainRange(a, c);
  for (const [x0, x1, z0, z1, height] of FLOORS) {
    if (a[0] >= x1 || c[0] < x0 || a[1] >= z1 || c[1] < z0) continue;
    const y0 = height(Math.max(a[0], x0)), y1 = height(Math.min(c[0], x1));
    low = Math.min(low, y0, y1); high = Math.max(high, y0, y1);
  }
  return b[1] + lift < high + 1.7 && b[4] + lift > Math.max(0.1, low) + 0.3;
}
function routeObstacles() {
  return [...world.filter(s => routeObstacle(s, 0)), ...ship.filter(s => s.solid)];
}
function detourCorners(b) {
  const x0 = walkBound(b, 0), x1 = walkBound(b, 3), z0 = walkBound(b, 2), z1 = walkBound(b, 5);
  return [[x0, z0], [x1, z0], [x1, z1], [x0, z1]].filter(walkable);
}
function clear(a, c, obstacles) {
  return walkable(a) && walkable(c) && floorCovered(a, c) && !obstacles.some(s => segmentBlocked(a, c, s));
}
function clearLinks(nodes, obstacles) {
  const links = [];
  for (let a = 0; a < nodes.length; a++) {
    for (let c = a + 1; c < nodes.length; c++) if (clear(nodes[a], nodes[c], obstacles)) links.push([a, c]);
  }
  return links;
}
let approachGraph;
function rebuildRoutes() {
  const obstacles = routeObstacles(), nodes = NODES.filter(walkable);
  nodes.push(...[[5, -15], [5, 0], [5, 10],
    [SX + 1.7, -5.4], [SX + 1.7, -9.2], [SX, -12]].filter(walkable));
  for (const { bb } of obstacles) nodes.push(...detourCorners(bb));
  approachGraph = { obstacles, nodes, edges: routeEdges(nodes, clearLinks(nodes, obstacles)) };
  return approachGraph;
}
function nearestClear(point, nodes, obstacles) {
  const order = nodes.map((n, i) => [i, Math.hypot(point[0] - n[0], point[1] - n[1])]);
  order.sort((a, b) => a[1] - b[1]);
  for (const [i] of order) if (clear(point, nodes[i], obstacles)) return i;
  return -1;
}
function approach(from, to) {
  const { obstacles, nodes, edges } = approachGraph;
  if (clear(from, to, obstacles)) return [to];
  const a = nearestClear(from, nodes, obstacles), b = nearestClear(to, nodes, obstacles);
  if (a < 0 || b < 0) return [];
  const path = route(a, b, nodes, edges);
  return path.length ? [...path, to] : [];
}
function routeEdges(nodes, links) {
  const edges = nodes.map(() => []);
  for (const [a, b] of links) {
    const d = Math.hypot(nodes[b][0] - nodes[a][0], nodes[b][1] - nodes[a][1]);
    edges[a].push([b, d]); edges[b].push([a, d]);
  }
  return edges;
}
// Shortest route between two nodes (Dijkstra over weighted edges).
function route(from, to, nodes = NODES, edges = routeEdges(nodes, LINKS)) {
  const dist = nodes.map(() => Infinity), prev = [], todo = new Set(nodes.keys());
  dist[from] = 0;
  while (todo.size) {
    const u = [...todo].reduce((a, b) => (dist[a] < dist[b] ? a : b));
    todo.delete(u);
    if (u === to || dist[u] === Infinity) break;
    for (const [v, length] of edges[u]) {
      const d = dist[u] + length;
      if (todo.has(v) && d < dist[v]) { dist[v] = d; prev[v] = u; }
    }
  }
  if (dist[to] === Infinity) return [];
  const path = [];
  for (let v = to; v !== undefined; v = prev[v]) path.unshift(nodes[v]);
  return path;
}
// One frame of the auto-walk: head for the next waypoint, turning smoothly; face the object on arrival.
function autoStep(dt) {
  const [tx, tz] = walkPath[0], dx = tx - me.x, dz = tz - me.z, d = Math.hypot(dx, dz), v = 4.5 * dt;
  if (d <= v) {
    me.x = tx; me.z = tz; walkPath.shift();
    if (!walkPath.length) face(walkTo);
    return true;
  }
  me.x += (dx / d) * v; me.z += (dz / d) * v;
  const turn = Math.atan2(dx, dz) - me.yaw;
  me.yaw += Math.atan2(Math.sin(turn), Math.cos(turn)) * Math.min(1, dt * 6);
  me.pitch *= 0.9;
  return true;
}
// An open map frees the mouse (no pointer lock, a normal cursor) so you can point at it; walking hides it again.
function setMap(mode) {
  mapMode = mode;
  if (mode && document.pointerLockElement) document.exitPointerLock();
  stage.classList.toggle("mapping", mode > 0);
}
// M picks on the map, M again fills the screen, M or Escape closes; arrows or the mouse choose, Enter goes.
function mapKey(e) {
  if (interior) return e.code === "KeyM";
  if (e.code === "KeyM") setMap((mapMode + 1) % 3);
  else if (!mapMode) return false;
  else if (e.key === "Escape") setMap(0);
  else if (e.key === "Enter") go(ORDER[pick]);
  else if (/^Arrow/.test(e.key)) pick = (pick + (/Right|Down/.test(e.key) ? 1 : ORDER.length - 1)) % ORDER.length;
  else return false;
  moved = true; // using the map folds the intro away
  return true;
}
// Map cell under a screen point, or null outside the map.
function mapCell(cx, cy) {
  const b = mapBox, i = b && Math.floor((cx - padX) / cellW) - b.oi, j = b && Math.floor((cy - padY) / cellH) - b.oj;
  return b && i >= 0 && j >= 0 && i < b.w && j < b.h ? [i, j] : null;
}
// Points of interest nearest to a map cell, the closest first (several when they share a cell).
function nearestPoints(i, j) {
  const d = (id) => { const [pi, pj] = toMap(anchors[id].x, anchors[id].z); return Math.hypot(pi - i + 1, (pj - j + 1) * 2); };
  const all = ORDER.map((id, n) => [d(id), n]).sort((p, q) => p[0] - q[0]);
  return all.filter((p) => p[0] <= all[0][0] + 0.01).map(([, n]) => n);
}
// Hovering the open map with the mouse picks the nearest point.
function hoverMap(cx, cy) {
  const at = mapMode && mapCell(cx, cy);
  if (!at || at[1] === 0 || at[1] >= mapBox.h - 2) return;
  const near = nearestPoints(...at);
  if (!near.includes(pick)) { pick = near[0]; dirty = true; }
}
// A tap or click on the map: the corner mark resizes it, the caption goes to the pick, elsewhere picks the nearest point.
function tapMap(cx, cy) {
  const at = mapCell(cx, cy);
  if (!at) return false;
  if (at[1] === 0) setMap(mapMode === 2 ? 0 : 2);
  else if (at[1] >= mapBox.h - 2) go(ORDER[pick]);
  else {
    const near = nearestPoints(...at);
    pick = near[(near.indexOf(pick) + 1) % near.length];
    if (mapMode === 0) setMap(1);
  }
  dirty = true;
  return true;
}

// One ray: the nearest of the solids, the moving sea surface and the sky decides the cell.
function cast(c, i, odd, dx, dy, dz) {
  if (interior) { castRoom(c, i, odd, dx, dy, dz); return; }
  // A downward ray meets the island or the sea before it sinks below the lowest wave, so no solid past that shows.
  hitT = dy < 0 ? (cam.y + SEA) / -dy : Infinity; hitS = null;
  trace(rowWorld, i, cam.x, cam.y, cam.z, dx, dy, dz);
  const wS = hitS;
  const ldx = rc * dx + rs * dy, ldy = -rs * dx + rc * dy;
  const shipNear = boxEntry(SHIP_BOUNDS, cam.lx, cam.ly, cam.z, 1 / ldx, 1 / ldy, 1 / dz);
  // Parallel rays on a box boundary can yield NaN; keep those for the exact part tests.
  if (shipNear < hitT || Number.isNaN(shipNear)) trace(rowShip, i, cam.lx, cam.ly, cam.z, ldx, ldy, dz);
  const tw = surfaceHit(dx, dy, dz, hitS ? hitT : Infinity);
  SP[c] = null;
  if (hitS && hitT < tw) shadeSolid(c, odd, hitS !== wS, dx, dy, dz, ldx, ldy);
  else if (tw < Infinity && onLand) shadeLand(c, odd, tw, dx, dy, dz);
  else if (tw < Infinity) shadeWater(c, tw, dx, dy, dz);
  else shadeSky(c, dx, dy, dz);
}
// The island under a ray: its normal from the slope of the height field, then shaded like any solid. The plateau
// top (the height grid at 1.2 m all round) is flat, so only slopes sample the height field.
function shadeLand(c, odd, t, dx, dy, dz) {
  const x = cam.x + dx * t, z = cam.z + dz * t, e = 0.15, flat = marchY(x, z) > 1.2 - 1e-6;
  const hx = flat ? 0 : (terrainY(x + e, z) - terrainY(x - e, z)) / (2 * e), hz = flat ? 0 : (terrainY(x, z + e) - terrainY(x, z - e)) / (2 * e), l = Math.sqrt(hx * hx + 1 + hz * hz);
  hitS = TERRAIN; hitK = -5; hitT = t; hitN[0] = -hx / l; hitN[1] = 1 / l; hitN[2] = -hz / l;
  shadeSolid(c, odd, false, dx, dy, dz, dx, dy);
}
// Brightness changes the ground textures ask for: kerbs and flowers brighter, joints, ruts and wet sand darker.
const GRAIN = { _: 1.35, "=": 1.3, "*": 1.5, "~": 1.25, "+": 1.1, "-": 1.1, ".": 1, ",": 0.85, ":": 0.7, ";": 0.8, '"': 0.9, "'": 0.95, "`": 0.9, " ": 1 };
const paleGroundMark = (tex) => tex === "s|" || tex === "s-" || tex === "s=" || tex === "k~";
function textureColor(s, tex, b, fog, warm) {
  if (s.tex === fountainWater) return tex[0] + tier(Math.max(0.34, b), 0);
  if (s === TERRAIN && paleGroundMark(tex)) {
    return tex[0] + tier(Math.max(b, (tex === "k~" ? 0.5 : 0.35) * fog), warm);
  }
  return null;
}
function shipFill(s, tex, b, fog) {
  return s.fill ? Math.max(b, s.fill * fog * (tex === "-" ? 0.65 : 1)) : b;
}
// Canvas and the flag use fixed tones, without point-light or shadow work.
function paintShipCloth(c, odd, dx, dy, dz) {
  const s = hitS, k = s.cloth, t = hitT, cell = t * 2 * cam.tanV / rows;
  const qx = cam.lx + dx * t - k.at[0], qz = cam.z + dz * t - k.at[2], u = qx * k.cu + qz * k.su, v = k.at[1] - cam.ly - dy * t;
  const id = s.id * 16 + clothSide(k, u, v, dx, dy, dz);
  if (s.flag) paintFlag(c, id, t, s.tex(u, v, cell), k);
  else paintCanvas(c, odd, id, t, s, k, u, v, qz * k.cu - qx * k.su, cell);
  SP[c] = s.spot;
}
// The black flag leaves its cloth dark, so only its pale outline and the folds of its ripples show around the pale
// Jolly Roger. The bones' slanted glyphs mirror when the flag's u runs to the left on screen.
function paintFlag(c, id, t, mark, k) {
  const mirror = k.cu * cam.r[0] + k.su * cam.r[2] < 0;
  const ch = !mark ? " " : mirror && mark === "/" ? "\\" : mirror && mark === "\\" ? "/" : mark;
  put(c, ch, mark ? "s7" : "t3", id, t);
}
// Canvas brightness follows the belly: brightest where the cloth stands farthest out (w, the hit's depth) and a few glyph
// steps darker toward its edges. The canvas keeps its flat colour tier, so it stays pale and its rows draw in few runs.
function paintCanvas(c, odd, id, t, s, k, u, v, w, cell) {
  const flat = s.fill * Math.exp(-t * 0.016), belly = k.belly ? w / (k.belly * 1.13) : 0;
  const b = flat * (0.88 + 0.3 * belly) * (s.tex(u, v, cell, k) ? 0.85 : 1);
  put(c, glyph(b, odd), CLASS.s[Math.min(7, Math.floor(flat * 9))], id, t);
}
function shadeSolid(c, odd, onShip, dx, dy, dz, ldx, ldy) {
  if (hitS.cloth) paintShipCloth(c, odd, ldx, ldy, dz);
  else shadeLitSolid(c, odd, onShip, dx, dy, dz, ldx, ldy);
}
function shadeLitSolid(c, odd, onShip, dx, dy, dz, ldx, ldy) {
  const s = hitS, P = s.P, k = hitK, t = hitT;
  const lnx = k >= 0 ? P[k] : hitN[0], lny = k >= 0 ? P[k + 1] : hitN[1], nz = k >= 0 ? P[k + 2] : hitN[2];
  const nx = onShip ? rc * lnx - rs * lny : lnx, ny = onShip ? rs * lnx + rc * lny : lny;
  const px = onShip ? cam.lx + ldx * t : cam.x + dx * t, py = onShip ? cam.ly + ldy * t : cam.y + dy * t, pz = cam.z + dz * t;
  const tex = s.tex && s.tex(px, py, pz, lnx, lny, nz);
  const mat = tex && tex !== "-" ? tex[0] : s.mat, grain = tex && tex.length === 2 ? GRAIN[tex[1]] || 1 : 1;
  let ch, cls = mat;
  if (mat === "l") {
    const flash = s === beacon ? Math.cos(T * 2.2 + Math.atan2(dx, dz) * 2) > 0.3 : s !== antennaLamp || Math.sin(T * 3) > 0;
    ch = flash ? "@" : "*"; cls = "l7";
  } else {
    const wx = onShip ? SX + rc * (px - SX) - rs * py : px, wy = onShip ? rs * (px - SX) + rc * py + bob : py;
    const dim = (tex === "-" ? 0.55 : 1) * (s.dim || 1) * grain;
    const [lit, warm] = lightAt(wx, wy, pz, nx, ny, nz);
    // Contact shadow: walls darken toward the ground they stand on.
    const ao = ny > 0.7 ? 1 : Math.min(1, 0.55 + 0.5 * (wy - (onShip ? bob + DECK : floorAt(wx, pz) ?? 0)));
    const fog = Math.exp(-t * 0.016);
    const b = shipFill(s, tex, (lit * dim * ao * (0.8 + 0.2 * Math.max(0, -(nx * dx + ny * dy + nz * dz)))) * fog + 0.02 * (1 - fog), fog);
    cls = mat + tier(b, warm);
    // Grass blades lean with the wind; fountain water keeps its texture glyphs below.
    const grass = ny > 0.7 && (mat === "g" || mat === "G" || mat === "M") && s === TERRAIN;
    ch = grass && b > 0.03 ? blade(px, pz, odd) : glyph(b, odd);
    const texture = textureColor(s, tex, b, fog, warm);
    if (texture) {
      ch = tex[1];
      cls = texture;
    }
  }
  // Floors get a negative id: they outline what stands on them but draw no edges themselves.
  put(c, ch, cls, (ny > 0.7 ? -1 : 1) * (s.id * 16 + (k >= 0 ? k >> 2 : 12 - k)), t);
  SP[c] = s.spot;
}
// Glyph for a brightness from the long ramp; the darkest cells thin out to a dither.
const glyph = (b, odd) => (b < 0.035 ? (odd ? " " : b > 0.02 ? "." : " ") : RAMP[Math.min(RAMP.length - 1, 1 + Math.floor(b * (RAMP.length - 2)))]);
// A grass blade: short tufts and taller blades that lean left or right as gusts roll across the island.
function blade(x, z, odd) {
  const t = swayTime(), h = hash(Math.floor(x * 5), Math.floor(z * 5)), gust = Math.sin(t * 1.7 + x * 0.35 + z * 0.22) + 0.5 * Math.sin(t * 3.1 + x * 1.3);
  if (h < 0.18) return odd ? " " : ",";
  if (h < 0.55) return gust > 0.6 ? "/" : gust < -0.6 ? "\\" : "|";
  return h < 0.75 ? "'" : h < 0.9 ? '"' : ";";
}
// Colour level (0 to 7) for a brightness, warmed when lamplight dominates.
const tier = (b, warm) => (warm > 0.55 && b > 0.2 ? "w" : "") + Math.min(7, Math.floor(b * 9));
// How close water at (x, z) is to the shore, from 0 (deep, the bed 1.6 m down) to 1 (the waterline).
function shallows(x, z) {
  return Math.min(1, Math.max(0, (marchY(x, z) + 1.6) / 1.6));
}

// ---- The sea: a height field of summed travelling waves (amplitude, direction, wave number, speed, phase),
// ray marched per cell, with analytic normals for Fresnel reflection, moon and lamp highlights, and foam.
const WAVES = new Float64Array([0.17, 0.8, 0.6, 0.7, 2.6, 0, 0.11, -0.3, 0.95, 1.14, 3.3, 1.7, 0.07, 0.95, -0.3, 1.96, 4.4, 4.1, 0.035, 0.2, 0.98, 3.5, 5.8, 2.3]);
const SEA = 0.17 + 0.11 + 0.07 + 0.035;
const seaN = [0, 1, 0];
function seaHeight(x, z) {
  let h = 0;
  for (let i = 0; i < 24; i += 6) h += WAVES[i] * Math.sin(WAVES[i + 3] * (WAVES[i + 1] * x + WAVES[i + 2] * z) - WAVES[i + 4] * T + WAVES[i + 5]);
  return h;
}
function seaNormal(x, z) {
  let hx = 0, hz = 0;
  for (let i = 0; i < 24; i += 6) {
    const c = WAVES[i] * WAVES[i + 3] * Math.cos(WAVES[i + 3] * (WAVES[i + 1] * x + WAVES[i + 2] * z) - WAVES[i + 4] * T + WAVES[i + 5]);
    hx += c * WAVES[i + 1]; hz += c * WAVES[i + 2];
  }
  const l = Math.sqrt(hx * hx + 1 + hz * hz);
  seaN[0] = -hx / l; seaN[1] = 1 / l; seaN[2] = -hz / l;
}
// Distance along the ray to the island or the sea, whichever it meets first (onLand says which), or
// Infinity if a solid at `limit` comes first. Steps grow with distance; a crossing is refined by bisection.
let onLand = false;
// Is the point below the island or the sea? Waves never rise above SEA, so higher points skip them.
const under = (x, y, z) => y < marchY(x, z) || (y < SEA && y < seaHeight(x, z));
function surfaceHit(dx, dy, dz, limit) {
  if (dy > -1e-4) return Infinity;
  let a = Math.max(0, (1.3 - cam.y) / dy);
  const end = Math.min(limit, 260);
  for (let i = 0; i < 56 && a < end; i++) {
    let b = Math.min(end, a + 0.25 + a * 0.08);
    if (under(cam.x + b * dx, cam.y + b * dy, cam.z + b * dz)) {
      for (let k = 0; k < 5; k++) { const m = (a + b) / 2; if (under(cam.x + m * dx, cam.y + m * dy, cam.z + m * dz)) b = m; else a = m; }
      const x = cam.x + b * dx, z = cam.z + b * dz;
      onLand = marchY(x, z) >= seaHeight(x, z);
      return b;
    }
    a = b;
  }
  const t = -cam.y / dy; // beyond the march the sea is flat enough
  onLand = false;
  return t < limit && t >= end ? t : Infinity;
}
function waterLampSpec(x, h, z, rx, ry, rz) {
  let lampSpec = 0;
  for (const L of LIGHTS) {
    const lx = L.wx - x, ly = L.wy - h, lz = L.wz - z, d2 = lx * lx + ly * ly + lz * lz;
    if (d2 > 3600) continue;
    const d = Math.sqrt(d2), s = (rx * lx + ry * ly + rz * lz) / d;
    if (s > 0.985) lampSpec += L.i * Math.pow(s, 300) * 1.4 / (1 + d2 * 0.006);
  }
  return lampSpec;
}
// Foam on the highest crests, and a broken line where waves wash onto the beaches.
function waterFoam(x, z, h, near) {
  return Math.max(0, (h - SEA * 0.7) / (SEA * 0.3)) * 0.6 + (near > 0.82 && Math.sin(x * 1.3 + z + T * 0.9) > -0.25 ? 0.65 : 0);
}
function waterReflection(lampSpec, moonSpec) {
  if (lampSpec > moonSpec && lampSpec > 0.1) return "l";
  return moonSpec > 0.1 ? "m" : null;
}
function waterGlyph(c, t, foam, lum, fog, mat) {
  if (foam > 0.4) { put(c, "~", "k" + tier(Math.max(lum, 0.5 * fog), 0), -1, t); return; }
  const soft = Math.min(0.78, lum); // highlights stay sparkles, not solid blocks
  put(c, glyph(soft, (c ^ Math.floor(t)) & 1), mat + tier(lum, 0), -1, t);
}
function shadeWater(c, t, dx, dy, dz) {
  const x = cam.x + dx * t, z = cam.z + dz * t, h = seaHeight(x, z), near = shallows(x, z);
  seaNormal(x, z);
  const [nx, ny, nz] = seaN, dn = dx * nx + dy * ny + dz * nz, rx = dx - 2 * dn * nx, ry = dy - 2 * dn * ny, rz = dz - 2 * dn * nz;
  const fresnel = 0.04 + 0.96 * Math.pow(1 - Math.min(1, -dn), 5);
  const moonSpec = Math.pow(Math.max(0, rx * MOON[0] + ry * MOON[1] + rz * MOON[2]), 90) * 1.4;
  const lampSpec = waterLampSpec(x, h, z, rx, ry, rz), foam = waterFoam(x, z, h, near);
  const body = (0.03 + 0.12 * Math.max(0, nx * MOON[0] + ny * MOON[1] + nz * MOON[2])) * (1 + near);
  const fog = Math.exp(-t * 0.014), lum = ((body * (1 - fresnel) + 0.03 * fresnel + moonSpec + lampSpec + foam * 0.35 + beamOn(x, z) * 0.6) * fog) + 0.015 * (1 - fog);
  const mat = waterReflection(lampSpec, moonSpec) || (near > 0.2 ? "w" : "d");
  waterGlyph(c, t, foam, lum, fog, mat);
}
// How close a sky ray passes to the lighthouse beam, as a glow from 0 to 1.
function beamGlow(dx, dy, dz) {
  const ux = BEAM.dx, uy = -0.02, uz = BEAM.dz, wx = cam.x - BEAM.x, wy = cam.y - BEAM.y, wz = cam.z - BEAM.z;
  const b = dx * ux + dy * uy + dz * uz, d = dx * wx + dy * wy + dz * wz, e = ux * wx + uy * wy + uz * wz, den = 1 - b * b;
  const sc = (b * e - d) / den, tc = (e - b * d) / den;
  if (sc < 0 || tc < 2 || tc > BEAM.reach) return 0;
  const gx = wx + sc * dx - tc * ux, gy = wy + sc * dy - tc * uy, gz = wz + sc * dz - tc * uz;
  return Math.max(0, 1 - Math.sqrt(gx * gx + gy * gy + gz * gz) / (0.4 + tc * 0.012)) * (1 - tc / BEAM.reach);
}
// ---- Clouds: three moonlit layers drift with the wind ------------------------------------------------------------
// Each cloud is a long band of rounded bumps on a flat base, on a billboard that faces you. The clouds of a layer sit
// on a square lattice that drifts downwind; some lattice cells stay empty, so clear sky lies between the clouds.
// Base height (m), lattice spacing (m), drift (m/s); the nearest layer comes first.
const CLOUD_LAYERS = [{ base: 260, spacing: 650, speed: 5 }, { base: 480, spacing: 1200, speed: 7 },
  { base: 900, spacing: 2250, speed: 10 }];
// The clouds in reach this frame, 25 numbers each: direction, distance, horizontal and upward billboard axes, cosine
// of the angular radius, moon direction on the billboard, length, haze, bump count, then five bumps (centre, radius)
// in band lengths. The seed picks a layout with clouds over the opening view.
const CLOUDS = new Float32Array(160 * 25), CLOUD_SEED = 2;
let cloudCount = 0;
// Sky texels of 1°, azimuth by elevation, keep the cloud density and moonlit rim of their direction.
// SKY_ROW holds each row's refresh key. ROW_CLOUDS lists the clouds that can reach each row.
// ROW_BINS marks the 5° azimuth bins they can reach; sky cells elsewhere skip the buffer.
const SKY_W = 360, SKY_H = 90, SKY = new Float32Array(SKY_W * SKY_H * 2), SKY_STEP = new Int32Array(SKY_W * SKY_H).fill(-1);
const SKY_ROW = new Int32Array(SKY_H), ROW_CLOUDS = new Uint8Array(SKY_H * 160), ROW_COUNT = new Uint8Array(SKY_H);
const ROW_BINS = new Uint8Array(SKY_H * 72);
let cloudFrame = -1;
// Negative render keys differ from time steps and the initial -1, so reduced-motion frames cannot retain stale camera views.
function gatherClouds(tenths) {
  if (reduced.matches) SKY_ROW.fill(--cloudFrame);
  else for (let j = 0; j < SKY_H; j++) SKY_ROW[j] = Math.floor(tenths + j * 0.618 % 1);
  const along0 = cam.x * WIND.x + cam.z * WIND.z, across0 = cam.x * WIND.z - cam.z * WIND.x;
  cloudCount = 0;
  ROW_COUNT.fill(0);
  ROW_BINS.fill(0);
  CLOUD_LAYERS.forEach(({ base, spacing, speed }, n) => {
    const reach = 4.5 * base, drift = speed * T;
    for (let i = Math.floor((along0 - drift - reach) / spacing); i * spacing + drift < along0 + reach; i++) {
      for (let j = Math.floor((across0 - reach) / spacing); j * spacing < across0 + reach; j++) {
        const I = i + 60 * n + CLOUD_SEED, J = j - 40 * n;
        if (hash(I, J) < 0.45 && cloudCount < 160) placeCloud(I, J, base, (i + 0.1 + 0.8 * hash(J, I)) * spacing + drift, (j + 0.1 + 0.8 * hash(I + 0.5, J)) * spacing);
      }
    }
  });
}
function placeCloud(I, J, base, along, across) {
  const x = along * WIND.x + across * WIND.z - cam.x, z = along * WIND.z - across * WIND.x - cam.z, y = base - cam.y;
  const flat = Math.sqrt(x * x + z * z), haze = 1 - smooth(flat / base - 3.5), d = Math.sqrt(flat * flat + y * y);
  if (haze <= 0) return;
  const length = base * (0.7 + 0.4 * hash(I * 3, J * 5)), bumps = 3 + Math.floor(3 * hash(J, I * 7)), o = cloudCount * 25;
  const ux = -y * x / d / flat, uy = flat / d, uz = -y * z / d / flat; // the upward billboard axis
  const mx = (MOON[0] * z - MOON[2] * x) / flat, my = MOON[0] * ux + MOON[1] * uy + MOON[2] * uz, ml = Math.hypot(mx, my) || 1;
  CLOUDS.set([x / d, y / d, z / d, d, z / flat, -x / flat, ux, uy, uz, d / Math.hypot(d, 0.7 * length), mx / ml, my / ml, length, haze, bumps], o);
  for (let b = 0; b < bumps; b++) {
    const t = b / (bumps - 1), r = hash(I + b, J - b);
    CLOUDS[o + 15 + 2 * b] = (t - 0.5) * 0.8 + 0.06 * (r - 0.5);
    CLOUDS[o + 16 + 2 * b] = (0.14 + 0.13 * (1 - Math.abs(2 * t - 1))) * (0.85 + 0.3 * r);
  }
  // Six samples bound most billboards; pole crossings need a separate bound because elevation can peak between samples.
  const az = Math.atan2(x, z);
  let low = 90, high = 0, left = 0, right = 0;
  for (const [X, Y] of [[-0.6, -0.04], [0, -0.04], [0.6, -0.04], [-0.6, 0.32], [0, 0.32], [0.6, 0.32]]) {
    const px = x + (z / flat * X + ux * Y) * length, py = y + uy * Y * length, pz = z - (x / flat * X - uz * Y) * length;
    const rise = Math.asin(py / Math.hypot(px, py, pz)) * 180 / Math.PI, turn = (Math.atan2(px, pz) - az + 3 * Math.PI) % (2 * Math.PI) - Math.PI;
    low = Math.min(low, rise); high = Math.max(high, rise); left = Math.min(left, turn); right = Math.max(right, turn);
  }
  const zenith = flat * d / y / length;
  if (y > 0 && zenith >= -0.04 && zenith <= 0.32) high = 90;
  if (high > 75) { left = -Math.PI; right = Math.PI; }
  for (let j = Math.max(0, Math.floor(low - 1)); j <= Math.min(SKY_H - 1, high + 1); j++) {
    ROW_CLOUDS[j * 160 + ROW_COUNT[j]++] = cloudCount;
    for (let b = Math.floor((az + left + Math.PI) * 36 / Math.PI - 0.2); b <= (az + right + Math.PI) * 36 / Math.PI + 0.2; b++) ROW_BINS[j * 72 + (b + 72) % 72] = 1;
  }
  cloudCount++;
}
// Cloud density (0 to 1) toward a direction, nearest cloud in front; haze trims distant clouds from the edge in, so
// they shrink rather than fade to dots. cloudEdge gets the moonlit rim: the edge of each bump, or the flat base, on
// the side that faces the moon.
let cloudEdge = 0;
function cloudDensity(dx, dy, dz) {
  const row = Math.max(0, Math.min(SKY_H - 1, Math.floor(Math.asin(dy) * SKY_H * 2 / Math.PI))), count = ROW_COUNT[row];
  let cover = 0, rim = 0;
  for (let n = 0; n < count && cover < 0.98; n++) {
    const o = ROW_CLOUDS[row * 160 + n] * 25, c = dx * CLOUDS[o] + dy * CLOUDS[o + 1] + dz * CLOUDS[o + 2];
    if (c < CLOUDS[o + 9]) continue;
    const k = CLOUDS[o + 3] / c / CLOUDS[o + 12], x = (dx * CLOUDS[o + 4] + dz * CLOUDS[o + 5]) * k;
    const y = (dx * CLOUDS[o + 6] + dy * CLOUDS[o + 7] + dz * CLOUDS[o + 8]) * k;
    let best = 0, q = 1, nx = 0;
    for (let b = o + 15; b < o + 15 + 2 * CLOUDS[o + 14] && y > -0.03; b += 2) {
      const bx = x - CLOUDS[b], qb = Math.sqrt(bx * bx + y * y) / CLOUDS[b + 1], f = smooth((1 - qb) / 0.55);
      if (f > best) { best = f; q = qb; nx = bx; }
    }
    const haze = CLOUDS[o + 13], a = (best * smooth((y + 0.03) / 0.03) - 1 + haze) / haze;
    if (a <= 0) continue;
    const side = Math.max(0, (nx * CLOUDS[o + 10] + y * CLOUDS[o + 11]) / (Math.hypot(nx, y) || 1)) * smooth((q - 0.4) / 0.45);
    rim += (1 - cover) * a * Math.max(side, Math.max(0, -CLOUDS[o + 11]) * smooth(1 - y / 0.06));
    cover += (1 - cover) * a;
  }
  cloudEdge = rim;
  return cover;
}
function refreshTexel(k, j) {
  SKY_STEP[k] = SKY_ROW[j];
  const a = (k - j * SKY_W + 0.5) * 2 * Math.PI / SKY_W - Math.PI, b = (j + 0.5) * Math.PI / 2 / SKY_H, cb = Math.cos(b);
  SKY[2 * k] = cloudDensity(cb * Math.sin(a), Math.sin(b), cb * Math.cos(a));
  SKY[2 * k + 1] = cloudEdge;
}
// Bilinear read of the buffer for a sky direction; cloudRim gets the moonlit rim.
let cloudRim = 0;
function skyClouds(az, el) {
  const u = (az + Math.PI) * (SKY_W / 2 / Math.PI) - 0.5, v = Math.min(SKY_H - 1.001, Math.max(0, el * (SKY_H * 2 / Math.PI) - 0.5));
  const i = Math.floor(u), j = Math.floor(v), bin = Math.floor((u + 0.5) / 5) % 72;
  if (!(ROW_BINS[j * 72 + bin] | ROW_BINS[j * 72 + 72 + bin])) return (cloudRim = 0);
  const i0 = i < 0 ? SKY_W - 1 : i, a = j * SKY_W + i0, b = i0 + 1 < SKY_W ? a + 1 : j * SKY_W, c = a + SKY_W, d = b + SKY_W;
  if (SKY_STEP[a] !== SKY_ROW[j]) refreshTexel(a, j);
  if (SKY_STEP[b] !== SKY_ROW[j]) refreshTexel(b, j);
  if (SKY_STEP[c] !== SKY_ROW[j + 1]) refreshTexel(c, j + 1);
  if (SKY_STEP[d] !== SKY_ROW[j + 1]) refreshTexel(d, j + 1);
  const fu = u - i, fv = v - j, wa = (1 - fu) * (1 - fv), wb = fu * (1 - fv), wc = (1 - fu) * fv, wd = fu * fv;
  cloudRim = SKY[2 * a + 1] * wa + SKY[2 * b + 1] * wb + SKY[2 * c + 1] * wc + SKY[2 * d + 1] * wd;
  return SKY[2 * a] * wa + SKY[2 * b] * wb + SKY[2 * c] * wc + SKY[2 * d] * wd;
}
// Glyphs grow denser with the cloud. Bodies keep the sky's dim colour; edges that face the moon, and thin cloud near
// the moon, are pale.
const CLOUD_RAMP = " .:-=+*#";
function shadeCloud(c, density, m) {
  const halo = Math.max(0, (m - 0.8) / 0.2) ** 2, light = cloudRim * (0.6 + 1.4 * halo) + 0.6 * halo * (1 - density);
  put(c, CLOUD_RAMP[Math.min(7, Math.floor(density * 8))], light < 0.25 ? "f" : light < 0.6 ? "k3" : "k5", 0, Infinity);
}
// Cloud hides the stars, and the moon once it is thick; the lighthouse beam passes in front of it.
function shadeSky(c, dx, dy, dz) {
  const m = dx * MOON[0] + dy * MOON[1] + dz * MOON[2], el = Math.asin(dy), az = Math.atan2(dx, dz), glow = beamGlow(dx, dy, dz);
  const r = hash(Math.floor(az * 150), Math.floor(el * 150)) * 2.5;
  const cover = dy > 0.02 ? skyClouds(az, el) : 0;
  if (m > 0.9988 && cover < 0.6) put(c, m > 0.99935 && cover < 0.3 ? "@" : "%", cover < 0.3 ? "k" : "k4", 0, Infinity);
  else if (el > 0.04 && r < 0.03 && cover < 0.25) put(c, r < 0.006 ? "*" : ".", "k", 0, Infinity);
  else if (glow > 0.15) put(c, glyph(glow * 0.8, 0), "l" + Math.min(7, 2 + Math.floor(glow * 6)), 0, Infinity);
  else if (cover >= 0.125) shadeCloud(c, cover, m);
  else put(c, el < 0.035 ? "." : " ", "f", 0, Infinity);
}
function put(c, ch, cls, id, depth) { G[c] = ch; C[c] = cls; ID[c] = id; D[c] = depth; }

// Is neighbour n (inside the grid) another surface at least `min` away?
const beyond = (n, inside, id, min) => inside && ID[n] !== id && D[n] >= min;
const slope = (l, r, u, w) => ((l || r) && (u || w) ? ((u && r) || (w && l) ? "\\" : "/") : l || r ? "|" : u ? "-" : w ? "_" : null);
// Outline glyph where a solid or face meets something farther away, else null.
function edge(c, i, j) {
  const id = ID[c], d = D[c];
  if (id <= 0 || d >= 70) return null;
  // Neighbours left and up must be farther, right and down at least as far, so each seam draws once.
  return slope(beyond(c - 1, i > 0, id, d * 1.03), beyond(c + 1, i < cols - 1, id, d * 0.97),
    beyond(c - cols, j > 0, id, d * 1.03), beyond(c + cols, j < rows - 1, id, d * 0.97));
}
// Silhouette glyph of the object you point at: its cells next to any cell that is not part of it.
function outline(c, i, j) {
  if (!target || SP[c] !== target) return null;
  const off = (n, inside) => !inside || SP[n] !== target;
  return slope(off(c - 1, i > 0), off(c + 1, i < cols - 1), off(c - cols, j > 0), off(c + cols, j < rows - 1));
}
// Keep unchanged rows. Desktop text runs keep their full-row origins; touch glyphs
// have independent positions, so only their changed runs and overhang need clearing.
let DG, DC, dpr = 1;
const BACKGROUND = "#060a14";
const snap = (v) => Math.round(v * dpr) / dpr;
// Puts what cell c shows this frame (the aim mark, the label leader, an outline or edge, else its glyph) in DG and
// DC; true when that changed. The scene leaves the mini map's cells blank.
function update(c, i, j, mid, onMap) {
  const aim = c === mid, hud = onMap && MAPCELLS.has(c);
  const mark = hud ? " " : aim ? "+" : (LINE.size && LINE.get(c)) || outline(c, i, j);
  const cls = hud ? "" : aim ? (target ? "h" : "k") : mark ? "h" : C[c], ch = mark || edge(c, i, j) || G[c];
  if (ch === DG[c] && cls === DC[c]) return false;
  DG[c] = ch; DC[c] = cls;
  return true;
}
// Draws the intro in full, then updates each whole row before painting and draws the mini map and sign above it.
function draw(mid) {
  if (introProgress < 1) {
    ctx.fillStyle = BACKGROUND;
    ctx.fillRect(0, 0, viewW, viewH);
    const tick = Math.floor(introProgress * 24);
    for (let j = 0; j < rows; j++) drawRow(mid, j, tick);
    ctx.fillStyle = "#000";
    ctx.globalAlpha = 1 - introProgress * introProgress;
    ctx.fillRect(0, 0, viewW, viewH);
    ctx.globalAlpha = 1;
    DG.fill(undefined);
    return;
  }
  if (DG[0] === undefined) {
    ctx.fillStyle = BACKGROUND;
    ctx.fillRect(0, 0, viewW, viewH);
  }
  forgetSign();
  const touch = touchFirst.matches;
  for (let j = 0; j < rows; j++) {
    const onMap = mapBox && j >= mapBox.oj && j < mapBox.oj + mapBox.h;
    let first = -1, last = -1;
    for (let i = 0; i < cols; i++) {
      if (!update(j * cols + i, i, j, mid, onMap)) continue;
      // Touch redraws each run of changed cells; runs fewer than five cells apart share one redraw.
      if (touch && first >= 0 && i - last > 4) { redraw(j, Math.max(0, first - 1), last + 1); first = -1; }
      if (first < 0) first = i;
      last = i;
    }
    if (first < 0) continue;
    if (touch) redraw(j, Math.max(0, first - 1), Math.min(cols - 1, last + 1));
    else redraw(j, 0, cols - 1);
  }
  drawMap();
  drawSign();
}
// The sign is drawn over the scene every frame, so the cells it covered draw again once it moves or closes.
let signDrawn = null;
function forgetSign() {
  const b = signDrawn, same = b && signBox && b.i === signBox.i && b.j === signBox.j && b.w === signBox.w && b.h === signBox.h;
  if (b && !same) {
    for (let j = Math.max(0, b.j); j < Math.min(rows, b.j + b.h); j++) DG.fill(undefined, j * cols + Math.max(0, b.i), j * cols + Math.min(cols, b.i + b.w));
  }
  signDrawn = signBox && { ...signBox };
}
function introDistance(i, j) {
  return i / cols * 0.75 + j / rows * 0.25 - (introProgress * 1.35 - 0.2);
}
function drawRow(mid, j, tick) {
  let run = "", cur = C[j * cols], from = 0;
  const tileRow = ((j + tick) & 7) << 3;
  for (let i = 0; i < cols; i++) {
    const c = j * cols + i, aim = c === mid;
    const distance = introDistance(i, j);
    const noise = distance > 0;
    const mark = noise ? null : aim ? "+" : LINE.get(c) || outline(c, i, j);
    const cls = noise ? distance < 0.08 ? "h" : "f" : aim ? (target ? "h" : "k") : mark ? "h" : C[c];
    const ch = noise ? INTRO_NOISE[tileRow + ((i + tick) & 7)] : mark || edge(c, i, j) || G[c];
    // The intro reuses desktop colour runs; touch draws only single glyphs without building runs.
    if (touchFirst.matches) { paint(ch, cls, i, j); continue; }
    if (cls !== cur) { paint(run, cur, from, j); run = ""; cur = cls; from = i; }
    run += ch;
  }
  paint(run, cur, from, j);
}
function redraw(j, i0, i1) {
  const x0 = snap(padX + i0 * cellW), x1 = snap(padX + (i1 + 1) * cellW), y0 = snap(padY + j * cellH), y1 = snap(padY + (j + 1) * cellH);
  ctx.save();
  ctx.beginPath(); ctx.rect(x0, y0, x1 - x0, y1 - y0); ctx.clip();
  ctx.fillStyle = BACKGROUND; ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
  const a = Math.max(0, i0 - 1), e = Math.min(cols - 1, i1 + 1);
  let run = "", cur = DC[j * cols + a], from = a;
  for (let i = a, c = j * cols + a; i <= e; i++, c++) {
    if (DC[c] !== cur) { paint(run, cur, from, j); run = ""; cur = DC[c]; from = i; }
    run += DG[c];
  }
  paint(run, cur, from, j);
  ctx.restore();
}
// The scene leaves the map's cells blank, so its backing (the background colour) and glyphs are drawn every frame.
function drawMap() {
  const b = mapBox;
  if (!b) return;
  const x0 = snap(padX + b.oi * cellW), x1 = snap(padX + (b.oi + b.w) * cellW), y0 = snap(padY + b.oj * cellH), y1 = snap(padY + (b.oj + b.h) * cellH);
  ctx.save();
  ctx.beginPath(); ctx.rect(x0, y0, x1 - x0, y1 - y0); ctx.clip();
  ctx.fillStyle = BACKGROUND; ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
  for (let j = b.oj; j < b.oj + b.h; j++) {
    let run = "", cur = "", from = b.oi;
    for (let i = b.oi; i < b.oi + b.w; i++) {
      const [ch, cls] = MAPCELLS.get(j * cols + i);
      if (cls !== cur) { paint(run, cur, from, j); run = ""; cur = cls; from = i; }
      run += ch;
    }
    paint(run, cur, from, j);
  }
  ctx.restore();
}
function drawSign() {
  if (!signBox) return;
  const { i, j, w, h } = signBox;
  ctx.fillStyle = "#060a14";
  ctx.fillRect(padX + i * cellW, padY + j * cellH, w * cellW, h * cellH);
  paint("+" + "-".repeat(w - 2) + "+", "t", i, j);
  const focused = signLinks.find(({ a }) => a.href === document.activeElement?.href);
  for (let n = 1; n < h - 1; n++) {
    paint("|", "t", i, j + n);
    paint("|", "t", i + w - 1, j + n);
  }
  signRows.forEach(([text, cls], n) => {
    const active = !touchFirst.matches && focused && n >= focused.start && n < focused.start + focused.height;
    if (active && signInset === 2) paint(">", "l", i + 1, j + n + 1);
    paint(text, active ? "l" : cls, i + signInset, j + n + 1);
  });
  if (touchFirst.matches) signLinks.forEach((link) => {
    paint(link.text, focused === link ? "l" : "h", i + link.left, j + 1 + link.row);
  });
  paint("+" + "-".repeat(w - 2) + "+", "t", i, j + h - 1);
}
// WebKit keeps every distinct string fillText draws: on iOS Safari runs of glyphs grow the tab by
// about 10 MB a second until iOS kills it. Touch devices draw glyph by glyph, a set of strings that stays small.
function paint(run, cls, i, j) {
  if (!run.trim()) return;
  ctx.fillStyle = COLORS[cls];
  if (!touchFirst.matches) ctx.fillText(run, padX + i * cellW, padY + j * cellH);
  else for (let k = 0; k < run.length; k++) if (run[k] !== " ") ctx.fillText(run[k], padX + (i + k) * cellW, padY + j * cellH);
}

function nearby() {
  if (interior) return null;
  let best = null, bd = 2.2;
  for (const [id, a] of Object.entries(anchors)) {
    const d = Math.hypot(a.x - me.x, a.z - me.z);
    if (d < bd && Math.abs(a.y + (a.ship ? bob : 0) - me.eye) < 5) { bd = d; best = id; }
  }
  return best;
}

// Cards are built from DOM nodes and text, never parsed from strings.
function node(tag, content, cls) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  n.append(...(Array.isArray(content) ? content : [content]));
  return n;
}

let shown;
function show(id) {
  const key = id || (moved ? "" : "welcome");
  if (key === shown) return;
  shown = key;
  target = id;
  signWidth = 0;
  if (!id) {
    if (moved) { card.replaceChildren(); return; }
    card.replaceChildren(
      node("h3", document.querySelector(".top h1").textContent),
      node("p", document.querySelector(".tagline").textContent),
      document.querySelector(".top nav").cloneNode(true));
    return;
  }
  const s = spots[id], link = node("a", id === "docsboard" ? "Docs index" : "Open");
  link.setAttribute("aria-label", `Open: ${s.title}`);
  link.target = "_blank";
  link.rel = "noopener";
  link.href = s.href;
  card.replaceChildren(node("h3", s.title), s.body.cloneNode(true), link);
}

// ---- Input -------------------------------------------------------------------------------
const KEYS = { KeyW: "f", ArrowUp: "f", KeyS: "b", ArrowDown: "b", KeyA: "l", KeyD: "r", ArrowLeft: "tl", ArrowRight: "tr",
  KeyR: "u", KeyF: "d" };
const open = () => { if (target) window.open(spots[target].href, "_blank", "noopener"); };
stage.addEventListener("keydown", (e) => {
  if (mapKey(e)) { e.preventDefault(); dirty = true; return; }
  if (e.key === "Enter" && target && !e.target.closest("a")) { e.preventDefault(); open(); return; }
  const k = KEYS[e.code];
  if (!k || e.altKey || e.ctrlKey || e.metaKey) return;
  e.preventDefault();
  keys.add(k);
});
stage.addEventListener("keyup", (e) => { keys.delete(KEYS[e.code]); releaseDoorInput(); });
stage.addEventListener("blur", () => { keys.clear(); releaseDoorInput(); });
const look = (dx, dy, k) => {
  me.yaw += dx * k;
  me.pitch = Math.max(-1.2, Math.min(1.2, me.pitch - dy * k));
  moved = true; jumped = null; walkPath = [];
  dirty = true;
};
// Grid links open on desktop and touch without starting mouse look.
canvas.addEventListener("click", (e) => {
  const link = signHit(e.clientX, e.clientY);
  if (link) { link.click(); return; }
  if (!mapMode && !touchFirst.matches && stage.requestPointerLock) stage.requestPointerLock();
  stage.focus({ preventScroll: true });
});
document.getElementById("page").addEventListener("focusin", (e) => {
  const id = e.target.closest("[data-spot]")?.dataset.spot;
  if (id && anchors[id]) {
    setMap(0); walkPath = []; walkTo = null;
    moved = true; face(id); dirty = true;
  }
});
card.addEventListener("focusin", () => {
  setMap(0); walkPath = []; walkTo = null;
  if (target) jumped = target;
  dirty = true;
});
document.addEventListener("mousemove", (e) => {
  if (document.pointerLockElement === stage) look(e.movementX, e.movementY, 0.0022);
  else hoverMap(e.clientX, e.clientY);
});
let padId = null, lookId = null, lastX = 0, lastY = 0;
function steer(e) {
  const r = pad.getBoundingClientRect(), half = r.width / 2;
  let x = (e.clientX - r.left - half) / half, y = (e.clientY - r.top - half) / half;
  const l = Math.hypot(x, y);
  if (l > 1) { x /= l; y /= l; }
  stick.x = x; stick.y = -y;
  releaseDoorInput();
  knob.style.transform = `translate(${x * half * 0.6}px, ${y * half * 0.6}px)`;
}
// Link presses do not dismiss the intro or start a touch drag.
stage.addEventListener("pointerdown", (e) => {
  if (e.target.closest("a") || signHit(e.clientX, e.clientY)) return;
  moved = true; dirty = true;
  if (tapMap(e.clientX, e.clientY)) return;
  if (e.pointerType === "mouse") return;
  if (pad.contains(e.target)) {
    padId = e.pointerId; steer(e);
  } else { lookId = e.pointerId; lastX = e.clientX; lastY = e.clientY; }
  stage.setPointerCapture(e.pointerId);
  e.preventDefault();
});
stage.addEventListener("pointermove", (e) => {
  if (e.pointerId === padId) steer(e);
  else if (e.pointerId === lookId) { look(e.clientX - lastX, e.clientY - lastY, 0.006); lastX = e.clientX; lastY = e.clientY; }
});
const release = (e) => {
  if (e.pointerId === padId) { padId = null; stick.x = stick.y = 0; knob.style.transform = ""; }
  if (e.pointerId === lookId) lookId = null;
  releaseDoorInput();
};
stage.addEventListener("pointerup", release);
stage.addEventListener("pointercancel", release);

function step(dt) {
  releaseDoorInput();
  const turn = (keys.has("tr") ? 1 : 0) - (keys.has("tl") ? 1 : 0);
  const tilt = (keys.has("u") ? 1 : 0) - (keys.has("d") ? 1 : 0);
  const fwd = (keys.has("f") ? 1 : 0) - (keys.has("b") ? 1 : 0) + stick.y;
  const side = (keys.has("r") ? 1 : 0) - (keys.has("l") ? 1 : 0) + stick.x;
  if (!turn && !tilt && !fwd && !side) return walkPath.length ? autoStep(dt) : false;
  moved = true; jumped = null; walkPath = [];
  me.yaw += turn * 1.9 * dt;
  me.pitch = Math.max(-1.2, Math.min(1.2, me.pitch + tilt * 1.2 * dt));
  const c = Math.cos(me.yaw), s = Math.sin(me.yaw), v = 3.4 * dt;
  const here = floorAt(me.x, me.z);
  movePlayer(me.x + (s * fwd + c * side) * v, me.z, here);
  movePlayer(me.x, me.z + (c * fwd - s * side) * v, here);
  return true;
}

// ---- Loop --------------------------------------------------------------------------------
let last = performance.now(), dirty = true, visible = true, slow = 0, fast = 0, layoutDirty = false, resizeTimer;
let refreshMs = Infinity, paintedLastFrame = false, probeMs = 0;
new IntersectionObserver(([e]) => { visible = e.isIntersecting; }).observe(stage);
const resize = new ResizeObserver(() => {
  if (stage.clientWidth === viewW && stage.clientHeight === viewH) return;
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { layoutDirty = true; dirty = true; }, 120);
});
reduced.addEventListener("change", () => { dirty = true; });
// Adaptive resolution: drop shadows, then grow glyphs; restore detail when frames run short.
function adaptResolution(ms, late) {
  slow = ms > 20 || late ? slow + 1 : 0;
  fast = ms < 9 && !late ? fast + 1 : 0;
  if (!interior) {
    if (slow > 20 && shadows) { shadows = false; slow = 0; dirty = true; }
    return;
  }
  if (slow > 20 && (shadows || scale < 2.2)) {
    if (shadows) shadows = false;
    else { scale *= 1.15; layoutDirty = dirty = true; }
    slow = 0;
  } else if (fast > 90 && scale > 1) {
    scale = Math.max(1, scale / 1.1); layoutDirty = dirty = true; fast = 0;
  }
}
function roomFrameLate(frameMs) {
  if (frameMs > 0) refreshMs = paintedLastFrame ? Math.min(frameMs, refreshMs * 1.001) : frameMs;
  const late = !!interior && (paintedLastFrame ? frameMs : probeMs) > refreshMs * 1.5;
  probeMs = Math.min(0, probeMs);
  paintedLastFrame = false;
  return late;
}
function advanceIntro(now, still) {
  if (introProgress === 1) return;
  if (introStart === null) introStart = now;
  introProgress = Math.min(1, (now - introStart) / 1200);
  if (still || introProgress === 1) finishIntro();
}
function frame(now) {
  const frameMs = now - last;
  const dt = Math.min(0.1, frameMs / 1000);
  const probing = probeMs > 0;
  const late = roomFrameLate(frameMs);
  last = now;
  const still = reduced.matches;
  advanceIntro(now, still);
  if (!still) T += dt;
  // The ship rides the swell too, gently: it is heavy, so half the wave height and a slow roll.
  if (still) { bob = 0; roll = 0; } else { seaNormal(SX, -2); bob = 0.5 * seaHeight(SX, -2) + 0.08 * Math.sin(T * 0.7); roll = -0.35 * Math.atan2(seaN[0], seaN[1]); }
  rc = Math.cos(roll); rs = Math.sin(roll);
  const walked = step(dt);
  // The room has no animated objects; repaint only after movement, looking, or resizing.
  if (visible && cols && (walked || dirty || (!interior && !still))) {
    if (probeMs < 0 || (late && slow % 20 === 0 && !probing)) {
      probeMs = frameMs;
      dirty = true;
      requestAnimationFrame(frame);
      return;
    }
    if (layoutDirty) { measure(); layoutDirty = false; }
    dirty = false;
    if (!interior) {
      setGangway();
      moveLights();
      floatBoats();
      swayTrees();
      billow();
    }
    me.eye = floorAt(me.x, me.z) + 1.6;
    const t0 = performance.now();
    render();
    const ms = performance.now() - t0;
    adaptResolution(ms, late);
    paintedLastFrame = true;
  }
  requestAnimationFrame(frame);
}
// Bob and roll change height, not walking topology. Build the corner graph before animation starts.
rebuildRoutes();
// A font that fails to load does not stop the scene.
document.fonts.load(`11px ${MONO}`).catch(() => {}).then(() => document.fonts.ready).then(() => {
  measure();
  resize.observe(stage);
  last = performance.now();
  requestAnimationFrame(frame);
});
