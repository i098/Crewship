import { expect, test } from "bun:test";
import { appendFileSync, mkdtempSync, utimesSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { HerdrWatch, wakeNotice, watchStrandedWake } from "./herdr-watch.ts";

const agent = (pane: string, status: string, over: object = {}) => ({
  pane_id: pane, agent_status: status, foreground_cwd: "/work/pool/3/code-factory", terminal_title_stripped: "\u{f0213} CREW: Fix the login page", ...over,
});
const list = (...agents: object[]) => JSON.stringify({ id: "cli:agent:list", result: { agents } });
const watch = () => new HerdrWatch({ alertOn: ["done", "blocked", "idle"], debounceMs: 20_000, skip: ["firstmate"] });

test("a change that holds past the debounce sends one plain sentence", () => {
  const w = watch();
  expect(w.poll(list(agent("p1", "working")), 0)).toBeUndefined();
  expect(w.poll(list(agent("p1", "done")), 1000)).toBeUndefined();
  expect(w.poll(list(agent("p1", "done")), 22_000)).toBe('The agent on "Fix the login page" in code-factory is done.');
  expect(w.poll(list(agent("p1", "done")), 60_000)).toBeUndefined();
});

test("a status that flips back inside the debounce sends nothing", () => {
  const w = watch();
  w.poll(list(agent("p1", "working")), 0);
  w.poll(list(agent("p1", "blocked")), 1000);
  w.poll(list(agent("p1", "working")), 10_000);
  expect(w.poll(list(agent("p1", "working")), 40_000)).toBeUndefined();
});

test("several confirmed changes share one text; blocked reads as needing input; working is silent", () => {
  const w = watch();
  w.poll(list(agent("p1", "working"), agent("p2", "working", { foreground_cwd: "/w/site" }), agent("p3", "idle")), 0);
  const next = list(agent("p1", "blocked"), agent("p2", "done", { foreground_cwd: "/w/site" }), agent("p3", "working"));
  w.poll(next, 1000);
  expect(w.poll(next, 25_000)).toBe(
    '2 agent updates:\n- The agent on "Fix the login page" in code-factory needs your input.\n- The agent on "Fix the login page" in site is done.');
});

test("supervisor panes and token-marked panes are skipped; no pane ids leak", () => {
  const w = watch();
  const sup = (s: string) => list(agent("p9", s, { foreground_cwd: "/home/x/firstmate" }), agent("p8", s, { tokens: { who: "crewship" } }));
  w.poll(sup("working"), 0);
  w.poll(sup("done"), 1000);
  expect(w.poll(sup("done"), 30_000)).toBeUndefined();
});

test("a pane that disappears is forgotten; bad JSON throws", () => {
  const w = watch();
  w.poll(list(agent("p1", "working")), 0);
  w.poll(list(), 1000);
  expect(w.poll(list(agent("p1", "done")), 2000)).toBeUndefined();
  expect(() => w.poll("{}", 3000)).toThrow();
});

test("a pane that closes while its done status is still held sends that alert once", () => {
  const w = watch();
  w.poll(list(agent("p1", "working"), agent("p2", "working")), 0);
  w.poll(list(agent("p1", "done"), agent("p2", "working")), 1000);
  expect(w.poll(list(agent("p2", "working")), 5000)).toBe('The agent on "Fix the login page" in code-factory is done.');
  expect(w.poll(list(agent("p2", "working")), 40_000)).toBeUndefined();
});


test("a woken line becomes one honest sentence with the note count", () => {
  expect(wakeNotice(["1794008507\twoken\tnotes=1\tqueue=false"])).toContain("1 of your note was waiting");
  expect(wakeNotice(["1\twoken\tnotes=3\tqueue=true"])).toContain("3 of your notes were waiting");
  expect(wakeNotice(["1\twoken\tnotes=0\tqueue=true"])).toContain("a queued wake was waiting");
  expect(wakeNotice(["noise"])).toBeUndefined();
});

test("a new log line sends once; old lines and a second line inside the cooldown send nothing", async () => {
  const dir = mkdtempSync(join(process.env.TMPDIR || "/tmp", "wake-"));
  const log = join(dir, ".stranded-wake.log");
  writeFileSync(log, "1\twoken\tnotes=1\tqueue=false\n");
  const sent: string[] = [];
  const w = watchStrandedWake(log, (t) => { sent.push(t); return true; })!;
  appendFileSync(log, "2\twoken\tnotes=2\tqueue=false\n");
  await Bun.sleep(300);
  appendFileSync(log, "3\twoken\tnotes=2\tqueue=false\n");
  await Bun.sleep(300);
  w.close();
  expect(sent).toHaveLength(1);
  expect(sent[0]).toContain("2 of your notes");
});

test("a rejected notice is retried on the next change event and sent once", async () => {
  const dir = mkdtempSync(join(process.env.TMPDIR || "/tmp", "wake-"));
  const log = join(dir, ".stranded-wake.log");
  writeFileSync(log, "");
  const sent: string[] = [];
  let accept = false;
  const w = watchStrandedWake(log, (t) => { sent.push(t); return accept; })!;
  appendFileSync(log, "1\twoken\tnotes=1\tqueue=false\n");
  await Bun.sleep(300);
  accept = true;
  const t = new Date();
  utimesSync(log, t, t);
  await Bun.sleep(300);
  utimesSync(log, t, new Date(t.getTime() + 1000));
  await Bun.sleep(300);
  w.close();
  expect(sent).toHaveLength(2);
});
