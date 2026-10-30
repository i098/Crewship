// The owner's free-text chat: a model reads the fleet and the board, then streams edits to the board line by line:
// it brings the cards that answer the question to the front, adds or changes its own cards, and says the answer.
// The model runs through omp's own print mode, so it uses the login omp already holds; no key is read here.
import { readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import type { CardKind, Component } from "@crewship/genui-spec";
import { TOPICS, type Topic } from "./cards";
import type { Fleet, Task } from "./data";

export const CHAT_MODEL = process.env.GENUI_CHAT_MODEL ?? "anthropic/claude-haiku-5-5";
// Record, not a list: the type check fails when the spec adds a kind this file does not know
const KINDS: Record<CardKind, true> = { decision: true, conflict: true, pipeline: true, timeline: true, crew: true, shipped: true, plan: true, embed: true, incident: true, compare: true, ask: true, sys: true, tui: true };
const CATALOG = (() => {
  const md = readFileSync(`${import.meta.dir}/../../../docs/genui/cards.md`, "utf8");
  return md.slice(md.indexOf("## Card kinds"), md.indexOf("\n## ", md.indexOf("## Card kinds") + 1)).trim();
})();

// removed: false brings back a card id an earlier question used and the board later dropped
const card = (kind: string, props: Record<string, unknown>): Component => ({ type: "card", props: { ...props, kind, asked: true, removed: false } });
const last = (t: Task) => t.lines.at(-1);
const line = (t: Task) => {
  const l = last(t);
  return `${t.id}${t.mate ? ` (mate ${t.mate})` : ""} busy=${t.busy || "?"}${l ? ` last=${l.state}${l.at ? `@${l.at}` : ""}: ${l.text.slice(0, 160)}` : ""}`;
};

/** A compact text view of the fleet for the prompt: mates, workers by latest status, open asks, PRs with checks. */
export function summary(f: Fleet): string {
  const workers = [...f.workers].sort((a, b) => (last(b)?.at ?? 0) - (last(a)?.at ?? 0)).slice(0, 40);
  const prs = f.prs.slice(0, 30).map((p) => {
    const c = p.checks ? ` checks ok=${p.checks.ok} bad=${p.checks.bad} pending=${p.checks.pending}` : " checks=unknown";
    return `${p.repo}#${p.number}${p.draft ? " draft" : ""} "${p.title}"${c}${p.owner ? ` by ${p.owner.task}` : ""}`;
  });
  const backlog = Object.entries(f.backlog).map(([home, rows]) => `${home}: ${rows.length} tasks, ${rows.filter((r) => r.held).length} held`);
  return [
    `now=${Math.floor(Date.now() / 1000)} (epoch s)`,
    `Second mates (${f.mates.length}):`,
    ...f.mates.map(line),
    `Workers (${f.workers.length}, newest ${workers.length}):`,
    ...workers.map(line),
    // before the first fold an empty list is not "no asks"; the model said "0 open asks" while 123 were loading
    f.asksAt ? `Open asks (${f.asks.length}):` : "Open asks: still loading; do not say how many",
    ...f.asks.slice(0, 30).map((a) => `${a.task} key=${a.key} ${a.verb}: ${a.note.slice(0, 160)}`),
    `Open PRs (${f.prs.length}):`,
    ...prs,
    `Backlog: ${backlog.join("; ") || "not loaded"}`,
    ...(f.error ? [`Reader error: ${f.error.msg}`] : []),
  ].join("\n");
}

const SYSTEM = `You drive a generative UI canvas that shows the owner's agent fleet. The canvas is empty until he asks; you draw what he asks for.
Use only facts from the fleet summary and the board list. Never invent names or numbers.
Write plain lines only, one edit per line. Each line is applied to the board the moment you finish it, so put the most useful edit first:
say: <the answer in one sentence, at most 25 words>
show: <fleet cards to draw, comma separated, from: ${TOPICS.join(", ")}>  (asks = every open decision or question waiting on him, each with its real options and an answer box; prs = his open PRs with checks; crew = second mates and their workers; usage = model spend today; merged = PRs merged per day; host = sources that failed)
focus: <ids of existing board cards that answer the question, comma separated; they move to the front>
card: {"id": "<short-name>", "kind": "...", "proj": "<a cluster from the board list, or me>", "props": {...}}  (adds or replaces a card of yours)
drop: <id of a card of yours that no longer helps>
Start with say:. Decisions, asks, PRs, crew, usage and merges are ALWAYS drawn with show:, never with card: (a decision card of yours is refused).
Add a card only for what no show: topic covers. Never add a card, of any kind, that lists asks, decisions, PRs or workers: show: already draws them. No URLs in card text. At most 3 cards, at most 12 list rows each.
Pick each card's kind from the catalog below; use kind "note" with props title, body, items[] when no kind fits. Colours are plain hsl(...).

`;

/** One board edit from the model's stream; complete lines only. */
export type Part = { say: string } | { show: Topic[] } | { focus: string[] } | { card: Component & { id: string } } | { drop: string } | { bad: string };

const AI = (id: string) => `ai-${id.replace(/^ai-/, "").replace(/[^A-Za-z0-9_-]/g, "-").slice(0, 40)}`;

/** Parses one output line. A card with an unknown kind becomes a note; its id always carries the `ai-` prefix. */
export function parse(l: string): Part | undefined {
  const m = /^(say|show|focus|card|drop):\s*(.*)$/i.exec(l.trim());
  if (!m) return undefined;
  const tag = m[1].toLowerCase(), rest = m[2].trim();
  if (tag === "say") return { say: rest };
  const names = rest
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  if (tag === "show") return { show: names.map((s) => s.toLowerCase()).filter((s): s is Topic => (TOPICS as readonly string[]).includes(s)) };
  if (tag === "focus") return { focus: names };
  if (tag === "drop") return { drop: AI(rest) };
  let j: { id?: unknown; kind?: unknown; proj?: unknown; props?: unknown };
  try {
    j = JSON.parse(rest);
  } catch {
    return { bad: `the model's card was not JSON: ${rest.slice(0, 120)}` };
  }
  if (!j || typeof j !== "object") return { bad: "the model's card was not an object" };
  const props = typeof j.props === "object" && j.props && !Array.isArray(j.props) ? (j.props as Record<string, unknown>) : {};
  const kind = typeof j.kind === "string" && Object.hasOwn(KINDS, j.kind) ? j.kind : "note";
  // the owner's bug: a model-made decision card had no real options, only a count and a bare bar
  if (kind === "decision") return { bad: "decisions come from show: asks, not from a card" };
  return { card: { id: AI(typeof j.id === "string" && j.id ? j.id : kind), ...card(kind, { ...props, proj: typeof j.proj === "string" && j.proj ? j.proj : "me" }) } };
}

/** Streams the model's text deltas from `omp -p --mode json`. */
async function* stream(prompt: string, timeoutMs = 90_000): AsyncGenerator<string> {
  const p = Bun.spawn(
    ["omp", "-p", "--mode", "json", "--no-tools", "--no-session", "--no-lsp", "--model", CHAT_MODEL, "--system-prompt", SYSTEM + CATALOG, prompt],
    { cwd: tmpdir(), stdout: "pipe", stderr: "pipe" }, // tmpdir: no repo context files get loaded into the prompt
  );
  const timer = setTimeout(() => p.kill(), timeoutMs);
  let buf = "", err = "";
  try {
    for await (const chunk of p.stdout.pipeThrough(new TextDecoderStream())) {
      buf += chunk;
      let nl: number;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const raw = buf.slice(0, nl);
        buf = buf.slice(nl + 1);
        let ev: { type?: string; assistantMessageEvent?: { type?: string; delta?: string }; message?: { role?: string; errorMessage?: string; stopReason?: string } };
        try { ev = JSON.parse(raw); } catch { continue; }
        const a = ev.assistantMessageEvent;
        if (ev.type === "message_update" && a?.type === "text_delta" && a.delta) yield a.delta;
        if (ev.type === "message_end" && ev.message?.role === "assistant" && ev.message.errorMessage) err = ev.message.errorMessage;
      }
    }
    const code = await p.exited;
    if (err) throw new Error(err);
    if (code !== 0) throw new Error(`omp exited ${code}: ${(await new Response(p.stderr).text()).trim().slice(-300)}`);
  } finally {
    clearTimeout(timer);
    p.kill();
  }
}

