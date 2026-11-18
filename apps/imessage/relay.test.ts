import { expect, test } from "bun:test";
import type { Secondmate } from "./desk.ts";
import { NOTICE_MAX, relayNotice } from "./relay.ts";

const mate = (id: string) => ({ id, home: "/srv/x", scope: "s" }) as Secondmate;
const same = (text: string) => text;

test("the notice names the mate in plain words, so the outbound filter keeps it", () => {
  expect(relayNotice(mate("web-mate"), ["fix the footer"], same)).toBe("Sent to web mate: fix the footer");
  expect(relayNotice(mate("docs"), ["fix the footer"], same)).toBe("Sent to docs mate: fix the footer");
  // a bare id in this shape is what cleanText strips; the readable name has no hyphen and survives
  expect(relayNotice(mate("opm-mate-2"), ["x"], same)).toBe("Sent to opm mate 2: x");
});

test("the notice names Firstmate and takes the caller's verb", () => {
  expect(relayNotice("firstmate", ["hello"], same)).toBe("Sent to Firstmate: hello");
  expect(relayNotice("firstmate", ["hello"], same, "Your text is queued for")).toBe("Your text is queued for Firstmate: hello");
});

test("the summary is one line cut to a fixed length; several texts join with a slash", () => {
  expect(relayNotice("firstmate", ["a\n\nb", "c"], same)).toBe("Sent to Firstmate: a b / c");
  const long = relayNotice("firstmate", ["x".repeat(500)], same);
  expect(long).toBe(`Sent to Firstmate: ${"x".repeat(NOTICE_MAX - 1)}…`);
});

test("the outbound filter still applies to the summary", () => {
  expect(relayNotice("firstmate", ["see /home/me/work/notes.txt now"], same)).toBe("Sent to Firstmate: see now");
});

test("a sensitive text, or no redactor, holds the summary back", () => {
  const held = "Sent to Firstmate: (held back, it may be sensitive)";
  expect(relayNotice("firstmate", ["the password is hunter2"], same)).toBe(held);
  expect(relayNotice("firstmate", ["token abc123"], (t) => t.replace("abc123", "[REDACTED]"))).toBe(held);
  expect(relayNotice("firstmate", ["hello"], undefined)).toBe(held);
});
