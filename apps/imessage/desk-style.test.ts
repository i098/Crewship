import { expect, test } from "bun:test";
import { deskPrompt } from "./desk.ts";

test("desk prompt requires ASD-STE100 style", () => {
  const prompt = deskPrompt("Owner", "model", "supervisor");
  expect(prompt).toContain("ASD-STE100");
  expect(prompt).toContain("active voice");
  expect(prompt).toContain("20 words maximum for an instruction, 25 for a description");
  expect(prompt).toContain("Keep the articles");
  expect(prompt).toContain("no Markdown");
  expect(prompt).not.toContain("Gen Z");
});
