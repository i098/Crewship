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
      title: "Vercel vs Fly for swapapp", a: "Vercel", b: "Fly", subject: "swapapp", verdict: "Fly wins 2 of 4 · cheaper, more regions",
      metrics: [["Cost / mo", 20, 12], ["Cold start", 9, 14], ["Deploy speed", 16, 11], ["Regions", 10, 18]],
      acts: [{ k: "fly", b: "Go with Fly", pri: true }, { k: "dismiss", b: "Dismiss" }],
    }),
};

/** The design's ask chips. */
const CHIPS = ["Compare Vercel vs Fly for swapapp", "When does swapapp ship?", "Who's working on what?", "What's going on?", "Open the first plan board"];

/** 30 host samples per stat (0-100), the design's sample() curves without its noise. */
function hostStats(): Record<string, number[]> {
  const at = (f: (c: number) => number) => Array.from({ length: 30 }, (_, i) => Math.round(Math.max(1, Math.min(99, f(i + 1)))));
  return { cpu: at((c) => 47 + 22 * Math.sin(c / 4)), mem: at((c) => 61 + 4 * Math.sin(c / 15)), disk: at((c) => 72 + c / 400), net: at((c) => 26 + 12 * Math.sin(c / 3)) };
}

export function seedSpec(): BoardSpec {
  const spec: BoardSpec = {
    components: {
      header: { type: "header", props: { title: "", wins: "agent", stats: hostStats(), tuis: CREW.map((c, i) => ({ name: c.name, proj: ["crew", "swap", "bill", "all"][i] })) } },
      input: { type: "input", props: { placeholder: "Ask anything, tell the AI what to do, ✎ draw or ＋ upload", chips: CHIPS } },
      d1: item("decision", "swap", 90, {
        need: true, q: "Store swaps in Postgres or SQLite?", why: "Blocks the swap feed migration",
        opts: [{ k: "pg", b: "Postgres", s: "Safe at scale · +1 day before ship", rec: true }, { k: "lite", b: "SQLite", s: "Ship today · migrate later (~6 h)" }],
      }),
      c1: item("conflict", "crew", 84, { need: true, title: "#212 auth refresh hit a conflict", doneTitle: "#212 is merged", branch: "#212", files: ["auth.ts", "middleware.ts"] }),
      p1: item("pipeline", "swap", 55, { title: "#209 swap feed", at: 2 }),
      t1: item("timeline", "all", 42, { title: "When things land", days: ["Wed", "Thu", "Fri", "Sat", "Mon"] }),
      k1: item("crew", "all", 34, { title: "Crew right now", members: CREW }),
      sh: item("shipped", "all", 20, { title: "Shipped in 14 days", shipped: 67 }),
      pl: item("plan", "plan", 60, {
        need: true, title: "Plan the build", kpi: { value: "~10", unit: "h build" },
        fields: [
          { name: "stack", label: "Render stack", opts: [["jsonrender", "json-render + AI SDK"], ["copilotkit", "CopilotKit"], ["a2ui", "A2UI"]] },
          { name: "source", label: "Talks to first", opts: [["fleet", "Firstmate + crew"], ["general", "Any question"]] },
          { name: "cutoff", label: "“…and there's n…”", opts: [["nobubbles", "No chat bubbles"], ["nofixedscreens", "No fixed screens"], ["noapp", "No install"]] },
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

/** Pipeline, timeline and shipped props from the picks, the script state and the clock. */
function statusProps(spec: BoardSpec, tick: number): Record<string, P> {
  const want: Record<string, P> = {};
  const c1 = props(spec, "c1"), i1 = props(spec, "i1"), p1 = props(spec, "p1"), sh = props(spec, "sh");
  const pg = props(spec, "d1")?.pick === "pg", mon = props(spec, "d2")?.pick === "mon";
  const stages = ["Code", "Build", "Tests", ...(pg ? ["Migrate"] : []), "Preview", "Merge"];
  if (p1) {
    const k = Math.min(Number(p1.at) || 0, stages.length - 1);
    const eta = Math.max(1, (stages.length - 1 - k) * 12 + (pg ? 25 : 0) - (tick % 2) * 6);
    want.p1 = { stages, at: k, kpi: { value: `~${eta}`, unit: "min" } };
  }
  // one day is 25 units: Postgres's migrate day moves the ship from Fri to Sat; waiting for Monday covers it.
  // the view takes days, so every unit value is divided by 25
  const shift = mon ? 46 : pg ? 25 : 0;
  if (props(spec, "t1"))
    want.t1 = {
      subject: "swapapp",
      ship: mon ? "Mon 10:00" : pg ? "Sat 14:00" : "Fri 14:00",
      shipAt: (54 + shift) / 25,
      shipRow: 1,
      now: Math.min(70, 13 + tick * 2) / 25,
      rows: [
        { name: "crewship", hsl: PROJECTS.crew.hsl, from: 0, len: (28 + (c1?.done ? -6 : 0)) / 25 },
        { name: "swapapp", hsl: PROJECTS.swap.hsl, from: 8 / 25, len: (46 + shift) / 25 },
        { name: "billing", hsl: PROJECTS.bill.hsl, from: 20 / 25, len: (40 + (i1 && i1.done !== true ? 10 : 0)) / 25 },
      ],
    };
  const n = Number(sh?.shipped) || 0;
  if (sh) want.sh = { total: n, bars: [3, 5, 2, 6, 4, 0, 1, 7, 5, 8, 6, 4, 9, 7 + n - 67] };
  return want;
}

/** Each live item's priority and line, and the header: the top item's line plus how many others wait on you. */
function lineProps(spec: BoardSpec): Record<string, P> {
  const want: Record<string, P> = {};
  const items = Object.entries(spec.components).filter(([, c]) => c.type === "card" && c.props.kind && live(c.props));
  for (const [id, { props: p }] of items)
    want[id] = { priority: p.done === true ? 5 : Number(p.base) + (p.asked === true ? 200 : 0), line: lineOf(spec, p) };
  const top = items.reduce<string | undefined>((a, [id]) => (!a || Number(want[id].priority) > Number(want[a].priority) ? id : a), undefined);
  if (!top || !spec.components.header) return want;
  const more = items.filter(([id, c]) => id !== top && c.props.need === true && c.props.done !== true).length;
  want.header = { title: String(want[top].line) + (more ? ` *+${more} more* need${more > 1 ? "" : "s"} you.` : "") };
  return want;
}

/** Relations show while both ends are on the board; links you drew stay as they are. */
function linksOf(spec: BoardSpec) {
  const rel = (l: { from: string; to: string; label?: string }) => REL.some(([a, b]) => a === l.from && b === l.to && l.label);
  return [
    ...spec.links.filter((l) => !rel(l)),
    ...REL.filter(([a, b]) => live(props(spec, a)) && live(props(spec, b))).map(([from, to, label]) => ({ from, to, label })),
  ];
}

/** Props that follow from the rest of the spec: stages, ship day, lines, priority, header, links. */
export function derive(spec: BoardSpec, tick: number): PatchOp[] {
  const status = statusProps(spec, tick), lines = lineProps(spec);
  const patch: PatchOp[] = [];
  for (const id of new Set([...Object.keys(status), ...Object.keys(lines)]))
    for (const [k, v] of Object.entries({ ...status[id], ...lines[id] }))
      if (JSON.stringify(spec.components[id].props[k]) !== JSON.stringify(v)) patch.push({ op: "add", path: `/components/${esc(id)}/props/${k}`, value: v });
  const links = linksOf(spec);
  if (JSON.stringify(links) !== JSON.stringify(spec.links)) patch.push({ op: "replace", path: "/links", value: links });
  return patch;
}

const set = (id: string, kv: P): PatchOp[] => Object.entries(kv).map(([k, value]) => ({ op: "add", path: `/components/${esc(id)}/props/${k}`, value }));
const add = (id: string, c: Component): PatchOp[] => [{ op: "add", path: `/components/${esc(id)}`, value: c }];

/** Card acts that settle an item (data-act on a view, sent as an input intent field). */
const SETTLES = /^(pick|merge|act|send)$/;

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

  /** A header pill opens the host stats ("sys") or an agent's terminal ("tui-<name>") as a card in front. */
  open(what: string) {
    const i = CREW.findIndex((c) => `tui-${c.name}` === what);
    if (what !== "sys" && i < 0) return;
    const card =
      i < 0
        ? item("sys", "host", 95, { title: "This host", series: props(this.spec(), "header")?.stats ?? hostStats() })
        : item("tui", ["crew", "swap", "bill", "all"][i], 95, { title: CREW[i].name, agent: CREW[i].name, lines: [`00:00  ${CREW[i].doing}`] });
    this.change(`open:${what}`, [...(this.has(what) ? set(what, { removed: false, done: false }) : add(what, card)), ...this.front(what)]);
  }

  /** The agent's answer to a typed ask (design agentChoose, run(ASK), askAbout). */
  answer(text: string, about: About = {}) {
    const spec = this.spec();
    const ids = (about.ids ?? []).filter((i) => live(props(spec, i)));
    const ctx = about.of && live(props(spec, about.of)) ? about.of : ids[0];
    const proj = String((ctx && props(spec, ctx)?.proj) ?? "me");
    const s = text.trim().replace(/[?.!]+$/, "").slice(0, 400);
    const opts = choiceOpts(s);
    if (opts) {
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

/** Anything with two readings comes back as a choice to tap, not a guess: "a or b", or a yes/no "should we". */
function choiceOpts(s: string): CardOpt[] | undefined {
  const parts = s.replace(/^(should|shall|do|can|would|will)\s+(we|i|you|it)\s+/i, "").split(/,?\s+or\s+/i).map((p) => p.trim()).filter(Boolean);
  if (parts.length > 1) return parts.slice(0, 4).map((p, i) => ({ k: `o${i}`, b: p[0].toUpperCase() + p.slice(1, 40), rec: !i }));
  if (/^(should|shall)\s+(we|i)\b/i.test(s)) return [{ k: "y", b: "Yes", rec: true }, { k: "n", b: "No" }];
}
