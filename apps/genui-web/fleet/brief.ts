// An ask's status line is written for the fleet, not for the owner. A brief is the model's rewrite of one ask
// into just enough to decide: what it is, why it matters now, and the options as short full labels.
// Briefs are cached on disk by ask and time, so each ask costs one model call once.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname } from "node:path";
import type { Ask } from "./data";

// the model runner comes in as a parameter: chat imports cards, which imports this file
type Run = (prompt: string, timeoutMs: number, system: string) => AsyncIterable<string>;

export type Brief = { what: string; why: string; opts: { b: string; rec: boolean }[] };

const FILE = process.env.GENUI_BRIEFS ?? `${homedir()}/.cache/crewship-genui/briefs.json`;

/** A brief from untrusted model or file JSON, or undefined when any field is off. */
export function asBrief(j: unknown): Brief | undefined {
  if (!j || typeof j !== "object") return;
  const { what, why, opts } = j as Record<string, unknown>;
  if (typeof what !== "string" || !what || typeof why !== "string" || !Array.isArray(opts)) return;
  if (!opts.every((o) => o && typeof o.b === "string" && o.b && typeof o.rec === "boolean")) return;
  return { what, why, opts: opts.map((o) => ({ b: o.b, rec: o.rec })) };
}

export const briefKey = (a: Ask) => `${a.home}|${a.task}|${a.key}|${a.at}`;

const cache = new Map<string, Brief>();
try {
  for (const [k, v] of Object.entries(JSON.parse(readFileSync(FILE, "utf8")))) {
    const b = asBrief(v);
    if (b) cache.set(k, b);
  }
} catch {}

export const briefOf = (a: Ask): Brief | undefined => cache.get(briefKey(a));

const SYSTEM = `You brief a busy owner on decisions his agents wait on. For each input line "<id> | <agent>: <the agent's raw note>", write one JSON line:
{"id": "<id>", "what": "...", "why": "...", "opts": [{"b": "...", "rec": true|false}]}
what: plain English, at most 9 words: what it is and what he picks. No ids, hashes, file paths, URLs or jargon.
why: plain English, at most 14 words: why it matters now (what is blocked or at risk). Empty string if the note does not say.
opts: only the choices the note itself names, in its order, each a full label of at most 5 words; rec true for the one the note recommends. [] when the note names no choices.
Use only facts in the note. Write JSON lines only, nothing else.`;

/** Briefs the asks not yet briefed, newest first, in batches; `landed` runs after each batch that added any. */
export async function briefAsks(asks: Ask[], landed: () => void, run: Run) {
  const todo = asks.filter((a) => !cache.has(briefKey(a)));
  for (let i = 0; i < todo.length; i += 12) {
    const batch = new Map(todo.slice(i, i + 12).map((a, j) => [`a${j}`, a]));
    const prompt = [...batch].map(([id, a]) => `${id} | ${a.task}: ${a.note.replace(/\s+/g, " ").slice(0, 1200)}`).join("\n");
    let text = "";
    try {
      for await (const d of run(prompt, 120_000, SYSTEM)) text += d;
    } catch (e) {
      console.error("brief:", (e as Error).message);
    }
    let added = 0;
    for (const l of text.split("\n")) {
      let j: { id?: unknown };
      try {
        j = JSON.parse(l.trim());
      } catch {
        continue;
      }
      const a = typeof j?.id === "string" ? batch.get(j.id) : undefined;
      const b = asBrief(j);
      if (a && b) cache.set(briefKey(a), b), added++;
    }
    if (!added) continue;
    mkdirSync(dirname(FILE), { recursive: true });
    writeFileSync(FILE, JSON.stringify(Object.fromEntries(cache)));
    landed();
  }
}
