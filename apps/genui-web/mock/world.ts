// The design's world for the mock: seed items, the scripted live events, and the agent's answers.
// Port of docs/genui/design/index.html ("initial world", say(), REL, script, ASK, askAbout, agentChoose, sample, logA).
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

/** The crew's terminals: project (its colour) and the lines each one cycles through (design AG, AGC). */
const AG: Record<string, { proj: string; lines: string[] }> = {
  "cf-auth": { proj: "crew", lines: ["git rebase main", "conflict: auth.ts", "tests 41/212", "tests 212/212 ok", "push #212"] },
  "cf-feed": { proj: "swap", lines: ["build #209", "tests 120/212", "preview deploy", "wait for review"] },
  "cf-bill": { proj: "bill", lines: ["repro refunds", "patch cents()", "tests 212/212 ok", "open #214"] },
  "cf-ops": { proj: "all", lines: ["watch deploys", "preview ok", "cert renews in 21d", "idle"] },
};

const hash = (s: string) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 9973, 7);
const mmss = (c: number) => `${String((c / 60) | 0).padStart(2, "0")}:${String(c % 60).padStart(2, "0")}`;

/** Fake host stats and terminal lines at clock second `c` (design sample()): the last 30 samples, the last 20 lines. */
export function hostAt(c: number) {
  const stats: Record<string, number[]> = { cpu: [], mem: [], disk: [], net: [] };
  for (let i = Math.max(1, c - 29); i <= c; i++) {
    const v = { cpu: 40 + 22 * Math.sin(i / 4) + (hash(i + "c") % 14), mem: 61 + 4 * Math.sin(i / 15), disk: 72 + i / 400, net: 18 + 12 * Math.sin(i / 3) + (hash(i + "n") % 16) };
    for (const [k, x] of Object.entries(v)) stats[k].push(Math.round(Math.max(1, Math.min(99, x))));
  }
  const logs = Object.fromEntries(
    Object.entries(AG).map(([n, a], j) => {
      const ls: string[] = [];
      for (let i = 1; i <= c; i++) if ((i + j) % 3 === 0) ls.push(`${mmss(i)}  ${a.lines[((i / 3) | 0) % a.lines.length]}`);
      return [n, ls.slice(-20)];
    }),
  );
  return { stats, logs };
}

/** The clock second the world starts at: the design samples 30 times before the first paint. */
const CLOCK0 = 30;

const item = (kind: string, proj: string, base: number, props: Record<string, unknown> = {}): Component => ({
  type: "card",
  props: { kind, proj, base, priority: base, ...props } as Component["props"],
});

const ITEMS: Record<string, () => Component> = {
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
  e4: () => item("embed", "plan", 40, { type: "board", title: "First plan board", src: "/media/plan.html" }),
  sys: () => item("sys", "host", 30, { title: "This host" }),
};

const tuiItem = (name: string) => item("tui", "host", 30, { agent: name, title: name, lines: [] });

type P = Record<string, unknown>;
const props = (spec: BoardSpec, id: string): P | undefined => spec.components[id]?.props;
const live = (p: P | undefined) => !!p && p.removed !== true;
const nameOf = (p: P) => String(p.q ?? p.title ?? { crew: "Crew right now", shipped: "Shipped in 14 days", timeline: "When things land" }[String(p.kind)] ?? p.kind);

/** One action-log row; `seq` names it for rewind, `op` is the user op it undoes, `made` marks a card the action added. */
type LogItem = { at: number; text: string; proj?: string; seq: number; rwd?: boolean; id?: string; op?: number; made?: boolean };

