// Feeds the board real state as agent tool calls, and handles what the owner does on it.
// Sources: open PRs and CI from `gh api`, merged PRs per day, crew threads from the crewboard daemon,
// token cost from omp's stats store, and this host's load. Nothing here is invented: a missing source shows an empty card.
// Run: bun feeder/feeder.ts  (GENUI_SERVER defaults to http://127.0.0.1:8787, BOARD to the canvas's default "demo")
import { Database } from "bun:sqlite";
import { statfsSync } from "node:fs";
import { cpus, freemem, homedir, totalmem } from "node:os";
import type { BoardSpec, Component, Op, PatchOp, ServerMsg } from "@crewship/genui-spec";
import { applyPatch, esc } from "../src/model";

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
  const [p, m, c, u] = await Promise.all([get("pull requests", prs), get("merged PRs", merged), get("crewboard", crew), get("usage", usage)]);
  return { prs: p, merged: m, crew: c, usage: u, host: { ...host }, gaps };
}

const card = (kind: string, proj: string, base: number, props: P): Component => ({ type: "card", props: { kind, proj, base, ...props } });

/** The cards the sources call for, by id. Owner-set props (pick, done, removed, asked) are never part of this. */
export function cards(s: Sources): Record<string, Component> {
  const out: Record<string, Component> = {};
  for (const p of s.prs ?? []) {
    const { total, done, failed } = p.checks;
    const stages = ["Open", "Checks", "Review", "Merge"];
    const at = p.draft ? 0 : done < total || failed.length ? 1 : 2;
    out[`pr${p.n}`] = failed.length
      ? card("note", "repo", 70, { title: `#${p.n}: ${failed.length} check${failed.length > 1 ? "s" : ""} failed`, flag: "failing", url: p.url, items: failed })
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
  if (s.prs && !s.prs.length) out.prs = card("note", "repo", 10, { title: "No open pull requests", items: [] });
  out.k1 = card("crew", "crew", 34, { title: s.crew?.length ? "Crew right now" : "No crew threads on the crewboard", members: (s.crew ?? []).map((c) => ({ ...c, hsl: PROJECTS.crew.hsl })) });
  if (s.merged) out.sh = card("shipped", "repo", 20, { title: "Merged PRs", ...s.merged });
  out.use = card("note", "cost", 30, s.usage
    ? { title: `$${s.usage.cost.toFixed(2)} spent today`, body: `${s.usage.msgs} model calls since 00:00 UTC`, items: s.usage.models.map(([m, c]) => `${m}: $${c.toFixed(2)}`) }
    : { title: "Usage unavailable", items: s.gaps.filter((g) => g.startsWith("usage")) });
  if (s.gaps.length) out.gaps = card("note", "host", 15, { title: "Sources not read", items: s.gaps });
  return out;
}

function lineOf(id: string, p: P): string {
  if (p.done === true) return "Done. *Moving on.*";
  switch (p.kind) {
    case "decision": return `*Needs you:* ${p.q}`;
    case "pipeline": return `${p.title} is at *${(p.stages as string[])[Number(p.at)]}.*`;
    case "crew": return `*${(p.members as unknown[]).length} crew threads* are active.`;
    case "tui": return `*${p.agent}* live.`;
    case "ask": return `*Sent to the crew:* ${p.q}`;
    default: return `*${p.title ?? id}*`;
  }
}

/** Priority, line and the header sentence from what is on the board now. */
function derived(spec: BoardSpec): Record<string, P> {
  const want: Record<string, P> = {};
  const items = Object.entries(spec.components).filter(([, c]) => c.type === "card" && c.props.removed !== true);
  for (const [id, { props: p }] of items) want[id] = { priority: p.done === true ? 5 : Number(p.base) + (p.asked === true ? 200 : 0), line: lineOf(id, p) };
  const top = items.reduce<string | undefined>((a, [id]) => (!a || Number(want[id].priority) > Number(want[a].priority) ? id : a), undefined);
  if (!top) return want;
  const more = items.filter(([id, c]) => id !== top && c.props.need === true && c.props.done !== true).length;
  want.header = { title: String(want[top].line) + (more ? ` *+${more} more* need${more > 1 ? "" : "s"} you.` : "") };
  return want;
}

const setProp = (id: string, k: string, value: unknown): PatchOp => ({ op: "add", path: `/components/${esc(id)}/props/${esc(k)}`, value });

/** The patch that brings `spec` to the wanted cards without touching what the owner set. */
export function diff(spec: BoardSpec, want: Record<string, Component>, owned: Set<string>): PatchOp[] {
  const patch: PatchOp[] = [];
  if (!spec.projects) patch.push({ op: "add", path: "/projects", value: PROJECTS });
  for (const [id, c] of Object.entries(want)) {
    const have = spec.components[id];
    if (!have) { patch.push({ op: "add", path: `/components/${esc(id)}`, value: c }); continue; }
    for (const [k, v] of Object.entries(c.props)) if (JSON.stringify(have.props[k]) !== JSON.stringify(v)) patch.push(setProp(id, k, v));
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
    header: { type: "header", props: { wins: "agent", stats: s.host, tuis: (s.crew ?? []).map((c) => ({ name: c.name, proj: "crew" })) } },
    input: { type: "input", props: { placeholder: "Ask the crew anything; it goes to the crewboard", chips: [] } },
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

async function call(tool: string, args: P) {
  const r = await fetch(`${SERVER}/agent/${BOARD}`, {
    method: "POST", body: JSON.stringify({ tool, args }),
    headers: { "content-type": "application/json", ...(process.env.GENUI_AGENT_TOKEN ? { authorization: `Bearer ${process.env.GENUI_AGENT_TOKEN}` } : {}) },
  });
  if (!r.ok) console.error(`${tool}: ${r.status} ${await r.text()}`);
}

async function publish(s: Sources) {
  const want = { ...chrome(s, log), ...cards(s), ...extra };
  for (const id of Object.keys(want)) if (want[id].type === "card") owned.add(id);
  const patch = diff(spec, want, owned);
  if (patch.length) await call("emit_view", { event: { delta: patch }, cause: "feeder:sources" });
}

const note = (text: string, proj = "me") => log.push({ at: Math.round((Date.now() - t0) / 1000), text, proj });
const pub = (body: P) => run(["crewboard", "pub", TOPIC, JSON.stringify(body)]);

/** The owner's intents, forwarded by the board to agent sockets. */
async function onIntent(m: Extract<ServerMsg, { t: "intent" }>) {
  const p = m.payload, c = spec.components[m.targetId]?.props ?? {};
  if (m.kind !== "input") return;
  if (typeof p.open === "string") {
    const id = p.open;
    if (id === "sys") extra.sys = card("sys", "host", 60, { title: "This host", series: last?.host ?? {}, asked: true });
    else if (id.startsWith("tui-")) {
      const name = id.slice(4);
      const lines = await run(["crewboard", "tail", `task/${name}`, "-n", "14", "--viewer"]).catch((e) => `crewboard: ${(e as Error).message}`);
      extra[id] = card("tui", "crew", 60, { agent: name, lines: lines.trimEnd().split("\n"), asked: true });
    }
  } else if (typeof p.text === "string" && p.text.trim()) {
    // the ask goes to every crew agent that reads the genui topic; no reply is made up here
    const r = await pub({ ask: p.text, about: p.about ?? null }).catch((e) => `failed: ${(e as Error).message}`);
    extra[`ask${m.id}`] = card("ask", "me", 90, { q: p.text, ready: false, asked: true });
    note(`Sent to the crewboard topic ${TOPIC}: ${p.text} (seq ${r.trim()})`);
  } else if (p.field === "pick" && c.kind === "decision") {
    const pr = Number(m.targetId.slice(2));
    const r = await pub({ decision: p.value, pr, url: c.url }).catch((e) => `failed: ${(e as Error).message}`);
    note(`${p.value === "approve" ? "Approved" : "Declined"} #${pr}; recorded on ${TOPIC} (seq ${r.trim()})${p.value === "approve" ? `. Merge draft, not run: gh pr merge ${pr}` : ""}`, "repo");
    await call("emit_view", { event: { delta: [setProp(m.targetId, "done", true)] }, cause: `intent:${m.id}` });
  } else if (p.field === "removed") delete extra[m.targetId];
  if (last) await publish(last);
}

function connect() {
  const ws = new WebSocket(`${SERVER.replace(/^http/, "ws")}/ws/${BOARD}?role=agent`);
  ws.onmessage = (e) => {
    const m = JSON.parse(String(e.data)) as ServerMsg;
    if (m.t === "snapshot") (spec = m.spec), synced.resolve();
    else if (m.t === "ops") for (const o of m.ops as Op[]) spec = applyPatch(spec, o.patch);
    else if (m.t === "intent") onIntent(m).catch((err) => console.error("intent:", err));
  };
  ws.onclose = () => setTimeout(connect, 2000); // the dev server restarts; reconnect
}

// the first snapshot must land before any diff, or the feeder would overwrite what the owner set
const synced = Promise.withResolvers<void>();
if (import.meta.main) {
  connect();
  await synced.promise;
  for (;;) {
    last = await gather();
    if (last.gaps.length) console.error("gaps:", last.gaps.join("; "));
    await publish(last).catch((e) => console.error("publish:", (e as Error).message));
    await Bun.sleep(POLL_S * 1000);
  }
}
