import { expect, test } from "bun:test";
import { BUBBLE_MAX, bubbles } from "./desk.ts";

const squash = (parts: string[]) => parts.join("").replace(/\s+/g, "");

test("a list that fits stays one bubble", () => {
  const list = Array.from({ length: 10 }, (_, i) => `- item ${i}`).join("\n");
  expect(bubbles(`intro\n\n${list}`)).toEqual(["intro", list]);
});

test("a long multi-paragraph text with a long list splits without losing a character", () => {
  const sentence = "This sentence is a fairly ordinary one of moderate length. ";
  const para = sentence.repeat(40).trim();
  const list = Array.from({ length: 80 }, (_, i) => `- list item number ${i} with some words`).join("\n");
  const text = [para, list, para, "word ".repeat(500).trim(), "x".repeat(BUBBLE_MAX * 2 + 5)].join("\n\n");
  const parts = bubbles(text);
  expect(parts.length).toBeGreaterThan(5);
  for (const part of parts) expect(part.length).toBeLessThanOrEqual(BUBBLE_MAX);
  expect(squash(parts)).toBe(squash([text]));
  expect(parts.filter((p) => p.startsWith("- ")).every((p) => p.split("\n").every((l) => l.startsWith("- list item")))).toBe(true);
});
