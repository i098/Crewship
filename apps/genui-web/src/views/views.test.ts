import { describe, expect, test } from "bun:test";
import type { BoardSpec } from "@crewship/genui-spec";
import { renderCard } from "./index";

const board = (components: BoardSpec["components"]): BoardSpec => ({ components, links: [], tokens: {} });

describe("card views", () => {
  test("agent strings are escaped and unsafe media sources are dropped", () => {
    const spec = board({
      e: { type: "card", props: { kind: "embed", type: "site", title: '<img onerror="x">', src: "javascript:alert(1)" } },
      p: { type: "card", props: { kind: "timeline", rows: [{ name: "a", hsl: "red;background:url(x)", from: 0, len: 1 }] } },
    });
    const e = renderCard(spec, spec.components.e);
    expect(e).not.toContain("<img onerror");
    expect(e).not.toContain("javascript:");
    expect(renderCard(spec, spec.components.p)).not.toContain("url(x)");
  });

  test("an unknown or prototype kind falls back to the plain note view", () => {
    const spec = board({ c: { type: "card", props: { kind: "constructor" as never, title: "Hi", body: "there" } } });
    expect(renderCard(spec, spec.components.c)).toContain('<p class="body">there</p>');
  });

  test("the pipeline labels only the current stage until the card is wide", () => {
    const spec = board({ p: { type: "card", props: { kind: "pipeline", title: "#209", stages: ["Code", "Build", "Preview"], at: 2 } } });
    const narrow = renderCard(spec, spec.components.p, "narrow"), wide = renderCard(spec, spec.components.p, "wide");
    expect(narrow).toContain(">Preview</text>");
    expect(narrow).not.toContain(">Code</text>");
    expect(wide).toContain(">Code</text>");
  });
});
