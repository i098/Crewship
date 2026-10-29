// The design's world for the mock: seed items, the scripted live events, and the agent's answers.
// Port of docs/genui/design/index.html ("initial world", say(), REL, script, ASK, askAbout, agentChoose).
// The spec is the only state: derive() turns it into the props the views show, so every change is one patch.
import type { BoardSpec, CardOpt, Component, PatchOp, Project } from "@crewship/genui-spec";
import { applyPatch, esc } from "../src/model";

export const PROJECTS: Record<string, Project> = {
  swap: { name: "swapapp", hsl: "hsl(188 95% 58%)" },
  crew: { name: "crewship", hsl: "hsl(262 92% 70%)" },
  bill: { name: "billing", hsl: "hsl(320 90% 66%)" },
  all: { name: "all projects", hsl: "hsl(152 72% 56%)" },
  plan: { name: "build plan", hsl: "hsl(38 98% 62%)" },
  host: { name: "this host", hsl: "hsl(210 90% 68%)" },
  me: { name: "you added", hsl: "hsl(48 96% 60%)" },
};

const REL: [string, string, string][] = [
  ["d1", "p1", "adds a migrate step"],
  ["d1", "t1", "Postgres adds a migrate day"],
  ["p1", "t1", "sets the ship time"],
  ["c1", "k1", "cf-auth waits on this"],
  ["i1", "k1", "cf-bill is fixing it"],
  ["i1", "t1", "billing slips"],
  ["d2", "t1", "sets the ship day"],
  ["cmp", "p1", "where #209 deploys"],
];

const CREW = [
  { name: "cf-auth", hsl: "hsl(262 92% 70%)", doing: "resolving #212 auth refresh" },
  { name: "cf-feed", hsl: "hsl(188 95% 58%)", doing: "#209 swap feed" },
  { name: "cf-bill", hsl: "hsl(320 90% 66%)", doing: "billing refunds" },
  { name: "cf-ops", hsl: "hsl(152 72% 56%)", doing: "watching the host" },
];

const item = (kind: string, proj: string, base: number, props: Record<string, unknown> = {}): Component => ({
  type: "card",
  props: { kind, proj, base, priority: base, ...props } as Component["props"],
});

const ITEMS = {
  i1: () =>
    item("incident", "bill", 70, {
      urgent: true, claim: "cf-bill", att: 1, title: "Refunds test failed on main", doneTitle: "Refunds test is green again",
      fix: { from: "refund = amount × 0.1", to: "refund = cents(amount, 10%)" },
    }),
  d2: () =>
    item("decision", "swap", 80, {
      need: true, q: "Ship swapapp Friday, or wait for billing?", why: "Billing slipped half a day",
      opts: [{ k: "fri", b: "Ship Friday", s: "Billing follows Monday", rec: true }, { k: "mon", b: "Wait for Monday", s: "One launch, both ready" }],
    }),
  cmp: () =>
    item("compare", "swap", 45, {
      title: "Vercel vs Fly for swapapp", a: "Vercel", b: "Fly", verdict: "Fly wins 2 of 4 · cheaper, more regions",
      rows: [{ name: "Cost / mo", a: 20, b: 12 }, { name: "Cold start", a: 9, b: 14 }, { name: "Deploy speed", a: 16, b: 11 }, { name: "Regions", a: 10, b: 18 }],
    }),
};

