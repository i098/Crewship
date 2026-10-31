// Feeds the board real state as agent tool calls, and handles what the owner does on it.
// Sources: open PRs and CI from `gh api`, merged PRs per day, crew threads from the crewboard daemon,
// token cost from omp's stats store, and this host's load. Nothing here is invented: a missing source shows an empty card.
// Run: bun feeder/feeder.ts  (GENUI_SERVER defaults to http://127.0.0.1:8787, BOARD to the canvas's default "demo")
import { Database } from "bun:sqlite";
import { statfsSync } from "node:fs";
import { cpus, freemem, homedir, totalmem } from "node:os";
import type { BoardSpec, Component, Op, PatchOp, ServerMsg } from "@crewship/genui-spec";
import { applyPatch, esc } from "../src/model";
import { answer, contextOf, fleetCards, fleetProjects, fleetTuis, merge, steer, TOPICS, topicRows, tuiLines, type Open, type Opt, type Pending, type Topic } from "../fleet/cards";
import { briefAsks } from "../fleet/brief";
import { FleetSource } from "../fleet/data";
import { boardIds, chat, type Plan, stream } from "../fleet/chat";

const SERVER = process.env.GENUI_SERVER ?? "http://127.0.0.1:8787";
const BOARD = process.env.BOARD ?? "demo";
const REPO = process.env.GENUI_REPO ?? "i098/Crewship";
const POLL_S = 60; // gh rate limit: about 12 calls per poll
const TOPIC = "genui"; // where the owner's decisions and asks land on the crewboard

export const PROJECTS = {
  repo: { name: "pull requests", hsl: "hsl(188 95% 58%)" },
  crew: { name: "crew", hsl: "hsl(262 92% 70%)" },
  host: { name: "this host", hsl: "hsl(210 90% 68%)" },
  cost: { name: "usage", hsl: "hsl(38 98% 62%)" },
  me: { name: "you added", hsl: "hsl(48 96% 60%)" },
};

// With GENUI_FM_MAIN set, the owner's fleet (asks, second mates, workers, every owned PR) replaces the one-repo PR cards.
const FM_MAIN = process.env.GENUI_FM_MAIN;
const fleet = FM_MAIN ? new FleetSource(FM_MAIN) : undefined;
const pending = new Map<string, Pending>(); // actions waiting for the owner's Yes
// what the owner asked the chat to draw; with the fleet the canvas starts empty, without it there is no chat, so all shows
const shown = new Set<Topic>(fleet ? [] : TOPICS);

type P = Record<string, unknown>;
export type Pr = { n: number; title: string; url: string; draft: boolean; checks: { total: number; done: number; failed: string[] } };
export type Sources = {
  prs: Pr[] | null;
  merged: { total: number; bars: number[] } | null; // bars: merged PRs per day, oldest first, 14 days
  crew: { name: string; doing: string }[] | null;
  usage: { cost: number; msgs: number; models: [string, number][] } | null;
  host: Record<string, number[]>;
  gaps: string[];
};

const run = async (cmd: string[]): Promise<string> => {
  const p = Bun.spawn(cmd, { stdout: "pipe", stderr: "pipe" });
  const [out, err, code] = await Promise.all([new Response(p.stdout).text(), new Response(p.stderr).text(), p.exited]);
  if (code !== 0) throw new Error(`${cmd[0]} ${cmd[1]}: ${err.trim().split("\n")[0]}`);
  return out;
};
const gh = async (path: string) => JSON.parse(await run(["gh", "api", path]));
type PrDetail = { title: string; state: string; merged: boolean; body: string | null; user: { login: string }; head: { ref: string }; base: { ref: string }; additions: number; deletions: number; changed_files: number };
const PR_URL = /^https:\/\/github\.com\/([\w.-]+\/[\w.-]+)\/pull\/(\d+)\/?$/;

async function prs(): Promise<Pr[]> {
  const open = (await gh(`repos/${REPO}/pulls?state=open&per_page=8`)) as { number: number; title: string; html_url: string; draft: boolean; head: { sha: string } }[];
  return Promise.all(open.map(async (p) => {
    const runs = ((await gh(`repos/${REPO}/commits/${p.head.sha}/check-runs?per_page=100`)) as { check_runs: { name: string; status: string; conclusion: string | null }[] }).check_runs;
    const failed = runs.filter((r) => ["failure", "timed_out", "cancelled"].includes(r.conclusion ?? "")).map((r) => r.name);
    return { n: p.number, title: p.title, url: p.html_url, draft: p.draft, checks: { total: runs.length, done: runs.filter((r) => r.status === "completed").length, failed } };
  }));
}

async function merged(): Promise<{ total: number; bars: number[] }> {
  const day = 864e5, from = new Date(Date.now() - 13 * day).toISOString().slice(0, 10);
  // shortcut: bars count the first 100 results only; page the search if 14 days ever pass 100 merges
  const r = (await gh(`search/issues?q=${encodeURIComponent(`repo:${REPO} is:pr is:merged merged:>=${from}`)}&per_page=100`)) as { total_count: number; items: { closed_at: string }[] };
  const bars = Array<number>(14).fill(0), start = Date.parse(from);
  for (const i of r.items) bars[Math.min(13, Math.floor((Date.parse(i.closed_at) - start) / day))]++;
  return { total: r.total_count, bars };
}

async function crew() {
  const topics = JSON.parse(await run(["crewboard", "topics", "--summary", "--json"])) as { topic: string; newest: number; summary?: string }[];
  return topics.filter((t) => t.topic.startsWith("task/")).sort((a, b) => b.newest - a.newest).slice(0, 6)
    .map((t) => ({ name: t.topic.slice(5), doing: t.summary ?? "" }));
}

