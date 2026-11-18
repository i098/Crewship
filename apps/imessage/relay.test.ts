import { expect, test } from "bun:test";
import type { Secondmate } from "./desk.ts";
import { mayNotice, NOTICE_MAX, relayNotice } from "./relay.ts";

const mate = (id: string) => ({ id, home: "/srv/x", scope: "s" }) as Secondmate;
const same = (text: string) => text;

test("the notice names the mate in plain words, so the outbound filter keeps it", () => {
  expect(relayNotice(mate("web-mate"), ["fix the footer"], same)).toBe("Sent to web mate: fix the footer");
  expect(relayNotice(mate("docs"), ["fix the footer"], same)).toBe("Sent to docs mate: fix the footer");
  // a bare id in this shape is what cleanText strips; the readable name has no hyphen and survives
  expect(relayNotice(mate("opm-mate-2"), ["x"], same)).toBe("Sent to opm mate 2: x");
});

test("the notice takes the caller's verb", () => {
  expect(relayNotice(mate("web-mate"), ["hello"], same, "Your text is queued for")).toBe("Your text is queued for web mate: hello");
});

test("the summary is one line cut to a fixed length; several texts join with a slash", () => {
  const m = mate("web-mate");
  expect(relayNotice(m, ["a\n\nb", "c"], same)).toBe("Sent to web mate: a b / c");
  expect(relayNotice(m, ["x".repeat(500)], same)).toBe(`Sent to web mate: ${"x".repeat(NOTICE_MAX - 1)}…`);
});

test("the outbound filter still applies to the summary", () => {
  expect(relayNotice(mate("web-mate"), ["see /home/me/work/notes.txt now"], same)).toBe("Sent to web mate: see now");
});

test("a sensitive text holds the summary back", () => {
  const held = "Sent to web mate: (held back, it may be sensitive)";
  expect(relayNotice(mate("web-mate"), ["the password is hunter2"], same)).toBe(held);
  expect(relayNotice(mate("web-mate"), ["token abc123"], (t) => t.replace("abc123", "[REDACTED]"))).toBe(held);
});

test("a notice goes only to a direct chat, with a redactor, a vetted desk and no mute", () => {
  const ok = { safe: same, vetted: true, muted: false };
  expect(mayNotice("iMessage;-;+15550000000", ok)).toBe(true);
  expect(mayNotice("iMessage;+;chat0000", ok)).toBe(false);
  expect(mayNotice("iMessage;-;+15550000000", { ...ok, safe: undefined })).toBe(false);
  expect(mayNotice("iMessage;-;+15550000000", { ...ok, vetted: false })).toBe(false);
  expect(mayNotice("iMessage;-;+15550000000", { ...ok, muted: true })).toBe(false);
});