export function seedSpec(): BoardSpec {
  const { stats } = hostAt(CLOCK0);
  const spec: BoardSpec = {
    components: {
      header: { type: "header", props: { title: "", wins: "agent", stats, tuis: Object.entries(AG).map(([name, a]) => ({ name, proj: a.proj })) } },
      input: { type: "input", props: { chips: ASK.map((a) => a[1]) } },
      log: { type: "log", props: { items: [] } },
      d1: item("decision", "swap", 90, {
        need: true, q: "Store swaps in Postgres or SQLite?", why: "Blocks the swap feed migration",
        opts: [{ k: "pg", b: "Postgres", s: "Safe at scale · +1 day before ship", rec: true }, { k: "lite", b: "SQLite", s: "Ship today · migrate later (~6 h)" }],
      }),
      c1: item("conflict", "crew", 84, { need: true, title: "#212 auth refresh hit a conflict", doneTitle: "#212 is merged", branch: "#212", files: ["auth.ts", "middleware.ts"] }),
      p1: item("pipeline", "swap", 55, { title: "#209 swap feed", at: 2 }),
      t1: item("timeline", "all", 42, { title: "When things land", days: ["Wed", "Thu", "Fri", "Sat", "Mon"] }),
      k1: item("crew", "all", 34, { title: "Crew right now", kpi: { value: Object.keys(AG).length, unit: "active" } }),
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
  const cards = Object.values(spec.components).filter((c) => c.type === "card");
  spec.components.log.props.items = cards.map((c, i): LogItem => ({ at: 0, text: `New: ${nameOf(c.props)}`, proj: c.props.proj, seq: i + 1 }));
  return applyPatch(spec, [...derive(spec, 0), ...hostPatch(spec, CLOCK0)]);
}

/** Header stats, each terminal card's lines, and what each crew member is doing, at clock second `c`. */
function hostPatch(spec: BoardSpec, c: number): PatchOp[] {
  const { stats, logs } = hostAt(c);
  const patch: PatchOp[] = [{ op: "add", path: "/components/header/props/stats", value: stats }];
  const crew = Object.entries(AG).map(([name, a]) => ({ name, hsl: PROJECTS[a.proj].hsl, doing: (logs[name].at(-1) ?? "idle").replace(/^\S+\s+/, "") }));
  if (props(spec, "k1")) patch.push(...set("k1", { crew }));
  for (const name of Object.keys(AG)) if (live(props(spec, `tui-${name}`))) patch.push(...set(`tui-${name}`, { lines: logs[name] }));
  return patch;
}

/** The header sentence for one item, `*…*` marking the emphasised run (design say()). */
function lineOf(spec: BoardSpec, p: P): string {
  if (p.done === true) return "Done. *Moving on.*";
  const stats = (props(spec, "header")?.stats ?? {}) as Record<string, number[]>;
  switch (p.kind) {
    case "decision": return `*Needs you:* ${p.q}`;
    case "conflict": return "*Needs you:* #212 hit a merge conflict. Pick how to merge.";
    case "incident": return "A billing test broke. *cf-bill claimed it;* you don't need to act.";
    case "compare": return "Fly beats Vercel on *3 of 4.* Your call.";
    case "pipeline": return `#209 is on *stage ${Number(p.at) + 1},* nothing needs you there.`;
    case "timeline": return `swapapp ships *${props(spec, "d2")?.pick === "mon" ? "Monday" : "Friday"}.*`;
    case "plan": return "*Needs you:* plan the build.";
    case "embed": return `*${p.title}*`;
    case "sys": return `Host: *cpu ${stats.cpu?.at(-1)}%,* mem ${stats.mem?.at(-1)}%.`;
    case "tui": return `*${p.agent}* live.`;
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
    want.p1 = { stages, at: k, kpi: { value: `~${eta}`, unit: "min" }, next: k < stages.length - 1 ? `#209 → ${stages[k + 1]}` : undefined };
  }
  // one day is 25 units: Postgres's migrate day moves the ship from Fri to Sat; waiting for Monday covers it
  const shift = mon ? 46 : pg ? 25 : 0;
  const ship = mon ? "Mon 10:00" : pg ? "Sat 14:00" : "Fri 14:00";
  if (props(spec, "t1"))
    want.t1 = {
      ship,
      next: `swapapp ships ${ship}`,
      shipX: 54 + shift,
      now: Math.min(70, tick * 2),
      rows: [
        { name: "crewship", hsl: PROJECTS.crew.hsl, x: 0, w: 28 + (c1?.done ? -6 : 0) },
        { name: "swapapp", hsl: PROJECTS.swap.hsl, x: 8, w: 46 + shift },
        { name: "billing", hsl: PROJECTS.bill.hsl, x: 20, w: 40 + (i1 && i1.done !== true ? 10 : 0) },
      ],
    };
  const n = Number(sh?.shipped) || 0;
  if (sh) want.sh = { kpi: { value: n, unit: "PRs" }, days: [3, 5, 2, 6, 4, 0, 1, 7, 5, 8, 6, 4, 9, 7 + n - 67] };
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

/** What the log says for a card act (data-act on a view, sent as an input intent field); the act settles its item. */
const SETTLES: Record<string, (p: P, k: unknown) => string> = {
  pick: (p, k) => `You picked ${(p.opts as CardOpt[] | undefined)?.find((o) => o.k === k)?.b ?? k}: ${p.q}`,
  merge: (p, k) => `You chose ${{ ai: "Keep both", theirs: "Take main", mine: "Keep mine" }[String(k)] ?? k}: ${p.title}`,
  fly: () => "You chose: Move swapapp to Fly",
  dismiss: () => "You chose: Keep Vercel",
  send: (p) => `You sent: ${p.q}`,
};

/** Where an ask came from: the card open in full view, the selection, or a box drawn on the board. */
export type About = { of?: string; ids?: string[]; at?: { x: number; y: number; w: number; h: number } };

/** The ask chips and what each brings forward (design ASK); the label is the chip text. */
const ASK: [RegExp, string, (w: World) => PatchOp[], string?][] = [
  [/compare|vercel|fly|vs/i, "Compare Vercel vs Fly for swapapp", (w) => w.bring("cmp"), "cmp"],
  [/when|ship|eta|land/i, "When does swapapp ship?", (w) => w.front("t1")],
  [/who|crew|working/i, "Who's working on what?", (w) => w.front("k1")],
  [/going on|status|overview|what/i, "What's going on?", () => []],
  [/board|plan/i, "Open the first plan board", (w) => w.bring("e4"), "e4"],
];

/** One board's live world: the design's script on a clock, and the agent's replies to what you do. */
export class World {
  tick = 0;
  private n = 0;
  private logSeq = 0;
  private clock = CLOCK0;
  private t0 = Date.now();
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

  /** Put a known card back on the board (or make it) and bring it to the front. */
  bring(id: string, make = ITEMS[id]): PatchOp[] {
    const back = props(this.spec(), id) ? set(id, { removed: false, done: false }) : add(id, make());
    return [...back, ...this.front(id)];
  }

  /** A row for the action log (design logA), timed from when the board opened. */
  log(text: string, proj?: unknown, extra: Partial<LogItem> = {}): PatchOp[] {
    const items = props(this.spec(), "log")?.items as LogItem[] | undefined;
    if (!items) return [];
    this.logSeq = Math.max(this.logSeq, items.length) + 1; // several rows can go out in one change
    const value: LogItem = { at: Math.round((Date.now() - this.t0) / 1000), text, proj: proj == null ? undefined : String(proj), seq: this.logSeq, ...extra };
    return [{ op: "add", path: "/components/log/props/items/-", value }];
  }

  private at(s: number, f: () => void) {
    const t = setTimeout(f, s * 1000);
    t.unref(); // a mock clock must never keep a test process alive
    this.timers.push(t);
  }

  private arrive(id: string, extra: PatchOp[] = []) {
    const c = ITEMS[id]();
    this.change(`world:${id}`, [...add(id, c), ...extra, ...this.log(`New: ${nameOf(c.props)}`, c.props.proj)]);
  }

  private stage(k: number) {
    const st = (props(this.spec(), "p1")?.stages ?? []) as string[];
    this.change("world:stage", [...set("p1", { at: k }), ...this.log(`#209 moved to ${String(st[Math.min(k, st.length - 1)]).toLowerCase()}`, "swap")]);
  }

  /** Settle `id`; `said` is the log row for it (default "Done: …"), `first` any other change that goes with it. */
  private finish(id: string, first: PatchOp[] = [], said?: PatchOp[]) {
    const p = props(this.spec(), id)!;
    this.change(`world:done:${id}`, [...first, ...set(id, { done: true }), ...(said ?? this.log(`Done: ${nameOf(p)}`, p.proj))]);
    // a done item shows its result, then leaves, unless a rewind brought it back meanwhile
    this.at(2.5, () => props(this.spec(), id)?.done === true && this.change(`world:gone:${id}`, set(id, { removed: true })));
  }

  /** The scripted live world (design `script`), the 1 s host sampler and the 6 s clock. */
  start() {
    this.at(6, () => this.stage(3));
    this.at(15, () => this.arrive("i1", this.log("cf-bill claimed: Refunds test failed on main", "bill")));
    this.at(21, () => this.change("world:i1", [...set("i1", { att: 2 }), ...this.log("cf-bill: fix attempt 2", "bill")]));
    this.at(27, () => this.change("world:i1", [...set("i1", { att: 3 }), ...this.log("cf-bill: fix attempt 3", "bill")]));
    this.at(32, () => this.finish("i1"));
    this.at(38, () => this.arrive("d2"));
    this.at(44, () => this.stage(4));
    this.every(1, () => this.change("world:host", hostPatch(this.spec(), ++this.clock)));
    this.every(6, () => this.clockTick());
    return this;
  }

  private every(s: number, f: () => void) {
    const t = setInterval(f, s * 1000);
    t.unref();
    this.timers.push(t);
  }

  /** The world keeps moving after the script: #209 walks to merge, and the shipped count goes up. */
  private clockTick() {
    this.tick++;
    const p1 = props(this.spec(), "p1");
    if (this.tick < 8 || this.tick % 2 || !p1 || p1.done === true) return this.change("world:tick");
    if (Number(p1.at) < (p1.stages as string[]).length - 1) return this.stage(Number(p1.at) + 1);
    this.finish("p1", set("sh", { shipped: Number(props(this.spec(), "sh")?.shipped) + 1 }));
  }

  stop() {
    for (const t of this.timers) clearTimeout(t);
  }

  /** After a user's input intent `op`: a card act settles its item and goes in the log. */
  react(id: string, field: unknown, value: unknown, op?: number) {
    const p = props(this.spec(), id);
    const says = typeof field === "string" && Object.hasOwn(SETTLES, field) ? SETTLES[field] : undefined;
    if (!says || !p || !live(p)) return this.change(`world:${id}`);
    this.finish(id, [], this.log(says(p, value), p.proj, { id, op }));
  }

  /** A tap on a header stat or terminal pill opens a live view of it in the host cluster. */
  open(what: string) {
    const name = what.startsWith("tui-") ? what.slice(4) : undefined;
    if (what !== "sys" && !(name && Object.hasOwn(AG, name))) return;
    this.change(`open:${what}`, [...this.bring(what, name ? () => tuiItem(name) : ITEMS.sys), ...this.log(`You opened ${name ?? "host stats"}`, "host", { id: what, made: true })]);
    if (name) this.change("world:host", hostPatch(this.spec(), this.clock));
  }

  /** Rewind one log row: take back the user op it names (via `inverse`) and reopen its card, or drop the card it made. */
  rewind(seq: number, inverse: (op: number) => PatchOp[] | undefined) {
    const items = (props(this.spec(), "log")?.items ?? []) as LogItem[];
    const i = items.findIndex((e) => e.seq === seq && !e.rwd && e.id);
    if (i < 0) return;
    const e = items[i], undo = e.op === undefined ? undefined : inverse(e.op);
    const card = e.made ? set(e.id!, { removed: true }) : set(e.id!, { done: false, removed: false });
    const mark = [{ op: "add", path: `/components/log/props/items/${i}/rwd`, value: true } as PatchOp, ...this.log(`Rewound: ${e.text}`, e.proj)];
    try {
      this.change(`rewind:${seq}`, [...(undo ?? []), ...card, ...mark]);
    } catch {
      this.change(`rewind:${seq}`, [...card, ...mark]); // a later change took the op's paths; the card still comes back
    }
  }

  /** The agent's answer to a typed ask `op` (design agentChoose, run(ASK), askAbout). */
  answer(text: string, about: About = {}) {
    const spec = this.spec();
    const ids = (about.ids ?? []).filter((i) => live(props(spec, i)));
    const ctx = about.of && live(props(spec, about.of)) ? about.of : ids[0];
    const proj = String((ctx && props(spec, ctx)?.proj) ?? "me");
    const s = text.trim().replace(/[?.!]+$/, "").slice(0, 400);
    const opts = choiceOpts(s);
    if (opts) {
      const id = `q${++this.n}`;
      const asked = this.log(`You asked: ${s}`, proj, { id, made: true });
      return this.change(`ask:${id}`, [...add(id, item("decision", proj, 95, { need: true, q: text.slice(0, 200), opts, of: about.of })), ...this.front(id), ...asked]);
    }
    const hit = !ctx && !about.at && ASK.find(([re]) => re.test(s));
    if (hit) return this.change("ask", [...hit[2](this), ...this.log(`You asked: ${hit[1]}`, "me", hit[3] ? { id: hit[3], made: true } : {})]);
    // the answer joins the cluster it is about and comes to its front, so it is on screen (D47)
    const id = `a${++this.n}`;
    const at = about.at && { x: Number(about.at.x) || 0, y: Number(about.at.y) || 0, w: Number(about.at.w) || 0 }; // client input
    const extra: Partial<Component> = at ? { rect: { x: Math.round(at.x + at.w + 24), y: Math.round(at.y), w: 300, h: 200 } } : {};
    const names = [...(about.of ? [about.of] : []), ...ids].map((i) => nameOf(props(spec, i)!));
    const c = item("ask", proj, 95, { q: s, about: names, ready: false, of: about.of, pinned: about.at ? true : undefined });
    this.change(`ask:${id}`, [...add(id, { ...c, ...extra }), ...(about.at || about.of ? [] : this.front(id)), ...this.log(`You asked: ${s}`, proj, { id, made: true })]);
    this.at(2.2, () => this.has(id) && this.change(`ask:${id}:ready`, set(id, { ready: true })));
  }
}

/** Anything with two readings comes back as a choice to tap, not a guess: "a or b", or a yes/no "should we". */
function choiceOpts(s: string): CardOpt[] | undefined {
  const parts = s.replace(/^(should|shall|do|can|would|will)\s+(we|i|you|it)\s+/i, "").split(/,?\s+or\s+/i).map((p) => p.trim()).filter(Boolean);
  if (parts.length > 1) return parts.slice(0, 4).map((p, i) => ({ k: `o${i}`, b: p[0].toUpperCase() + p.slice(1, 40), rec: !i }));
  if (/^(should|shall)\s+(we|i)\b/i.test(s)) return [{ k: "y", b: "Yes", rec: true }, { k: "n", b: "No" }];
}