function usage() {
  const db = new Database(`${homedir()}/.omp/stats.db`, { readonly: true });
  try {
    const since = new Date().setUTCHours(0, 0, 0, 0);
    const rows = db.query("select model, count(*) n, sum(cost_total) c from messages where timestamp >= ? group by model order by c desc").all(since) as { model: string; n: number; c: number }[];
    return { cost: rows.reduce((s, r) => s + r.c, 0), msgs: rows.reduce((s, r) => s + r.n, 0), models: rows.slice(0, 3).map((r) => [r.model, r.c] as [string, number]) };
  } finally { db.close(); }
}

// Host samples accumulate from the feeder's own reads; the series starts empty.
const host: Record<string, number[]> = { cpu: [], mem: [], disk: [] };
let lastCpu = cpus().map((c) => c.times);
function sampleHost() {
  const now = cpus().map((c) => c.times);
  let busy = 0, all = 0;
  now.forEach((t, i) => {
    const o = lastCpu[i], d = (k: keyof typeof t) => t[k] - o[k];
    const tot = d("user") + d("nice") + d("sys") + d("idle") + d("irq");
    busy += tot - d("idle"); all += tot;
  });
  lastCpu = now;
  const fs = statfsSync("/");
  const push = (k: string, v: number) => host[k] = [...host[k], Math.round(v)].slice(-30);
  if (all) push("cpu", (100 * busy) / all);
  push("mem", 100 * (1 - freemem() / totalmem()));
  push("disk", 100 * (1 - fs.bavail / fs.blocks));
}

export async function gather(): Promise<Sources> {
  const gaps: string[] = [];
  const get = async <T>(name: string, f: () => T | Promise<T>): Promise<T | null> => {
    try { return await f(); } catch (e) { gaps.push(`${name}: ${(e as Error).message}`); return null; }
  };
  sampleHost();
  const [p, m, c, u] = await Promise.all([fleet ? null : get("pull requests", prs), get("merged PRs", merged), get("crewboard", crew), get("usage", usage)]);
  return { prs: p, merged: m, crew: c, usage: u, host: { ...host }, gaps };
}

const card = (kind: string, proj: string, base: number, props: P): Component => ({ type: "card", props: { kind, proj, base, ...props } });

/** Each open PR as a pipeline (or a failing note) plus its approve decision, and GitHub's preview of the newest. */
function prCards(prs: Pr[], out: Record<string, Component>) {
  for (const p of prs) {
    const { total, done, failed } = p.checks;
    const stages = ["Open", "Checks", "Review", "Merge"];
    const at = p.draft ? 0 : done < total || failed.length ? 1 : 2;
    out[`pr${p.n}`] = failed.length
      ? card("note", "repo", 70, { title: `#${p.n}: ${failed.length} check${failed.length > 1 ? "s" : ""} failed`, flag: "failing", url: p.url, items: failed, acts: [{ k: "claim", b: "Claim the fix", pri: true }] })
      : card("pipeline", "repo", 50, { title: `#${p.n} ${p.title}`, url: p.url, stages, at, kpi: { value: `${done}/${total}`, unit: "checks" } });
    out[`ok${p.n}`] = card("decision", "repo", failed.length ? 40 : 80, {
      need: true, q: `Approve #${p.n} ${p.title}?`, why: p.draft ? "Draft PR" : `${done}/${total} checks done`, url: p.url,
      opts: [
        // the merge stays a draft command: the owner runs it
        { k: "approve", b: "Approve", s: `Records it; merge draft: gh pr merge ${p.n}`, rec: !failed.length && done === total, preview: { [`pr${p.n}`]: { at: 3 } } },
        { k: "decline", b: "Decline", s: "Records it on the crewboard" },
      ],
    });
  }
  // GitHub's own preview image of the newest open PR
  const top = prs[0];
  if (top)
    out.e1 = card("embed", "repo", 25, {
      type: "image",
      title: `#${top.n} on GitHub`,
      src: `https://opengraph.githubassets.com/genui/${REPO}/pull/${top.n}`,
      nat: "1200/600",
    });
  else out.prs = card("note", "repo", 10, { title: "No open pull requests", items: [] });
}

/** The cards the sources call for and the owner asked to see, by id. Owner-set props (pick, done, removed, asked) are never part of this. */
export function cards(s: Sources, show: Set<Topic> = new Set(TOPICS)): Record<string, Component> {
  const out: Record<string, Component> = {};
  if (show.has("prs") && s.prs) prCards(s.prs, out);
  if (show.has("crew"))
    out.k1 = card("crew", "crew", 34, {
      title: s.crew?.length ? "Crew right now" : "No crew threads on the crewboard",
      members: (s.crew ?? []).map((c) => ({ ...c, hsl: PROJECTS.crew.hsl })),
    });
  if (show.has("merged") && s.merged) out.sh = card("shipped", "repo", 20, { title: "Merged PRs", ...s.merged });
  if (show.has("usage"))
    out.use = card(
      "note",
      "cost",
      30,
      s.usage
        ? {
            title: `$${s.usage.cost.toFixed(2)} spent today`,
            body: `${s.usage.msgs} model calls since 00:00 UTC`,
            items: s.usage.models.map(([m, c]) => `${m}: $${c.toFixed(2)}`),
          }
        : { title: "Usage unavailable", items: s.gaps.filter((g) => g.startsWith("usage")) },
    );
  if (show.has("host") && s.gaps.length) out.gaps = card("note", "host", 15, { title: "Sources not read", items: s.gaps });
  return out;
}

