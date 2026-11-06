import { expect, test } from "bun:test";
import { voicePrompt } from "./desk.ts";

// voicePrompt output is the exact text delivered to the voice-pass model.
const prose = voicePrompt("What is the build status?");
const exact = voicePrompt("Read README.md and quote it exactly.");

test("the prose voice prompt carries the STE sentence rules", () => {
  expect(prose).toContain("Cover every supplied fact; split long sentences into more short sentences instead of dropping facts.");
  expect(prose).toContain("Use simple tenses (present, past, simple future). No passive voice. Never write a sentence over 25 words");
});

test("the exact-quote voice prompt keeps its original rules and gets no rewrite rules", () => {
  expect(exact).toContain("preserving every requested character");
  expect(exact).toContain("Cover every supplied source line");
  expect(exact).not.toContain("split long sentences");
  expect(exact).not.toContain("No passive voice");
});
