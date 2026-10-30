import { expect, test } from "bun:test";
import { parseAt, windowPatch } from "../src/window";

test("open makes a floating card at its spot, on top by its time stamp", () => {
  const [op] = windowPatch("open", "w1", { title: "Logs", body: "tail", at: { x: 10, y: 20 }, now: 5000 });
  expect(op).toEqual({
    op: "add",
    path: "/components/w1",
    value: {
      type: "card",
      rect: { x: 10, y: 20, w: 380, h: 240 },
      props: { kind: "note", body: "tail", proj: "me", base: 80, title: "Logs", float: true, layer: 5, removed: false },
    },
  });
});

test("move writes only the rect fields given; lower goes under every raised window", () => {
  expect(windowPatch("move", "w1", { at: { x: 1, y: 2 } }).map((p) => p.path)).toEqual(["/components/w1/rect/x", "/components/w1/rect/y"]);
  expect(windowPatch("lower", "w1", { now: 9000 })).toEqual([{ op: "add", path: "/components/w1/props/layer", value: -9 }]);
  expect(() => windowPatch("move", "w1")).toThrow("--at");
});

test("an id that could reach another path, and a bad --at, are refused", () => {
  expect(() => windowPatch("close", "../header")).toThrow("window id");
  expect(() => parseAt("1,2,3")).toThrow("--at");
  expect(parseAt("1,2,30,40")).toEqual({ x: 1, y: 2, w: 30, h: 40 });
});