function lineOf(id: string, p: P): string {
  if (p.done === true) return "Done. *Moving on.*";
  switch (p.kind) {
    case "decision": return `*Needs you:* ${p.q}`;
    case "pipeline": return `${p.title} is at *${(p.stages as string[])[Number(p.at)]}.*`;
    case "crew": return `*${(p.members as unknown[]).length} crew threads* are active.`;
    case "tui": return `*${p.agent}* live.`;
    case "ask": return p.ready === true && Array.isArray(p.about) && p.about.length ? String(p.about.at(-1)).split(/(?<=[.?!])\s/)[0] : `*You asked:* ${p.q}`;
    default: return `*${p.title ?? id}*`;
  }
}

/** Priority, line and the header sentence from what is on the board now. */
function derived(spec: BoardSpec): Record<string, P> {
  const want: Record<string, P> = {};
  const items = Object.entries(spec.components).filter(([, c]) => c.type === "card" && c.props.removed !== true);
  for (const [id, { props: p }] of items) want[id] = { priority: p.done === true ? 5 : Number(p.base) + (p.asked === true ? 200 : 0), line: lineOf(id, p) };
  const top = items.reduce<string | undefined>((a, [id]) => (!a || Number(want[id].priority) > Number(want[a].priority) ? id : a), undefined);
  // an empty canvas still says what waits on him, so the header never reads as "nothing" while asks are open
  if (!top) {
    const n = fleet?.fleet.asks.length ?? 0;
    return { ...want, header: { title: n ? `*${n} asks* need you. Ask to see them.` : "Ask for decisions, PRs, crew or usage." } };
  }
  // paging cards carry how many asks off their page still need him, so the header matches the full list
  const more = items.reduce((n, [id, c]) => n + (id !== top && c.props.need === true && c.props.done !== true ? 1 : 0) + Number(c.props.unseen ?? 0), 0);
  want.header = { title: String(want[top].line) + (more ? ` *+${more} more* need${more > 1 ? "" : "s"} you.` : "") };
  return want;
}

const setProp = (id: string, k: string, value: unknown): PatchOp => ({ op: "add", path: `/components/${esc(id)}/props/${esc(k)}`, value });

const KEEP = new Set(["pick", "done", "sent", "removed", "asked", "pinned", "float", "layer", "claim", "priority", "line"]);

/** The ops that bring one existing card's props to the wanted ones. */
function cardPatch(id: string, have: Component, c: Component): PatchOp[] {
  const patch: PatchOp[] = [];
  for (const [k, v] of Object.entries(c.props)) if (JSON.stringify(have.props[k]) !== JSON.stringify(v)) patch.push(setProp(id, k, v));
  // a prop the card no longer has (an old paging card's list) is cleared; owner-set and derived props stay.
  // null, not remove: a publish computed before the last one lands would remove a missing path, and the board rejects that
  if (c.type === "card")
    for (const k of Object.keys(have.props)) if (!(k in c.props) && !KEEP.has(k) && have.props[k] != null) patch.push(setProp(id, k, null));
  return patch;
}

/** The patch that brings `spec` to the wanted cards without touching what the owner set. */
export function diff(spec: BoardSpec, want: Record<string, Component>, owned: Set<string>): PatchOp[] {
  const patch: PatchOp[] = [];
  const projects = { ...PROJECTS, ...(fleet ? fleetProjects(fleet.fleet) : {}) };
  if (JSON.stringify(spec.projects) !== JSON.stringify(projects)) patch.push({ op: "add", path: "/projects", value: projects });
  for (const [id, c] of Object.entries(want)) {
    const have = spec.components[id];
    if (have) patch.push(...cardPatch(id, have, c));
    else patch.push({ op: "add", path: `/components/${esc(id)}`, value: c });
  }
  // a card the sources no longer report (a closed PR) leaves the board
  for (const id of owned) if (!want[id] && spec.components[id] && spec.components[id].props.removed !== true) patch.push(setProp(id, "removed", true));
  const next = applyPatch(spec, patch);
  for (const [id, kv] of Object.entries(derived(next)))
    for (const [k, v] of Object.entries(kv)) if (next.components[id] && JSON.stringify(next.components[id].props[k]) !== JSON.stringify(v)) patch.push(setProp(id, k, v));
  return patch;
}

/** The board's chrome: header with host stats and crew pills, the ask bar, and the action log. */
function chrome(s: Sources, log: P[]): Record<string, Component> {
  return {
    header: {
      type: "header",
      props: { wins: "agent", stats: s.host, tuis: fleet ? fleetTuis(fleet.fleet) : (s.crew ?? []).map((c) => ({ name: c.name, proj: "crew" })) },
    },
    input: {
      type: "input",
      props: {
        placeholder: fleet
          ? "Ask for decisions, PRs, crew or usage; select a crew card and type to steer it"
          : "Ask the crew anything; it goes to the crewboard",
        chips: [],
      },
    },
    log: { type: "log", props: { items: log } },
  };
}

// ---- the live loop: an agent socket on the board, a poll of the sources, and the owner's intents ----

