import { expect, test } from "bun:test";
import type { BoardSpec } from "@crewship/genui-spec";
import { applyPatch } from "../src/model";
import { cards, diff, type Sources } from "./feeder";

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
