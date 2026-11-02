import { expect, test } from "bun:test";
import type { BoardSpec, Component } from "@crewship/genui-spec";
import type { Fleet, Pr } from "../fleet/data";
import { applyPatch } from "../src/model";
import { cards, diff, type Sources, track } from "./feeder";

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
  // a prop the source stopped sending leaves the card: the old paging card kept its long list
  spec = applyPatch(spec, [{ op: "add", path: "/components/ok1/props/items", value: ["stale"] }]);
  spec = applyPatch(spec, diff(spec, cards(src([pr(1)])), owned));
  expect(spec.components.ok1.props.items).toBeNull();
  expect(spec.components.ok1.props.pick).toBe("approve");
});

test("a PR that starts failing joins the board and leads it for a while; what failed at first load stays quiet", () => {
  const pr = (n: number, bad?: number): Pr => ({
    url: `https://github.com/me/r/pull/${n}`, repo: "me/r", number: n, title: `PR ${n}`, draft: false, updated: "t",
    ...(bad === undefined ? {} : { checks: { ok: 1, bad, pending: 0 } }),
  });
  const fleet = (...prs: Pr[]): Fleet => ({ main: "/m", login: "me", mates: [], workers: [], asks: [], backlog: {}, prs, prsAt: 1, asksAt: 1 });
  const want: Record<string, Component> = {};
  track(fleet(pr(5, 0), pr(6, 3)), want);
  // a push resets PR 5's checks: no read, so no stage and no change
  track(fleet(pr(5), pr(6, 3)), want);
  track(fleet(pr(5, 2), pr(6, 3)), want);
  expect(want["pr-me-r-5"].props).toMatchObject({ flag: "failing", acts: [{ k: "claim" }] });
  expect(Number(want["pr-me-r-5"].props.boost)).toBeGreaterThan(Date.now());
  expect(want["pr-me-r-6"]).toBeUndefined();
  const green: Record<string, Component> = {};
  track(fleet(pr(5, 0), pr(6, 3)), green);
  expect(green["pr-me-r-5"]).toBeUndefined();
});