export function seedSpec(): BoardSpec {
  const spec: BoardSpec = {
    components: {
      header: { type: "header", props: { title: "", wins: "agent" } },
      input: { type: "input", props: { placeholder: "Ask anything, tell the AI what to do, or draw" } },
      d1: item("decision", "swap", 90, {
        need: true, q: "Store swaps in Postgres or SQLite?", why: "Blocks the swap feed migration",
        opts: [{ k: "pg", b: "Postgres", s: "Safe at scale · +1 day before ship", rec: true }, { k: "lite", b: "SQLite", s: "Ship today · migrate later (~6 h)" }],
      }),
      c1: item("conflict", "crew", 84, { need: true, title: "#212 auth refresh hit a conflict", doneTitle: "#212 is merged", branch: "#212", files: ["auth.ts", "middleware.ts"] }),
      p1: item("pipeline", "swap", 55, { title: "#209 swap feed", at: 2 }),
      t1: item("timeline", "all", 42, { title: "When things land", days: ["Wed", "Thu", "Fri", "Sat", "Mon"] }),
      k1: item("crew", "all", 34, { title: "Crew right now", crew: CREW, kpi: { value: CREW.length, unit: "active" } }),
      sh: item("shipped", "all", 20, { title: "Shipped in 14 days", shipped: 67 }),
      pl: item("plan", "plan", 60, {
        need: true, q: "Plan the build", kpi: { value: "~10", unit: "h build" },
        fields: [
          { name: "stack", legend: "Render stack", opts: [{ v: "jsonrender", b: "json-render + AI SDK" }, { v: "copilotkit", b: "CopilotKit" }, { v: "a2ui", b: "A2UI" }] },
          { name: "source", legend: "Talks to first", opts: [{ v: "fleet", b: "Firstmate + crew" }, { v: "general", b: "Any question" }] },
          { name: "cutoff", legend: "“…and there's n…”", opts: [{ v: "nobubbles", b: "No chat bubbles" }, { v: "nofixedscreens", b: "No fixed screens" }, { v: "noapp", b: "No install" }] },
        ],
      }),
      e1: item("embed", "swap", 50, { type: "site", title: "#209 preview", src: "/media/mock.html" }),
      e2: item("embed", "plan", 25, { type: "image", title: "Build stack", src: "/media/stack.svg", nat: "640/300" }),
      e3: item("embed", "plan", 20, { type: "video", title: "This board, rounds 3–7", src: "/media/rounds.mp4", nat: "1280/720" }),
      e5: item("embed", "plan", 22, { type: "diagram", title: "How it works", src: "/media/flow.svg", nat: "866/276" }),
    },
    links: [],
    tokens: {},
    projects: PROJECTS,
  };
  return applyPatch(spec, derive(spec, 0));
}

type P = Record<string, unknown>;
const props = (spec: BoardSpec, id: string): P | undefined => spec.components[id]?.props;
const live = (p: P | undefined) => !!p && p.removed !== true;

/** The header sentence for one item, `*…*` marking the emphasised run (design say()). */
function lineOf(spec: BoardSpec, p: P): string {
  if (p.done === true) return "Done. *Moving on.*";
  switch (p.kind) {
    case "decision": return `*Needs you:* ${p.q}`;
    case "conflict": return "*Needs you:* #212 hit a merge conflict. Pick how to merge.";
    case "incident": return "A billing test broke. *cf-bill claimed it;* you don't need to act.";
    case "compare": return "Fly beats Vercel on *3 of 4.* Your call.";
    case "pipeline": return `#209 is on *stage ${Number(p.at) + 1},* nothing needs you there.`;
    case "timeline": return `swapapp ships *${props(spec, "d2")?.pick === "mon" ? "Monday" : "Friday"}.*`;
    case "plan": return "*Needs you:* plan the build.";
    case "embed": return `*${p.title}*`;
    case "ask": return p.ready ? "Here is *what I found.*" : "Looking into *your question…*";
    default: return "*4 agents* are working right now.";
  }
}

