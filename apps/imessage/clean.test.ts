import { expect, test } from "bun:test";
import { cleanText, statusLine } from "./clean.ts";

test("status lines are refused", () => {
  for (const t of [
    "PR https://github.com/o/r/pull/1142",
    "https://github.com/o/r/pull/1142",
    "PR 2267 third failure is same-on-main: head 92340ee0 and main 15a481db fail",
    "cf-text-leak: working on it",
    "x-mate-ab12 is done",
    "all good key=nm-1-ci",
  ]) expect(statusLine(t), t).toBeString();
});

test("plain prose passes", () => {
  for (const t of [
    "Your fix is merged. See https://github.com/o/r/pull/1142 for details.",
    "Hello there.\n\nhttps://github.com/o/r/pull/12",
    "PR 2267 is merged, thanks",
    "Status: all good",
    "The build finished and nothing needs you.",
    "Deploy is live; I checked the page and it loads.",
    "I changed the retry to 3 and the tests pass.",
    "The Codex effort picker is merged because it passed the pixel check, and you can compare the original app with ours on this slider page: https://pub-c548cd7bc64c41ae8ce0d860578f3b6f.r2.dev/cgx-effort-picker/1db80615e84d17724bd32ddb/index.html",
  ]) expect(statusLine(t), t).toBeUndefined();
});

test("cleanText still strips prefixes", () => {
  expect(cleanText("done: it works")).toBe("it works");
});

test("cleanText strips a child status prefix", () => {
  expect(cleanText("child abc-1 working: it runs")).toBe("it runs");
});

test("cleanText strips pr, mode, yolo, head and task tokens", () => {
  expect(cleanText("ok pr=12 mode=dark yolo=1 head=ab task=x end")).toBe("ok end");
});
