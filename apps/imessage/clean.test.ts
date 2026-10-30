import { expect, test } from "bun:test";
import { cleanText, statusLine } from "./clean.ts";

test("status lines are refused", () => {
  for (const t of [
    "PR https://github.com/o/r/pull/1142",
    "https://github.com/o/r/pull/1142",
    "PR 2267 third failure is same-on-main: head 92340ee0 and main 15a481db fail",
    "Idle sweep: v-300k-hold re-tasked (no clean host needed)",
    "cf-text-leak: working on it",
    "x-mate-ab12 is done",
    "all good key=nm-1-ci",
    "Hello there.\n\nPR 12 built",
  ]) expect(statusLine(t), t).toBeString();
});

test("plain prose passes", () => {
  for (const t of [
    "Your fix is merged. See https://github.com/o/r/pull/1142 for details.",
    "The build finished and nothing needs you.",
    "Deploy is live; I checked the page and it loads.",
    "I changed the retry to 3 and the tests pass.",
  ]) expect(statusLine(t), t).toBeUndefined();
});

test("cleanText still strips prefixes", () => {
  expect(cleanText("done: it works")).toBe("it works");
});
