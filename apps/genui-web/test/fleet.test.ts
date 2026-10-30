import { describe, expect, test } from "bun:test";
import { askOpts, askRef, contextOf, fleetCards, mergeBlock, topicRows } from "../fleet/cards";
import { countChecks, type Fleet, isLive, type Pr, parseBacklog, raisedAt } from "../fleet/data";

const fleet = { login: "i098" } as Fleet;
const pr = (o: Partial<Pr>): Pr => ({
  url: "u", repo: "i098/app", number: 1, title: "t", draft: false, updated: "",
  checks: { ok: 3, bad: 0, pending: 0 }, owner: { home: "/h", task: "t1" }, ...o,
});

test("an answer card lists the real PRs it showed, his own first, and says when the list is still loading", () => {
  const f = { ...fleet, prsAt: 1, prs: [pr({ repo: "x/y", number: 9 }), pr({ number: 2, checks: { ok: 0, bad: 1, pending: 0 } })] } as Fleet;
  expect(topicRows(f, ["prs"])).toEqual([{ h: "Open PRs (2)", rows: ["i098/app#2 t · 1 failing", "x/y#9 t · green"] }]);
  expect(topicRows({ ...f, prsAt: 0 }, ["prs"])[0].rows[0]).toMatch(/Still loading/);
});

describe("merge guard", () => {
  test("only an owned, non-draft, all-green PR with a live task may merge", () => {
    expect(mergeBlock(fleet, pr({}))).toBeUndefined();
    expect(mergeBlock(fleet, pr({ repo: "i0981/app" }))).toContain("not your repo");
    expect(mergeBlock(fleet, pr({ repo: "Org/app" }))).toContain("not your repo");
    expect(mergeBlock({ login: "" } as Fleet, pr({}))).toContain("not your repo");
    expect(mergeBlock(fleet, pr({ draft: true }))).toBe("draft");
    expect(mergeBlock(fleet, pr({ checks: undefined }))).toBe("checks not read yet");
    expect(mergeBlock(fleet, pr({ checks: { ok: 3, bad: 0, pending: 1 } }))).toBe("checks still running");
    expect(mergeBlock(fleet, pr({ checks: { ok: 3, bad: 1, pending: 0 } }))).toBe("checks failing");
    expect(mergeBlock(fleet, pr({ checks: { ok: 0, bad: 0, pending: 0 } }))).toBe("no checks");
    expect(mergeBlock(fleet, pr({ owner: undefined }))).toBe("no live task owns it");
  });

  test("a re-run check counts only its latest run", () => {
    const runs = [
      { name: "ci", id: 1, status: "completed", conclusion: "failure" },
      { name: "ci", id: 2, status: "completed", conclusion: "success" },
      { name: "lint", id: 3, status: "in_progress", conclusion: null },
    ];
    expect(countChecks(runs, [{ state: "success" }])).toEqual({ ok: 2, bad: 0, pending: 1 });
  });
});

test("backlog rows keep quoted commas and drop the truncation note", () => {
  const out = `count: 2
tasks[2]{id,state,kind,repo,title,held}:
  fleet-cutover-c7,queued,ship,firstmate,"phases 2-4: drain laptop fleet, snapshot \\n... (truncated, 222 chars total)",yes
  fm-merge-local-branch-naming-b6,in_flight,ship,firstmate,"fm-merge-local.sh assumes the branch is always fm/<task-id>",no
help[1]:
  Run \`tasks-axi list --state queued\``;
  expect(parseBacklog(out)).toEqual([
    { id: "fleet-cutover-c7", state: "queued", kind: "ship", title: "phases 2-4: drain laptop fleet, snapshot ", held: true },
    { id: "fm-merge-local-branch-naming-b6", state: "in_flight", kind: "ship", title: "fm-merge-local.sh assumes the branch is always fm/<task-id>", held: false },
  ]);
});

test("an ask's time is the at= stamp of the last line carrying its key", () => {
  const text = [
    "needs-decision [at=100] [key=a]: first",
    "working [at=150]: other",
    "needs-decision [at=200] [key=a]: asked again",
    "blocked [at=300] [key=b]: stuck",
  ].join("\n");
  expect(raisedAt(text, "a")).toBe(200);
  expect(raisedAt(text, "b")).toBe(300);
  expect(raisedAt(text, "missing")).toBe(0);
});

