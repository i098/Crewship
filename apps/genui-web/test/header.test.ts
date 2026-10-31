import { expect, test } from "bun:test";
import { buildHeader } from "../src/header";

class Fake {
  textContent = "";
  className = "";
  dataset: Record<string, string> = {};
  attrs: Record<string, string> = {};
  kids: (Fake | string)[] = [];
  constructor(readonly tag: string) {}
  setAttribute(k: string, v: string) { this.attrs[k] = v; }
  append(...n: (Fake | string)[]) { this.kids.push(...n); }
}
const doc = { createElement: (t: string) => new Fake(t) } as unknown as Document;
const evil = `"><img src=x onerror=alert(1)>`;

test("header passes hostile title and notice as text, never as markup", () => {
  const [, h1, st] = buildHeader(doc, { title: evil, wins: "user", live: false, seq: 1, busy: false, notice: evil }) as Fake[];
  expect(h1.textContent).toBe(evil);
  expect(st.kids).toEqual(["reconnecting", ` · ${evil}`]);
});

test("header shows seq and the pressed side", () => {
  const [, , st, seg] = buildHeader(doc, { title: "t", wins: "user", live: true, seq: 7, busy: true }) as Fake[];
  expect((st.kids[1] as Fake).textContent).toBe("7");
  expect((seg.kids as Fake[]).map((b) => [b.dataset.wins, b.attrs["aria-pressed"]])).toEqual([["agent", "false"], ["user", "true"]]);
});
