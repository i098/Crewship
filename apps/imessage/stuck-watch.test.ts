import { expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, utimesSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { BUMP_MARK, collectSessions, pendingNotes, promptOf, rateLimit, type Session, StuckWatch } from "./stuck-watch.ts";

const MIN = 60_000;
const tmp = () => mkdtempSync(join(process.env.TMPDIR || "/tmp", "stuck-"));
const watch = (file?: string) => new StuckWatch({ stuckMs: 15 * MIN, graceMs: 5 * MIN, file });
const mainSession = (over: Partial<Session> = {}): Session => ({ id: "main", label: "Firstmate (main)", notes: 0, blocked: false, ...over })
const T0 = Date.UTC(2026, 10, 17, 6, 0);

test("a prompt that stays open is texted once with its text, never bumped, and a recovery is texted once", () => {
  const w = watch();
  const s = mainSession({ blocked: true, prompt: "Pick a model: 1. Opus 2. Sonnet" });
  expect(w.poll([s], T0)).toEqual([]);
  expect(w.poll([s], T0 + 14 * MIN)).toEqual([]);
  const [text] = w.poll([s], T0 + 15 * MIN);
  expect(text!.kind).toBe("owner");
  expect(text!.text).toContain("Firstmate (main) is stuck: it sits on a prompt since 11-17 06:00 UTC (15 min)");
  expect(text!.text).toContain("I did not nudge it");
  expect(text!.text).toContain("Prompt: Pick a model");
  text!.done(true);
  expect(w.poll([s], T0 + 30 * MIN)).toEqual([]);
  expect(w.poll([mainSession()], T0 + 31 * MIN)).toEqual([]);
  const [clear] = w.poll([mainSession()], T0 + 32 * MIN);
  expect(clear!.text).toContain("is moving again after 32 min");
  clear!.done(true);
  expect(w.poll([mainSession()], T0 + 40 * MIN)).toEqual([]);
});

test("no prompt is ever bumped, whatever it asks or even when it cannot be read", () => {
  for (const prompt of ["Spend a saved Claude rate-limit reset? 1. Yes 2. No", "Paste your API key:", "Delete 40 files? 1. Yes 2. No", undefined]) {
    const w = watch();
    const s = mainSession({ blocked: true, prompt, notes: 5, oldest: T0 - MIN });
    w.poll([s], T0);
    const out = w.poll([s], T0 + 15 * MIN);
    expect(out.map((a) => a.kind)).toEqual(["owner"]);
  }
});

test("a failed bump comes again each poll until the grace ends, then one text; a good bump is not repeated", () => {
  const stuckNotes = mainSession({ notes: 2, oldest: T0 });
  const w = watch();
  w.poll([stuckNotes], T0 + 15 * MIN)[0]!.done(false);
  const again = w.poll([stuckNotes], T0 + 17 * MIN);
  expect(again.map((a) => a.kind)).toEqual(["bump"]);
  again[0]!.done(false);
  expect(w.poll([stuckNotes], T0 + 19 * MIN).map((a) => a.kind)).toEqual(["bump"]);
  const retry = w.poll([stuckNotes], T0 + 20 * MIN);
  expect(retry.map((a) => a.kind)).toEqual(["owner"]);
  expect(retry[0]!.text).toContain("My nudge did not go through.");
  retry[0]!.done(false);
  expect(w.poll([stuckNotes], T0 + 21 * MIN)).toHaveLength(1);

  const w3 = watch();
  w3.poll([stuckNotes], T0 + 15 * MIN)[0]!.done(true);
  expect(w3.poll([stuckNotes], T0 + 17 * MIN)).toEqual([]);
  expect(w3.poll([stuckNotes], T0 + 20 * MIN)[0]!.text).toContain("I nudged it, and it is still stuck.");

  const w2 = watch();
  w2.poll([stuckNotes], T0 + 15 * MIN)[0]!.done(true);
  expect(w2.poll([mainSession()], T0 + 16 * MIN)).toEqual([]);
  expect(w2.poll([mainSession()], T0 + 17 * MIN)).toEqual([]);
  expect(w2.poll([mainSession({ notes: 1, oldest: T0 + 17 * MIN })], T0 + 18 * MIN)).toEqual([]);
});

test("unread notes count from the oldest one, and the bump is not counted as a note", () => {
  const dir = tmp();
  const ago = (name: string, min: number, body = "note") => {
    writeFileSync(`${dir}/${name}`, body);
    utimesSync(`${dir}/${name}`, (T0 - min * MIN) / 1000, (T0 - min * MIN) / 1000);
  };
  ago("a.note", 40);
  ago("b.note", 10);
  ago("c.note", 5, `${BUMP_MARK} You look stuck`);
  mkdirSync(`${dir}/handled`);
  ago("handled/old.note", 900);
  expect(pendingNotes(dir, ".note")).toEqual({ count: 2, oldest: T0 - 40 * MIN });

  const w = watch();
  const s = mainSession({ notes: 59, oldest: T0 - 40 * MIN });
  const [bump] = w.poll([s], T0);
  expect(bump!.text).toContain("59 notes wait since 11-17 05:20 UTC");
  bump!.done(true);
  const [text] = w.poll([s], T0 + 5 * MIN);
  expect(text!.text).toContain("it has not read its inbox since 11-17 05:20 UTC (45 min). 59 notes wait.");
});

test("an incident already texted is not texted again after a restart", () => {
  const file = `${tmp()}/stuck.json`;
  const s = mainSession({ notes: 3, oldest: T0 - 30 * MIN });
  const w = watch(file);
  w.poll([s], T0)[0]!.done(true);
  w.poll([s], T0 + 5 * MIN)[0]!.done(true);
  const again = watch(file);
  expect(again.poll([s], T0 + 6 * MIN)).toEqual([]);
  expect(again.poll([mainSession()], T0 + 7 * MIN)).toEqual([]);
  expect(again.poll([mainSession()], T0 + 8 * MIN)[0]!.text).toContain("is moving again");
});

const agents = (...list: object[]) => JSON.stringify({ result: { agents: list } });
const pane = (id: string, dir: string, status: string) => ({ pane_id: id, agent_status: status, foreground_cwd: dir, cwd: dir });

test("sessions join the inboxes with the panes of their homes; a spare pane that is not blocked clears the prompt", async () => {
  const home = tmp();
  mkdirSync(`${home}/state/inbox`, { recursive: true });
  mkdirSync(`${home}/state/web-mate.inbox`, { recursive: true });
  writeFileSync(`${home}/state/inbox/n1.note`, "hello");
  writeFileSync(`${home}/state/web-mate.inbox/001.msg`, "task");
  const reads: string[] = [];
  const sessions = await collectSessions({
    home, mates: [{ id: "web-mate", home: "/work/web", scope: "web" }],
    agentsJson: agents(pane("p1", home, "blocked"), pane("p2", "/work/web", "blocked"), pane("p3", "/work/web", "idle"), pane("p4", "/elsewhere", "blocked")),
    readPane: async (id) => (reads.push(id), "Trust this folder? ❯ 1. Yes"),
  });
  expect(reads).toEqual(["p1", "p2"]);
  expect(sessions).toMatchObject([
    { id: "main", notes: 1, blocked: true, prompt: "Trust this folder? ❯ 1. Yes" },
    { id: "web-mate", label: "web-mate (second mate)", notes: 1, blocked: false, prompt: undefined },
  ]);
  await expect(collectSessions({ home, mates: [], agentsJson: "{}", readPane: async () => "" })).rejects.toThrow("no agents array");
});

test("an idle pane with unread notes is read, so a rate-limit stop is detected", async () => {
  const home = tmp();
  mkdirSync(`${home}/state/inbox`, { recursive: true });
  writeFileSync(`${home}/state/inbox/n1.note`, "hello");
  const sessions = await collectSessions({
    home, mates: [], agentsJson: agents(pane("p1", home, "idle")),
    readPane: async () => "429 rate_limit_error",
  });
  expect(sessions).toMatchObject([{ id: "main", blocked: false, limited: true }]);
});

test("with a live limit, an idle pane without notes is read and found limited; only the pane end counts, and only for the limit's model", async () => {
  const home = tmp();
  const limit = { model: "claude-fable-5-2", at: 0, resetAt: 1, cleared: false };
  const run = (screen: string, l?: typeof limit) => collectSessions({ home, mates: [], agentsJson: agents(pane("p1", home, "idle")), limit: l, readPane: async () => screen });
  expect(await run("429 rate_limit_error", limit)).toMatchObject([{ id: "main", notes: 0, limited: true }]);
  expect(await run("429 rate_limit_error", undefined)).toMatchObject([{ id: "main", notes: 0, limited: false }]); // no limit: pane not read
  expect(await run("429 rate_limit_error\n" + "ok\n".repeat(5), limit)).toMatchObject([{ limited: false }]); // stale error scrolled up
  expect(await run("claude-sonnet-5-5 429 rate_limit_error", limit)).toMatchObject([{ limited: false }]); // another model
  expect(await run("claude-fable-5-2 429 rate_limit_error", limit)).toMatchObject([{ limited: true }]);
});

test("the prompt text keeps the last lines and the question at the end, without glyphs, and hides token-like strings", () => {
  const screen = `old chat\n\n\u{f0e8} status \n──────\nEnter token ghp_abcdefghijklmnop1234 or ${"a1".repeat(20)}\n❯ 1. Yes\n  2. No\n`;
  expect(promptOf(screen)).toBe("old chat | status | Enter token [hidden] or [hidden] | ❯ 1. Yes | 2. No");
  expect(promptOf("\n \n──\n")).toBeUndefined();
  const long = `${Array.from({ length: 11 }, () => "chat ".repeat(20)).join("\n")}\nSpend a saved reset? 1. Yes 2. No`;
  expect(promptOf(long)!.endsWith("Spend a saved reset? 1. Yes 2. No")).toBe(true);
  expect(promptOf(long)!.length).toBeLessThanOrEqual(500);
});

test("a rate limit gives one fleet text with the reset in PT, no text for each session, and one ring when it clears", () => {
  const w = watch();
  const limit = { model: "claude-fable-5-2", at: T0, resetAt: Date.UTC(2026, 10, 19, 1, 0), cleared: false };
  const stopped = ["main", "oss-mate-o1", "codex-mate-x1"].map((id) => mainSession({ id, blocked: true, limited: true, prompt: "Error: 429", notes: 2, oldest: T0 }));
  expect(w.poll(stopped, T0, limit)).toEqual([]);
  const [text, ...rest] = w.poll(stopped, T0 + 2 * MIN, { ...limit, at: T0 + MIN, resetAt: limit.resetAt - 9 * MIN }); // a later 429 gives a reset some minutes away
  expect(rest).toEqual([]);
  expect(text!.text).toBe("Rate limit on claude-fable-5-2. Stopped: main, oss, codex. It resets at 4:51 PM PT. I ring each one again when it clears.");
  text!.done(true);
  expect(w.poll(stopped, T0 + 20 * MIN, limit)).toEqual([]); // past stuckMs: still no text for each session and no bump
  const rings = w.poll(stopped, T0 + 21 * MIN, { ...limit, cleared: true });
  expect(rings.map((a) => a.kind)).toEqual(["bump", "bump", "bump", "owner"]);
  expect(rings[3]!.text).toContain("rate limit cleared");
  rings.forEach((a) => a.done(true));
  expect(w.poll(stopped, T0 + 22 * MIN, { ...limit, cleared: true })).toEqual([]); // rung once
  expect(w.poll(stopped, T0 + 23 * MIN, { ...limit, at: T0 + 22 * MIN, cleared: true })).toEqual([]); // a new 429 right after the ring: no ring loop
  expect(w.poll(stopped, T0 + 36 * MIN, { ...limit, cleared: true }).map((a) => a.text.slice(0, 26))).toEqual(Array(3).fill("Firstmate (main) is stuck:")); // the ring did not help
});

test("a blocked session on a real prompt with a stale 429 above is not rung; one whose pane ends in the 429 is", async () => {
  const home = tmp();
  mkdirSync(`${home}/state/inbox`, { recursive: true });
  const limit = { model: "claude-fable-5-2", at: T0, resetAt: T0 + 3 * MIN, cleared: true };
  const run = async (screen: string) => {
    const sessions = await collectSessions({ home, mates: [], agentsJson: agents(pane("p1", home, "blocked")), limit, readPane: async () => screen });
    return { sessions, actions: watch().poll(sessions, T0 + 10 * MIN, limit) };
  };
  const prompt = await run(`429 rate_limit_error\n${"work\n".repeat(5)}Trust this folder? ❯ 1. Yes`);
  expect(prompt.sessions).toMatchObject([{ blocked: true, limited: false }]);
  expect(prompt.actions.filter((a) => a.key.startsWith("limit-"))).toEqual([]);
  const stop = await run("work\nclaude-fable-5-2 429 rate_limit_error");
  expect(stop.sessions).toMatchObject([{ blocked: true, limited: true }]);
  expect(stop.actions.filter((a) => a.kind === "bump")).toHaveLength(1);
});

test("the limit is read from a stats database", () => {
  const { Database } = require("bun:sqlite");
  const file = join(tmp(), "stats.db");
  const db = new Database(file);
  db.run("pragma synchronous=off");
  db.run("create table messages (timestamp integer, model text, stop_reason text, error_message text)");
  const add = db.prepare("insert into messages values (?, ?, ?, ?)");
  add.run(T0, "claude-fable-5-2", "error", '429 {"type":"error"} retry-after-ms=10800000');
  add.run(T0 + MIN, "claude-sonnet-5-5", "stop", null);
  expect(rateLimit(file, T0 + 2 * MIN)).toEqual({ model: "claude-fable-5-2", at: T0, resetAt: T0 + 180 * MIN, cleared: false });
  add.run(T0 + 3 * MIN, "claude-fable-5-2", "aborted", null);
  expect(rateLimit(file, T0 + 4 * MIN)!.cleared).toBe(false);
  add.run(T0 + 5 * MIN, "claude-fable-5-2", "toolUse", null);
  expect(rateLimit(file, T0 + 6 * MIN)!.cleared).toBe(true);
  expect(rateLimit(file, T0 + 5 * MIN + 11 * MIN)).toBeUndefined(); // cleared early by a good call, long ago: no reads, no rings
  db.close();
});

test("rateLimit: a missing stats.db gives no limit", () => {
  expect(rateLimit("/nonexistent/stats.db", Date.now())).toBeUndefined();
});
