import { expect, test } from "bun:test";
import { parse } from "./chat";

test("parse turns each model line into one board edit", () => {
  expect(parse("say: two are blocked")).toEqual({ say: "two are blocked" });
  expect(parse("Focus: crew-oss-mate-o1, ask-x ,")).toEqual({ focus: ["crew-oss-mate-o1", "ask-x"] });
  expect(parse("drop: blocked list")).toEqual({ drop: "ai-blocked-list" });
  expect(parse("some prose")).toBeUndefined();
  // the id always gets the ai- prefix, so the model can never overwrite a fleet card
  expect(parse('card: {"id":"crew-fm","kind":"crew","proj":"oss-mate-o1","props":{"title":"Blocked"}}')).toEqual({
    card: { id: "ai-crew-fm", type: "card", props: { title: "Blocked", kind: "crew", proj: "oss-mate-o1", asked: true, removed: false } },
  });
  expect(parse('card: {"kind":"chart","props":{"title":"x"}}')).toMatchObject({ card: { id: "ai-note", props: { kind: "note", title: "x", proj: "me" } } });
  expect(parse("card: null")).toHaveProperty("bad");
  expect(parse("card: {oops")).toHaveProperty("bad");
});
