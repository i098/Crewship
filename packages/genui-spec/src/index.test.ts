import { expect, test } from "bun:test";
import { applyPatch, event, spec, styleTokens, type Spec } from "./index";

const doc = { root: "a", elements: { a: { type: "Text", props: { text: "hi" } } } };
const textOf = (s: Spec) => { const a = s.elements.a; return a?.type === "Text" ? a.props.text : undefined; };

test("spec fills defaults and rejects unknown component", () => {
  expect(spec.parse(doc).elements.a).toMatchObject({ children: [] });
  expect(() => spec.parse({ ...doc, elements: { a: { type: "Nope", props: {} } } })).toThrow();
});
test("style tokens accept HSL vars only", () => {
  expect(styleTokens.parse({ "--gu-bg": "hsl(228 22% 7%)" })).toBeTruthy();
  expect(() => styleTokens.parse({ "--gu-bg": "#fff" })).toThrow();
  expect(() => styleTokens.parse({ "--evil": "hsl(1 1% 1%)" })).toThrow();
});
test("STATE_DELTA parses and applyPatch round-trips with its inverse", () => {
  const s = spec.parse(doc);
  const ev = event.parse({ type: "STATE_DELTA", seq: 1, delta: [{ op: "replace", path: "/elements/a/props/text", value: "yo" }] });
  if (ev.type !== "STATE_DELTA") throw new Error("wrong event");
  const next = applyPatch(s, ev.delta);
  expect(textOf(next)).toBe("yo");
  expect(textOf(applyPatch(next, [{ op: "replace", path: "/elements/a/props/text", value: "hi" }]))).toBe("hi");
  expect(textOf(s)).toBe("hi"); // input not mutated
});
test("applyPatch add/replace/remove on arrays; bad path throws", () => {
  const s = { l: [1, 2] };
  expect(applyPatch(s, [{ op: "add", path: "/l/-", value: 3 }, { op: "remove", path: "/l/0" }])).toEqual({ l: [2, 3] });
  expect(applyPatch(s, [{ op: "replace", path: "/l/1", value: 9 }])).toEqual({ l: [1, 9] });
  expect(() => applyPatch(s, [{ op: "add", path: "/x/y", value: 1 }])).toThrow();
});

test("applyPatch does not walk inherited keys into Object.prototype", async () => {
  const { applyPatch } = await import("./index");
  expect(() => applyPatch({ components: {} }, [{ op: "add", path: "/components/constructor/prototype/polluted", value: 1 }])).toThrow();
  expect(({} as Record<string, unknown>).polluted).toBeUndefined();
});
