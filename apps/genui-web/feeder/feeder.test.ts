import { expect, test } from "bun:test";
import type { BoardSpec } from "@crewship/genui-spec";
import { applyPatch } from "../src/model";
import { cards, decision, diff, type Sources } from "./feeder";

const src = (prs: Sources["prs"]): Sources => ({ prs, merged: null, crew: [], usage: null, host: {}, gaps: [] });
const pr = (n: number, failed: string[] = []) => ({ n, title: `PR ${n}`, url: `https://example.test/${n}`, draft: false, checks: { total: 3, done: 3, failed } });

test("a failing PR shows its failed checks and no made-up progress", () => {
  const c = cards(src([pr(7, ["lint"])])).pr7.props;
  expect(c).toMatchObject({ kind: "note", flag: "failing", items: ["lint"] });
  expect(c.att).toBeUndefined();
});

test("the feed keeps the owner's pick and removes a card whose PR closed", () => {
  const owned = new Set<string>();
  let spec: BoardSpec = { components: {}, links: [], tokens: {} };
  const want = cards(src([pr(1), pr(2)]));
  for (const id of Object.keys(want)) owned.add(id);
  spec = applyPatch(spec, diff(spec, want, owned));
  spec = applyPatch(spec, [{ op: "add", path: "/components/ok1/props/pick", value: "approve" }]);
  spec = applyPatch(spec, diff(spec, cards(src([pr(1)])), owned));
  expect(spec.components.ok1.props.pick).toBe("approve");
  expect(spec.components.pr2.props.removed).toBe(true);
});

test("a pick on any decision card records which card and question it answered", () => {
  expect(decision("ok7", { url: "https://x/7" }, "approve")).toEqual({
    body: { decision: "approve", pr: 7, url: "https://x/7", draft: "gh pr merge 7" }, note: "Approved #7", draft: "gh pr merge 7",
  });
  expect(decision("ok7", { url: "https://x/7" }, "decline").body).toEqual({ decision: "decline", pr: 7, url: "https://x/7" });
  expect(decision("okdesign", { q: "Approve the design?" }, "approve")).toEqual({
    body: { decision: "approve", card: "okdesign", q: "Approve the design?" }, note: "Approved Approve the design?",
  });
});
