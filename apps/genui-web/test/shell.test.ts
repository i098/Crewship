import { expect, test } from "bun:test";
import { lineHtml } from "../src/shell";

test("header line: starred runs turn amber, across words, and text is escaped", () => {
  const words = [...lineHtml("*Needs you:* Store <b> *+2 more* need you.").matchAll(/<span[^>]*>(.*?)<\/span>/g)].map((m) => m[1]);
  expect(words).toEqual(["<em>Needs</em>", "<em>you:</em>", "Store", "&#60;b&#62;", "<em>+2</em>", "<em>more</em>", "need", "you."]);
});