test("only an ask raised in the last two days is live", () => {
  const now = 1_000_000;
  expect(isLive({ at: now - 48 * 3600 }, now)).toBe(true);
  expect(isLive({ at: now - 48 * 3600 - 1 }, now)).toBe(false);
  expect(isLive({ at: 0 }, now)).toBe(false);
});

test("an ask names its PR (linked, or by number among its task's PRs), else its task and project", () => {
  const f = {
    ...fleet,
    prs: [pr({ repo: "i098/app", number: 7, title: "Fix login", owner: { home: "/h", task: "w1" } })],
    mates: [],
    workers: [{ id: "w1", home: "/h", meta: { project: "/p/projects/app" }, lines: [], busy: "" }],
  } as unknown as Fleet;
  const ask = (note: string) => ({ home: "/h", task: "w1", key: "k", verb: "needs-decision", note, at: 0 });
  expect(askRef(f, ask("see https://github.com/i098/app/pull/7 now"))).toBe("PR i098/app#7 · Fix login");
  expect(askRef(f, ask("PR7 is green"))).toBe("PR i098/app#7 · Fix login");
  expect(askRef(f, ask("https://github.com/x/y/pull/3"))).toBe("PR x/y#3");
  expect(askRef(f, ask("pick a font"))).toBe("w1 · app");
  expect(askRef(f, ask("pick a font"), "TreeHacks form")).toBe("TreeHacks form");
});

test("an ask shows the options it names, the one it recommends, or none when it is open", () => {
  const n = askOpts("Push denied. Options: (1) fork to i098 and open the PRs (recommended); (2) keep the commits local; (3) use another account.");
  expect(n.map((o) => [o.k, o.b, o.rec])).toEqual([
    ["o1", "Fork to i098 and open…", true],
    ["o2", "Keep the commits local", false],
    ["o3", "Use another account", false],
  ]);
  expect(askOpts("Decide: A) authorize one more attempt; B) stop the debugger route. Recommend A.").map((o) => o.b)).toEqual([
    "Authorize one more attempt",
    "Stop the debugger route",
  ]);
  expect(askOpts("Options: he signs in once himself (recommended), another Apple ID, or skip iOS. No build queued.").map((o) => [o.b, o.rec])).toEqual([
    ["He signs in once himself", true],
    ["Another Apple ID", false],
    ["Skip iOS", false],
  ]);
  expect(askOpts("PR 874 is green, see https://x.y/z. Recommend OK.")).toMatchObject([{ b: "OK", rec: true }]);
  expect(askOpts("Who are the others? Send names and I add them.")).toEqual([]);
});

test("nothing is drawn until asked; asked-for asks page so every one is reachable and counted", () => {
  const asks = Array.from({ length: 5 }, (_, i) => ({ home: "/h", task: "t1", key: `k${i}`, verb: "needs-decision", note: `Question ${i}?`, at: i }));
  const f = { ...fleet, main: "/h", mates: [], workers: [], prs: [], asks } as unknown as Fleet;
  expect(fleetCards(f, new Map())).toEqual({});
  const seen = new Set<string>();
  const page = new Map<string, number>();
  for (let p = 0; p < 3; p++) {
    page.set("fm", p);
    const out = fleetCards(f, new Map(), { cards: new Set(), page }, new Set(["asks"]));
    const on = Object.keys(out).filter((id) => id.startsWith("ask-"));
    on.forEach((id) => seen.add(id));
    // the cards on this page plus the paging card's count always make the full list
    expect(on.length + Number(out["more-fm"].props.unseen)).toBe(5);
    for (const id of on) expect(out[id].props).toMatchObject({ kind: "decision", free: true, opts: [] });
  }
  expect(seen.size).toBe(5);
});

test("asking about a failing PR card shows its checks, though only a green PR's card carries prUrl", () => {
  const f = { ...fleet, mates: [], workers: [], asks: [], prs: [pr({ url: "https://x/1", title: "Fix login", checks: { ok: 2, bad: 1, pending: 0 } })] };
  expect(contextOf(f, { kind: "note", url: "https://x/1", title: "i098/app#1: 1 failing" })).toEqual([
    "i098/app#1: Fix login",
    "Checks: 2 passed, 1 failed, 0 running",
  ]);
  expect(contextOf(f, { kind: "note", title: "No PR here" })).toEqual(["No PR here"]);
});