/** Props that follow from the rest of the spec: stages, ship day, lines, priority, header, links. */
export function derive(spec: BoardSpec, tick: number): PatchOp[] {
  const want: Record<string, P> = {};
  const d1 = props(spec, "d1"), d2 = props(spec, "d2"), c1 = props(spec, "c1"), i1 = props(spec, "i1");
  const pg = d1?.pick === "pg", mon = d2?.pick === "mon";
  const stages = ["Code", "Build", "Tests", ...(pg ? ["Migrate"] : []), "Preview", "Merge"];
  const p1 = props(spec, "p1");
  if (p1) {
    const k = Math.min(Number(p1.at) || 0, stages.length - 1);
    const eta = Math.max(1, (stages.length - 1 - k) * 12 + (pg ? 25 : 0) - (tick % 2) * 6);
    want.p1 = { stages, at: k, kpi: { value: `~${eta}`, unit: "min" } };
  }
  if (props(spec, "t1")) {
    // one day is 25 units: Postgres's migrate day moves the ship from Fri to Sat; waiting for Monday covers it
    const shift = mon ? 46 : pg ? 25 : 0;
    want.t1 = {
      ship: mon ? "Mon 10:00" : pg ? "Sat 14:00" : "Fri 14:00",
      shipX: 54 + shift,
      now: Math.min(70, tick * 2),
      rows: [
        { name: "crewship", hsl: PROJECTS.crew.hsl, x: 0, w: 28 + (c1?.done ? -6 : 0) },
        { name: "swapapp", hsl: PROJECTS.swap.hsl, x: 8, w: 46 + shift },
        { name: "billing", hsl: PROJECTS.bill.hsl, x: 20, w: 40 + (i1 && i1.done !== true ? 10 : 0) },
      ],
    };
  }
  const sh = props(spec, "sh");
  if (sh) {
    const n = Number(sh.shipped) || 0;
    want.sh = { kpi: { value: n, unit: "PRs" }, days: [3, 5, 2, 6, 4, 0, 1, 7, 5, 8, 6, 4, 9, 7 + n - 67] };
  }
  const items = Object.entries(spec.components).filter(([, c]) => c.type === "card" && c.props.kind && live(c.props));
  for (const [id, c] of items) {
    const p = c.props as P;
    const priority = p.done === true ? 5 : Number(p.base) + (p.asked === true ? 200 : 0);
    want[id] = { ...want[id], priority, line: lineOf(spec, p) };
  }
  // header: the line of the top item, plus how many others wait on you
  const top = items.reduce<[string, Component] | undefined>((a, b) => (!a || Number(want[b[0]].priority) > Number(want[a[0]].priority) ? b : a), undefined);
  if (top && spec.components.header) {
    const more = items.filter(([id, c]) => id !== top[0] && c.props.need === true && c.props.done !== true).length;
    want.header = { title: String(want[top[0]].line) + (more ? ` *+${more} more* need${more > 1 ? "" : "s"} you.` : "") };
  }
  const patch: PatchOp[] = [];
  for (const [id, w] of Object.entries(want))
    for (const [k, v] of Object.entries(w))
      if (JSON.stringify(spec.components[id].props[k]) !== JSON.stringify(v)) patch.push({ op: "add", path: `/components/${esc(id)}/props/${k}`, value: v });
  // relations show while both ends are on the board; links you drew stay as they are
  const rel = (l: { from: string; to: string; label?: string }) => REL.some(([a, b]) => a === l.from && b === l.to && l.label);
  const links = [
    ...spec.links.filter((l) => !rel(l)),
    ...REL.filter(([a, b]) => live(props(spec, a)) && live(props(spec, b))).map(([from, to, label]) => ({ from, to, label })),
  ];
  if (JSON.stringify(links) !== JSON.stringify(spec.links)) patch.push({ op: "replace", path: "/links", value: links });
  return patch;
}

const set = (id: string, kv: P): PatchOp[] => Object.entries(kv).map(([k, value]) => ({ op: "add", path: `/components/${esc(id)}/props/${k}`, value }));
const add = (id: string, c: Component): PatchOp[] => [{ op: "add", path: `/components/${esc(id)}`, value: c }];

/** Card acts that settle an item (data-act on a view, sent as an input intent field). */
const SETTLES = /^(pick|merge|fly|dismiss|send)$/;

/** Where an ask came from: the card open in full view, the selection, or a box drawn on the board. */
export type About = { of?: string; ids?: string[]; at?: { x: number; y: number; w: number; h: number } };

const ASK: [RegExp, (w: World) => PatchOp[]][] = [
  [/compare|vercel|fly|vs/i, (w) => [...(w.has("cmp") ? set("cmp", { removed: false, done: false }) : add("cmp", ITEMS.cmp())), ...w.front("cmp")]],
  [/when|ship|eta|land/i, (w) => w.front("t1")],
  [/who|crew|working/i, (w) => w.front("k1")],
];

/** One board's live world: the design's script on a clock, and the agent's replies to what you do. */
export class World {
  tick = 0;
  private n = 0;
  private timers: Timer[] = [];

  constructor(
    private spec: () => BoardSpec,
    private commit: (cause: string, patch: PatchOp[]) => void,
  ) {}

  /** Apply `patch` and everything that follows from it, as one agent op. */
  change(cause: string, patch: PatchOp[] = []) {
    const next = patch.length ? applyPatch(this.spec(), patch) : this.spec();
    const all = [...patch, ...derive(next, this.tick)];
    if (all.length) this.commit(cause, all);
  }

  has = (id: string) => live(props(this.spec(), id));

  /** Bring `id` to the front of its cluster; asks are cleared and set in one step (design run()). */
  front(id: string): PatchOp[] {
    const others = Object.entries(this.spec().components).filter(([k, c]) => k !== id && c.props.asked === true);
    return [...others.flatMap(([k]) => set(k, { asked: false })), ...set(id, { asked: true })];
  }

