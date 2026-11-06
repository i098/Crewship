import { expect, test } from "bun:test";
import { STE_STYLE } from "./ste.ts";
import { voicePrompt } from "./desk.ts";

// voicePrompt output is the exact text delivered to the voice-pass model.
const prose = voicePrompt("What is the build status?");
const exact = voicePrompt("Read README.md and quote it exactly.");

test("the prose voice prompt carries the STE sentence rules", () => {
  expect(prose).toContain("Coverage overrides brevity. Cover every supplied fact; split long sentences into more short sentences instead of dropping facts.");
  expect(prose).toContain(STE_STYLE);
});

test("the exact-quote voice prompt keeps its original rules and gets no rewrite rules", () => {
  expect(exact).toContain("preserving every requested character");
  expect(exact).toContain("Cover every supplied source line; do not omit facts to shorten the answer.");
  expect(exact).not.toContain("split long sentences");
  expect(exact).not.toContain(STE_STYLE);
});