const t0 = Date.now();
let spec: BoardSpec = { components: {}, links: [], tokens: {} };
let last: Sources | undefined;
const log: P[] = [];
const owned = new Set<string>();
const extra: Record<string, Component> = {}; // cards the owner opened: host stats, a crew terminal, an ask
const focused = new Set<string>(), unfocused = new Set<string>(); // board cards the chat brought forward, now and before
// cards the owner closed with ✕; any other card the sources want again (a PR back after a GitHub gap) returns.
// shortcut: memory only, so a feeder restart brings back fleet cards he closed; persist it if that bothers him
const dismissed = new Set<string>();
// the board rebuilt for the current question (chat plan:): `back` holds cards he tapped back from the rail, `own` the model's new cards
let plan: { p: Plan; cause: string; back: string[]; own: Set<string> } | undefined;
const planSeqs = new Set<number>(); // the board ops of the plan's question, so undoing one of them drops the plan
const TOPIC_OF: Record<string, Topic> = { ask: "asks", pr: "prs", crew: "crew" };

/** The fleet cards a plan keeps are drawn whatever topic or page is showing. */
function planned(): { open: Open; shown: Set<Topic> } {
  if (!plan) return { open, shown };
  const ids = [...plan.p.keep, ...plan.back];
  const topics = ids.map((id) => TOPIC_OF[id.split("-")[0]]).filter(Boolean);
  return { open: { ...open, cards: new Set([...open.cards, ...ids]) }, shown: new Set([...shown, ...topics]) };
}

/** A card of his from an earlier feeder run is on the board but not in `want`: keep it as his, so a plan can set it aside too. */
function adoptLeftovers(want: Record<string, Component>) {
  for (const [id, c] of Object.entries(spec.components))
    if (!want[id] && c.props.proj === "me" && !FEEDER_MADE.test(id) && goesAside(id, c)) {
      const { aside, size, under, edge, ...props } = c.props;
      want[id] = extra[id] = { ...c, props };
    }
}

/** Applies the plan: each kept card stays in its own board's cluster (boards never mix), in the plan's order and size;
 * every other card is set aside to the rail. */
export function applyPlan(want: Record<string, Component>, pl = plan) {
  if (!pl) return;
  adoptLeftovers(want);
  const p = boardIds(pl.p, want);
  const keep = [...new Set([...p.keep, ...pl.back, ...Object.keys(p.under), ...p.edge])].filter((id) => want[id]?.type === "card");
  const lift = (id: string, props: P) => (want[id] = { ...want[id], props: { ...want[id].props, ...props } });
  keep.forEach((id, i) =>
    lift(id, {
      base: 700 - i,
      asked: true, // all kept cards get the same ask boost, so the plan's order holds
      ...(p.size[id] ? { size: p.size[id] } : {}),
      ...(p.under[id] ? { under: p.under[id] } : {}),
      ...(p.edge.includes(id) ? { edge: true } : {}),
    }),
  );
  if (want["ai-q"]) lift("ai-q", { base: 800 });
  for (const [id, c] of Object.entries(want)) if (!keep.includes(id) && !pl.own.has(id) && goesAside(id, c)) lift(id, { aside: true });
}

/** A card a plan may set aside: not the answer, not one waiting on his Yes, and not a floating window (those stay over any layout). */
function goesAside(id: string, c: Component): boolean {
  const p = c.props;
  return c.type === "card" && p.removed !== true && id !== "ai-q" && !pending.has(id) && p.pinned !== true && p.float !== true;
}

/** Publishes once more after the one in flight, so a burst of chat edits costs at most two board round trips. */
let inFlight: Promise<void> | undefined, queued: string | undefined;
function kick(cause: string) {
  if (inFlight) return void (queued = cause);
  if (!last) return;
  inFlight = publish(last, cause)
    .catch((e) => console.error("publish:", (e as Error).message))
    .finally(() => {
      inFlight = undefined;
      if (queued) (cause = queued, queued = undefined, kick(cause));
    });
}

async function call(tool: string, args: P) {
  const r = await fetch(`${SERVER}/agent/${BOARD}`, {
    method: "POST", body: JSON.stringify({ tool, args }),
    headers: { "content-type": "application/json", ...(process.env.GENUI_AGENT_TOKEN ? { authorization: `Bearer ${process.env.GENUI_AGENT_TOKEN}` } : {}) },
  });
  if (!r.ok) console.error(`${tool}: ${r.status} ${await r.text()}`);
}

/** Chat focus: the cards brought forward for the current question hold the front until the next question. */
function focus(want: Record<string, Component>) {
  const lift = (id: string, asked: boolean) => (want[id] = { ...want[id], props: { ...want[id].props, asked } });
  for (const id of focused) if (want[id]?.type === "card") lift(id, true);
  for (const id of unfocused) if (!focused.has(id) && want[id]?.type === "card" && want[id].props.asked !== true) lift(id, false);
}

/** A card the sources want again comes back unless the owner closed it with ✕. */
function revive(want: Record<string, Component>) {
  for (const [id, c] of Object.entries(want)) if (c.type === "card" && !dismissed.has(id) && c.props.removed === undefined) want[id] = { ...c, props: { ...c.props, removed: false } };
}

/** Cards left by an earlier feeder run are ours too, so the board drops what the fleet no longer has; the owner's own stay.
 * A fleet card a plan lifted to "me" and an ask's context window are still ours, so a restart does not leave them in front. */
const FEEDER_MADE = /^(ai|pr|crew|ask|more|ctx)-/;
function adopt(want: Record<string, Component>) {
  if (!owned.size) for (const [id, c] of Object.entries(spec.components)) if (c.type === "card" && (c.props.proj !== "me" || FEEDER_MADE.test(id))) owned.add(id);
  for (const id of Object.keys(want)) if (want[id].type === "card") owned.add(id);
}