  private at(s: number, f: () => void) {
    const t = setTimeout(f, s * 1000);
    t.unref(); // a mock clock must never keep a test process alive
    this.timers.push(t);
  }

  private finish(id: string) {
    this.change(`world:done:${id}`, set(id, { done: true }));
    this.at(2.5, () => this.change(`world:gone:${id}`, set(id, { removed: true })));
  }

  /** The scripted live world (design `script` and the 6 s clock). */
  start() {
    const step = (k: number) => () => this.change("world:stage", set("p1", { at: k }));
    this.at(6, step(3));
    this.at(15, () => this.change("world:i1", add("i1", ITEMS.i1())));
    this.at(21, () => this.change("world:i1", set("i1", { att: 2 })));
    this.at(27, () => this.change("world:i1", set("i1", { att: 3 })));
    this.at(32, () => this.finish("i1"));
    this.at(38, () => this.change("world:d2", add("d2", ITEMS.d2())));
    this.at(44, step(4));
    const clock = setInterval(() => {
      this.tick++;
      const p1 = props(this.spec(), "p1");
      if (this.tick >= 8 && this.tick % 2 === 0 && p1 && p1.done !== true) {
        const last = (p1.stages as string[]).length - 1;
        if (Number(p1.at) < last) return this.change("world:stage", set("p1", { at: Number(p1.at) + 1 }));
        this.finish("p1");
        return this.change("world:shipped", set("sh", { shipped: Number(props(this.spec(), "sh")?.shipped) + 1 }));
      }
      this.change("world:tick");
    }, 6000);
    clock.unref();
    this.timers.push(clock);
    return this;
  }

  stop() {
    for (const t of this.timers) clearTimeout(t);
  }

  /** After a user's input intent: a card act settles its item. */
  react(id: string, field: unknown) {
    if (typeof field === "string" && SETTLES.test(field) && this.has(id)) this.finish(id);
    else this.change(`world:${id}`);
  }

  /** The agent's answer to a typed ask (design agentChoose, run(ASK), askAbout). */
  answer(text: string, about: About = {}) {
    const spec = this.spec();
    const ids = (about.ids ?? []).filter((i) => live(props(spec, i)));
    const ctx = about.of && live(props(spec, about.of)) ? about.of : ids[0];
    const proj = String((ctx && props(spec, ctx)?.proj) ?? "me");
    const s = text.trim().replace(/[?.!]+$/, "").slice(0, 400);
    // anything with two readings comes back as a choice to tap, not a guess
    const parts = s.replace(/^(should|shall|do|can|would|will)\s+(we|i|you|it)\s+/i, "").split(/,?\s+or\s+/i).map((p) => p.trim()).filter(Boolean);
    const yn = /^(should|shall)\s+(we|i)\b/i.test(s);
    if (parts.length > 1 || yn) {
      const opts: CardOpt[] = parts.length > 1
        ? parts.slice(0, 4).map((p, i) => ({ k: `o${i}`, b: p[0].toUpperCase() + p.slice(1, 40), rec: !i }))
        : [{ k: "y", b: "Yes", rec: true }, { k: "n", b: "No" }];
      const id = `q${++this.n}`;
      return this.change(`ask:${id}`, [...add(id, item("decision", proj, 95, { need: true, q: text.slice(0, 200), opts, of: about.of })), ...this.front(id)]);
    }
    const hit = !ctx && !about.at && ASK.find(([re]) => re.test(s));
    if (hit) return this.change("ask", hit[1](this));
    // the answer joins the cluster it is about and comes to its front, so it is on screen (D47)
    const id = `a${++this.n}`;
    const at = about.at && { x: Number(about.at.x) || 0, y: Number(about.at.y) || 0, w: Number(about.at.w) || 0 }; // client input
    const extra: Partial<Component> = at ? { rect: { x: Math.round(at.x + at.w + 24), y: Math.round(at.y), w: 300, h: 200 } } : {};
    const names = [...(about.of ? [about.of] : []), ...ids].map((i) => { const p = props(spec, i)!; return String(p.q ?? p.title ?? p.kind); });
    const c = item("ask", proj, 95, { q: s, about: names, ready: false, of: about.of, pinned: about.at ? true : undefined });
    this.change(`ask:${id}`, [...add(id, { ...c, ...extra }), ...(about.at || about.of ? [] : this.front(id))]);
    this.at(2.2, () => this.has(id) && this.change(`ask:${id}:ready`, set(id, { ready: true })));
  }
}
