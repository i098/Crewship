import { describe, expect, test } from "bun:test";
import { countChecks, parseBacklog, type Fleet, type Pr } from "../fleet/data";
import { mergeBlock } from "../fleet/cards";

const fleet = { login: "i098" } as Fleet;
const pr = (o: Partial<Pr>): Pr => ({
  url: "u", repo: "i098/app", number: 1, title: "t", draft: false, updated: "",
  checks: { ok: 3, bad: 0, pending: 0 }, owner: { home: "/h", task: "t1" }, ...o,
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