/** What the current answer showed (asks, PRs, crew): its real rows go in the answer card. */
let answerTopics = new Set<Topic>();

/** An open terminal or host card follows its source while it stays open. */
function liveExtras() {
  if (extra.sys && last) extra.sys = { ...extra.sys, props: { ...extra.sys.props, series: last.host } };
  // a finished answer's lists follow the fleet, so a source that loads after the answer still fills them
  const a = extra["ai-q"];
  if (a?.props.ready === true && fleet) extra["ai-q"] = { ...a, props: { ...a.props, rows: topicRows(fleet.fleet, answerTopics) } };
  for (const id of Object.keys(extra)) {
    const lines = id.startsWith("tui-") && fleet ? tuiLines(fleet.fleet, id.slice(4)) : undefined;
    if (lines) extra[id] = { ...extra[id], props: { ...extra[id].props, lines } };
  }
}

async function publish(s: Sources, cause = "feeder:sources") {
  liveExtras();
  const pl = planned();
  const want = { ...chrome(s, log), ...cards(s, pl.shown), ...(fleet ? fleetCards(fleet.fleet, pending, pl.open, pl.shown) : {}), ...extra };
  focus(want);
  revive(want);
  applyPlan(want);
  adopt(want);
  const patch = diff(spec, want, owned);
  if (patch.length) await call("emit_view", { event: { delta: patch }, cause });
}

const note = (text: string, proj = "me") => log.push({ at: Math.round((Date.now() - t0) / 1000), text, proj });
const pub = (body: P) => run(["crewboard", "pub", TOPIC, JSON.stringify(body)]);
const failed = (e: unknown) => `failed: ${(e as Error).message}`;

/** The fleet card a typed text is for: a selected or open ask, crew card or crew terminal, else the ask picked to answer. */
function fleetTarget(about: unknown): { id: string; c: Component } | undefined {
  const a = (about ?? {}) as { of?: unknown; ids?: unknown };
  const ids = [a.of, ...(Array.isArray(a.ids) ? a.ids : [])].filter((x): x is string => typeof x === "string");
  for (const id of ids) {
    const c = spec.components[id] ?? extra[id];
    if (c && (c.props.key || c.props.task || (c.props.kind === "tui" && c.props.agent))) return { id, c };
  }
  return undefined;
}

/** Puts an action on the board as a confirm card; it runs only when the owner picks Yes. */
function ask(a: Pending, of?: string) {
  const id = `confirm-${Date.now().toString(36)}`;
  pending.set(id, { ...a, id, of });
}

/** Puts an action up for confirming, or says why it cannot run; `of` is the card it acts on. */
function offer(make: () => Pending, refused: string, of?: string) {
  try {
    ask(make(), of);
  } catch (e) {
    note(`${refused}: ${(e as Error).message}`);
  }
}

type Intent = Extract<ServerMsg, { t: "intent" }>;
// what the owner has open: the cluster the camera is on and the cards in full view; only these load detail
const open: Required<Open> = { cluster: null, cards: new Set(), page: new Map() };
// removed and done are cleared, so a card closed with its X opens again from its pill
const again = { asked: true, removed: false, done: false };

/** Opens host stats or a crew terminal from a header pill. */
async function openExtra(id: string) {
  if (id === "sys") return void (extra.sys = card("sys", "host", 60, { title: "This host", series: last?.host ?? {}, ...again }));
  if (!id.startsWith("tui-")) return;
  const name = id.slice(4), fl = fleet && tuiLines(fleet.fleet, name);
  const lines = fl ? fl.join("\n") : await run(["crewboard", "tail", `task/${name}`, "-n", "14", "--viewer"]).catch((e) => `crewboard: ${(e as Error).message}`);
  extra[id] = card("tui", "crew", 60, { agent: name, lines: lines.trimEnd().split("\n"), ...again });
}

/** False when the page forbids frames; redirects are followed with their cookies, as a browser would (a Lavish board sets its cookie first). */
async function frameable(url: string): Promise<boolean> {
  let u = url,
    cookie = "";
  for (let i = 0; i < 4; i++) {
    const r = await fetch(u, { redirect: "manual", headers: cookie ? { cookie } : {}, signal: AbortSignal.timeout(8000) });
    const to = r.headers.get("location");
    if (r.status >= 300 && r.status < 400 && to) {
      cookie = [cookie, ...r.headers.getSetCookie().map((c) => c.split(";")[0])].filter(Boolean).join("; ");
      u = new URL(to, u).href;
      continue;
    }
    void r.body?.cancel();
    return !r.headers.has("x-frame-options") && !/frame-ancestors(?![^;]*\*)/i.test(r.headers.get("content-security-policy") ?? "");
  }
  return false;
}