/** One line per board card for the prompt: id, kind, cluster and what it shows. */
export function boardList(board: Record<string, Component>): string {
  return Object.entries(board)
    .filter(([, c]) => c.type === "card" && c.props.removed !== true && typeof c.props.kind === "string")
    .map(([id, c]) => `${id} kind=${c.props.kind} cluster=${c.props.proj ?? "board"}: ${String(c.props.title ?? c.props.q ?? "").slice(0, 100)}`)
    .slice(0, 120)
    .join("\n");
}

/** The board edits a question makes, applied by the feeder as each one arrives. */
export type Edit = { say: string; done: boolean } | { show: Topic[] } | { focus: string[] } | { upsert: string; card: Component } | { drop: string };

/** Answers one free-text question by streaming board edits, then one final `say` with done set. */
export async function chat(o: { text: string; about?: unknown; fleet: Fleet; board: Record<string, Component>; apply: (e: Edit) => Promise<void> }): Promise<void> {
  const q = o.text.trim().slice(0, 300), said: string[] = [];
  const prompt = `Fleet summary:\n${summary(o.fleet)}\n\nBoard cards:\n${boardList(o.board)}\n\nCards the owner selected: ${o.about == null ? "none" : JSON.stringify(o.about).slice(0, 2000)}\n\nQuestion: ${q}`;
  let bad = "";
  const take = async (l: string) => {
    const part = parse(l);
    if (!part) return;
    if ("say" in part) (said.push(part.say), await o.apply({ say: part.say, done: false }));
    else if ("focus" in part) await o.apply({ focus: part.focus.filter((id) => o.board[id]) });
    else if ("card" in part) { const { id, ...c } = part.card; await o.apply({ upsert: id, card: c }); }
    else if ("drop" in part || "show" in part) await o.apply(part);
    else bad = part.bad;
  };
  try {
    let text = "";
    for await (const d of stream(prompt)) {
      text += d;
      let nl: number;
      while ((nl = text.indexOf("\n")) >= 0) {
        await take(text.slice(0, nl));
        text = text.slice(nl + 1);
      }
    }
    await take(text);
  } catch (e) {
    bad = `${CHAT_MODEL}: ${(e as Error).message}`;
  }
  await o.apply({ say: said.at(-1) ?? (bad ? `Chat failed: ${bad}` : "The model gave no answer."), done: true });
}
