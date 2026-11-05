import { expect, test } from "bun:test";
import { BUBBLE_MAX, bubbles, voiceAnswer } from "./desk.ts";

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

test("an emoji run splits into parts within the limit and never inside a surrogate pair", () => {
  const parts = bubbles("😀".repeat(BUBBLE_MAX));
  expect(parts.length).toBeGreaterThan(1);
  for (const part of parts) {
    expect(part.length).toBeLessThanOrEqual(BUBBLE_MAX);
    expect(Array.from(part).every((c) => c.codePointAt(0)! < 0xd800 || c.codePointAt(0)! > 0xdfff)).toBe(true);
  }
  expect(parts.join("")).toBe("😀".repeat(BUBBLE_MAX));
});

test("a long exact answer splits across bubbles without losing a character", () => {
  const line = "- exact source line with some words in it";
  const answer = `${Array.from({ length: 15 }, () => line).join("\n")}\n\n${Array.from({ length: 15 }, () => line).join("\n")}`;
  expect(answer.length).toBeGreaterThan(BUBBLE_MAX);
  const parts = voiceAnswer({ answer, identity: false }, "Give me the exact text.", true, answer);
  expect(parts!.length).toBeGreaterThan(1);
  for (const part of parts!) expect(part.length).toBeLessThanOrEqual(BUBBLE_MAX);
  expect(squash(parts!)).toBe(squash([answer]));
});