/** A link as a window card: a PR read through the GitHub API (github.com refuses frames), a page framed when it allows it. */
async function openWindow(win: string, url: string) {
  if (!/^win-[a-z0-9]{1,16}$/.test(win) || !/^https?:\/\//.test(url)) return;
  const pr = PR_URL.exec(url),
    host = new URL(url).host;
  if (!pr) {
    const ok = await frameable(url).catch(() => true); // unknown: let the browser try
    extra[win] = ok
      ? card("embed", "me", 80, { type: "site", title: host, src: url, ar: "4/3", ...again })
      : card("note", "me", 80, {
          title: host,
          flag: "blocked",
          items: ["This page refuses to be shown inside another page (its own frame-ancestors setting)."],
          ...again,
        });
    return;
  }
  const [, repo, n] = pr;
  const d = await (gh(`repos/${repo}/pulls/${n}`) as Promise<PrDetail>).catch((e) => (e as Error).message);
  if (typeof d === "string") return void (extra[win] = card("note", "me", 80, { title: `${repo}#${n}`, flag: "failing", items: [`Not read: ${d}`], ...again }));
  const c = fleet?.fleet.prs.find((p) => p.url.replace(/\/$/, "") === url.replace(/\/$/, ""))?.checks;
  extra[win] = card("note", "me", 80, {
    title: `${repo}#${n}: ${d.title}`,
    items: [
      `${d.merged ? "merged" : d.state} · by ${d.user.login} · ${d.head.ref} → ${d.base.ref}`,
      `${d.changed_files} files · +${d.additions} −${d.deletions}`,
      ...(c ? [`checks: ${c.ok} passed, ${c.bad} failed, ${c.pending} running`] : []),
    ],
    body: (d.body ?? "").slice(0, 4000),
    ...again,
  });
}

/** The rail: a tap brings one card back into the plan; Reset drops the plan and the overview returns. True when handled. */
function onRail(p: P, id: string): boolean {
  if (p.field === "aside") void (plan && !plan.back.includes(id) && plan.back.push(id));
  else if (p.field === "plan") plan = undefined;
  else return false;
  return true;
}

/** What the owner opens and closes: a pill, the full view, the cluster in front, a card closed with ✕. True when handled. */
async function onView(p: P, id: string): Promise<boolean> {
  if (onRail(p, id)) return true;
  if (typeof p.open === "string") await openExtra(p.open);
  // only the link the card itself carries opens, so a client cannot make the feeder fetch any URL
  else if (p.field === "window" && typeof p.win === "string" && typeof p.value === "string" && spec.components[id]?.props.url === p.value)
    await openWindow(p.win, p.value);
  else if (typeof p.view === "string") void (p.on === true ? open.cards.add(p.view) : open.cards.delete(p.view));
  else if ("cluster" in p) open.cluster = typeof p.cluster === "string" ? p.cluster : null;
  else if (p.field !== "removed") return false;
  else {
    dismissed.add(id);
    delete extra[id];
    pending.delete(id);
    open.cards.delete(id);
  }
  return true;
}

const SENT_MS = 2500;

/** Yes or Cancel on a confirm card. */
async function confirm(m: Intent, fl: FleetSource) {
  const act = pending.get(m.targetId)!;
  if (act.state) return; // a second tap while it runs
  if (m.payload.value !== "yes") return void (pending.delete(m.targetId), note(`Cancelled: ${act.q}`));
  // the card he tapped stays where it is and says what happens: sending, then sent, then it leaves
  pending.set(m.targetId, { ...act, state: "running" });
  if (last) await publish(last, m.id);
  const r = await act.run().catch((e) => ({ ok: false, text: String(e) }));
  note(r.text, r.ok ? "me" : "ask");
  if (!r.ok) pending.delete(m.targetId);
  else {
    pending.set(m.targetId, { ...act, state: "sent", why: r.text });
    if (act.of) dismissed.add(act.of); // a publish before the source drops it cannot bring the card back
    const done = act.of ? [setProp(act.of, "done", true), setProp(act.of, "sent", true)] : [];
    if (done.length) await call("emit_view", { event: { delta: done }, cause: m.id });
    setTimeout(() => {
      pending.delete(m.targetId);
      if (act.of) void call("emit_view", { event: { delta: [setProp(act.of, "removed", true)] }, cause: m.id });
      if (last) void publish(last, m.id).catch(() => {});
    }, SENT_MS);
  }
  void fl.refreshLocal().catch(() => {});
}

/** The selected or open card a composer ask is about: the full-view card first, then the selection. */
function selected(about: unknown): string | undefined {
  const a = (about ?? {}) as { of?: unknown; ids?: unknown };
  return [a.of, ...(Array.isArray(a.ids) ? a.ids : [])].find((x): x is string => typeof x === "string" && !!(spec.components[x] ?? extra[x]));
}

/**
 * An ask about one card: its real facts open at once in a floating window over it (GenUI rule: extra context goes in a
 * window, the card's own content is never rewritten), and the chat reshapes the whole board around the card.
 */
function answerInPlace(m: Intent, id: string, q: string, fl: FleetSource) {
  const facts = contextOf(fl.fleet, (spec.components[id] ?? extra[id]).props);
  const win = `ctx-${id}`.slice(0, 64);
  startChat(m, q, fl, { card: id, facts }, [id]);
  extra[win] = card("note", "me", 80, { title: "Context", items: facts, float: true, near: id, layer: Math.floor(Date.now() / 1000), removed: false });
}

let chats = 0;

/** A new ask takes the board: the last answer's focus, context window and cards step back. Returns the ask's number. */
function newAsk(m: Intent, first: string[], own: Set<string>): number {
  focused.forEach((id) => unfocused.add(id));
  focused.clear();
  // each question rebuilds the board from the overview; one with no plan: line keeps the overview, an ask about a card
  // shows that card large at once, before the model's plan reshapes the rest
  plan = first.length ? { p: { keep: first, size: { [first[0]]: "l" }, under: {}, edge: [] }, cause: m.id, back: [], own } : undefined;
  planSeqs.clear();
  // one context window at a time: every new ask closes the last ask's window (an ask about a card then opens its own)
  for (const k of Object.keys(extra)) if (k.startsWith("ctx-")) delete extra[k];
  // the last answer's cards step back so the new question owns the front and the header
  for (const [id, c] of Object.entries(extra)) if (id.startsWith("ai-")) extra[id] = { ...c, props: { ...c.props, asked: false } };
  return ++chats;
}

/**
 * Free text: the chat model streams board edits, each applied as it lands. `about` is the card he asked about;
 * `first` are cards every plan of this answer keeps in front (the card he asked about).
 */
function startChat(m: Intent, q: string, fl: FleetSource, about: unknown = m.payload.about, first: string[] = []) {
  const own = new Set<string>();
  // a newer ask owns the board: edits an older chat still streams are dropped, so they cannot overwrite its answer
  const gen = newAsk(m, first, own);
  const said: string[] = [];
  let drew = false; // the first show: of an answer replaces what the last answer drew; an answer with none keeps it
  const topics = (answerTopics = new Set<Topic>());
  // base 100: the answer sits above the decision cards it lists, so a phone shows it first
  const ask = (ready: boolean, about: string[]) =>
    card("ask", "me", 100, { q, ready, about, rows: ready ? topicRows(fl.fleet, topics) : [], asked: true, removed: false });
  extra["ai-q"] = ask(false, said);
  // the model reads the fleet once, so it waits up to a minute for asks and PRs to load instead of answering "still loading"
  const loaded = async () => {
    for (let i = 0; i < 60 && !(fl.fleet.asksAt && fl.fleet.prsAt); i++) await Bun.sleep(1000);
  };
  void loaded()
    .then(() =>
      chat({
        text: q, about, fleet: fl.fleet, board: { ...spec.components, ...extra },
        apply: async (e) => {
          if (gen !== chats) return;
          if ("say" in e) {
            if (!e.done) said.push(e.say);
            extra["ai-q"] = ask(e.done, said.length ? [...said] : [e.say]);
          } else if ("focus" in e) e.focus.forEach((id) => focused.add(id));
          else if ("show" in e) {
            if (!drew) shown.clear(), open.page.clear();
            drew = true;
            e.show.forEach((t) => (shown.add(t), topics.add(t)));
          } else if ("upsert" in e) (extra[e.upsert] = e.card), own.add(e.upsert);
          else if ("plan" in e) plan = { p: { ...e.plan, keep: [...new Set([...first, ...e.plan.keep])] }, cause: m.id, back: [], own };
          else delete extra[e.drop];
          kick(m.id);
        },
      }),
    )
    .catch((e) => note(`Chat failed: ${(e as Error).message}`));
}

/** An ask's option: its full text is the answer, sent after the owner confirms. */
function pickOpt(c: P, k: unknown, fl: FleetSource, of: string) {
  const o = (Array.isArray(c.opts) ? (c.opts as Opt[]) : []).find((o) => o.k === k);
  if (o) offer(() => answer(fl, c, o.say ? `${o.b}: ${o.say}` : o.b), "Not sent", of);
}

// shortcut: a question is told from an instruction by its words, so "fix the test" steers and "why did the test fail" asks; upgrade to a model call if it misreads
const QUESTION =
  /\?\s*$|^(what|why|how|who|when|where|which|is|are|was|does|did|do|can|could|should|will|explain|tell|show|give|more|context|details?|status)\b/i;

/** The card a composer ask is answered in: the selected or open card, unless it is a crew card given a plain instruction (a steer). */
function inPlaceOf(m: Intent, text: string): string | undefined {
  const sel = text && m.targetId === "input" ? selected(m.payload.about) : undefined;
  if (!sel) return undefined;
  const s = (spec.components[sel] ?? extra[sel]).props;
  return !s.key && (s.kind === "tui" || !!s.task) && !QUESTION.test(text) ? undefined : sel;
}

/** Owner text: answered in the card it is about, else sent to the ask or crew card it names (after a confirm), else a chat. */
function onText(m: Intent, text: string, fl: FleetSource) {
  const inPlace = inPlaceOf(m, text);
  const to = inPlace ? undefined : fleetTarget(m.payload.about);
  if (inPlace) answerInPlace(m, inPlace, text, fl);
  else if (to)
    offer(
      () => (to.c.props.key ? answer(fl, to.c.props, text) : steer(fl, String(to.c.props.task ?? to.c.props.agent), text)),
      "Not sent",
      to.c.props.key ? to.id : undefined,
    );
  else startChat(m, text, fl);
}

/** The owner's fleet intents: text to a card, a confirm, an ask's or a PR's options, a cluster's next page, or chat. True when handled. */
async function onFleet(m: Intent, c: P, fl: FleetSource): Promise<boolean> {
  const p = m.payload,
    text = typeof p.text === "string" ? p.text.trim() : "";
  const pick = p.field === "pick" ? p.value : undefined;
  if (text) onText(m, text, fl);
  else if (pick !== undefined && pending.has(m.targetId)) await confirm(m, fl);
  else if (pick !== undefined && c.key) pickOpt(c, pick, fl, m.targetId);
  else if (pick === "merge" && c.prUrl) offer(() => merge(fl, c.prUrl), "Not merged", m.targetId);
  else if (pick !== undefined && c.prUrl) await call("emit_view", { event: { delta: [setProp(m.targetId, "done", true)] }, cause: m.id });
  else if (p.field === "act" && p.value === "page" && typeof c.proj === "string") open.page.set(c.proj, (open.page.get(c.proj) ?? 0) + 1);
  else return false;
  return true;
}

/** Without the fleet: asks and decisions go to the crewboard topic for the crew to read; nothing runs here. */
async function onBoard(m: Intent, c: P) {
  const p = m.payload;
  if (typeof p.text === "string" && p.text.trim()) {
    // the ask goes to every crew agent that reads the genui topic; no reply is made up here
    const id = `ask${m.id}`;
    const r = await pub({ ask: p.text, id, about: p.about ?? null, reply: `crewboard pub ${TOPIC} '{"to":"${id}","reply":"…"}'` }).catch(failed);
    extra[id] = card("ask", "me", 90, { q: p.text, ready: false, asked: true });
    note(`Sent to the crewboard topic ${TOPIC}: ${p.text} (seq ${r.trim()})`);
  } else if (p.field === "act" && p.value === "claim" && c.url) {
    // claiming is a record on the crewboard that the crew reads; nothing runs on the repo
    const pr = Number(m.targetId.slice(2));
    const r = await pub({ claim: pr, url: c.url, checks: c.items }).catch(failed);
    note(`You claimed the fix for #${pr}; recorded on ${TOPIC} (seq ${r.trim()})`, "repo");
    await call("emit_view", { event: { delta: [setProp(m.targetId, "claim", "you")] }, cause: m.id });
  } else if (p.field === "pick" && c.kind === "decision") await decide(m, c);
}

async function decide(m: Intent, c: P) {
  const pr = Number(m.targetId.slice(2)), yes = m.payload.value === "approve";
  const r = await pub({ decision: m.payload.value, pr, url: c.url, ...(yes ? { draft: `gh pr merge ${pr}` } : {}) }).catch(failed);
  note(`${yes ? "Approved" : "Declined"} #${pr}; recorded on ${TOPIC} (seq ${r.trim()})${yes ? `. Merge draft, not run: gh pr merge ${pr}` : ""}`, "repo");
  await call("emit_view", { event: { delta: [setProp(m.targetId, "done", true)] }, cause: m.id });
}

/** The owner's intents, forwarded by the board to agent sockets. */
async function onIntent(m: Intent) {
  if (m.kind !== "input") return;
  const c = spec.components[m.targetId]?.props ?? {};
  if (!(await onView(m.payload, m.targetId)) && !(fleet && (await onFleet(m, c, fleet)))) await onBoard(m, c);
  // the reply carries the intent's id as its cause, so one z rewinds the action and the reply together
  if (last) await publish(last, m.id);
}

function connect() {
  const ws = new WebSocket(`${SERVER.replace(/^http/, "ws")}/ws/${BOARD}?role=agent`);
  ws.onmessage = (e) => {
    const m = JSON.parse(String(e.data)) as ServerMsg;
    if (m.t === "snapshot") (spec = m.spec), synced.resolve();
    else if (m.t === "ops")
      for (const o of m.ops as Op[]) {
        spec = applyPatch(spec, o.patch);
        // an undone open or ask stays gone: forget the card so the next publish does not add it back
        if (o.cause.startsWith("undo:")) for (const q of o.patch) if (q.op === "remove") delete extra[q.path.split("/")[2]];
        if (plan && o.cause === plan.cause) planSeqs.add(o.seq);
        else if (o.cause.startsWith("undo:") && planSeqs.has(Number(o.cause.slice(5)))) plan = undefined; // undoing the question takes its plan back too
      }
    else if (m.t === "intent") onIntent(m).catch((err) => console.error("intent:", err));
  };
  ws.onclose = () => setTimeout(connect, 2000); // the dev server restarts; reconnect
}

/** Crew replies to asks: `{"to":"ask…","reply":"…"}` on the genui topic fills that ask's card. */
async function replies() {
  const sub = Bun.spawn(["crewboard", "sub", TOPIC, "--json", "--viewer"], { stdout: "pipe", stderr: "ignore" });
  for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => { sub.kill(); process.exit(0); });
  let buf = "";
  for await (const chunk of sub.stdout.pipeThrough(new TextDecoderStream())) {
    buf += chunk;
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl);
      buf = buf.slice(nl + 1);
      let msg: { from?: string; body?: string }, body: { to?: unknown; reply?: unknown };
      try { msg = JSON.parse(line); body = JSON.parse(msg.body ?? ""); } catch { continue; }
      const ask = typeof body.to === "string" ? extra[body.to] : undefined;
      if (!ask || typeof body.reply !== "string") continue;
      ask.props = { ...ask.props, ready: true, about: body.reply.split("\n").filter(Boolean), from: msg.from ?? "crew" };
      note(`${msg.from ?? "crew"} answered: ${body.reply}`);
      if (last) await publish(last);
    }
  }
}

// the first snapshot must land before any diff, or the feeder would overwrite what the owner set
const synced = Promise.withResolvers<void>();
if (import.meta.main) {
  connect();
  if (fleet) {
    fleet.start();
    let t: Timer | undefined;
    let briefing = false;
    const republish = () => { if (last) publish(last).catch((e) => console.error("publish:", (e as Error).message)); };
    // fleet files change often; one publish per second at most. New asks get briefed, one run at a time.
    fleet.onChange(() => {
      clearTimeout(t);
      t = setTimeout(() => {
        republish();
        if (briefing) return;
        briefing = true;
        briefAsks(fleet.fleet.asks, republish, stream).finally(() => (briefing = false));
      }, 1000);
    });
  }
  await synced.promise;
  replies().catch((e) => console.error("replies:", (e as Error).message));
  for (;;) {
    last = await gather();
    if (last.gaps.length) console.error("gaps:", last.gaps.join("; "));
    await publish(last).catch((e) => console.error("publish:", (e as Error).message));
    await Bun.sleep(POLL_S * 1000);
  }
}
