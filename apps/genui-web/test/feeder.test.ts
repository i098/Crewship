import { expect, test } from "bun:test";
import type { Component } from "@crewship/genui-spec";
import { applyPlan } from "../feeder/feeder";

const card = (proj: string, props: Record<string, unknown> = {}): Component => ({ type: "card", props: { kind: "ask", proj, ...props } });

test("a question about a card in the open deck keeps the whole pile on the board; other cards step aside", () => {
  const want = { d0: card("all"), d1: card("all", { under: "d0" }), d2: card("all", { under: "d0" }), x: card("fm") };
  applyPlan(want, { p: { keep: ["d1"], size: { d1: "l" }, under: {}, edge: [] }, cause: "c", back: [], own: new Set() });
  for (const id of ["d0", "d1", "d2"]) expect(want[id as "d0"].props.aside).toBeUndefined();
  expect(want.d2.props.under).toBe("d0");
  expect(want.x.props.aside).toBe(true);
});
