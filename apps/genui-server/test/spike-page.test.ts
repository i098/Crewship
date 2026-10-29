import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";

// Runs the spike page's inline script against stub browser globals and feeds it socket frames.
function runPage() {
  const html = readFileSync(new URL("../spike/page.html", import.meta.url), "utf8");
  const start = html.indexOf("<script>") + "<script>".length;
  const code = html.slice(start, html.lastIndexOf("</script>"));
  const els: Record<string, { textContent: string; innerHTML: string }> = {
    status: { textContent: "", innerHTML: "" },
    root: { textContent: "", innerHTML: "" },
  };
  const sock: { onmessage?: (m: { data: string }) => void } = {};
  new Function("document", "WebSocket", "location", code)(
    { getElementById: (id: string) => els[id] },
    function () { return sock; },
    { protocol: "http:", host: "h" },
  );
  return { root: els.root, send: (e: unknown) => sock.onmessage!({ data: JSON.stringify(e) }) };
}
const snap = (elements: Record<string, unknown>) => ({ type: "STATE_SNAPSHOT", seq: 1, snapshot: { root: "r", elements: { r: { type: "Stack", props: {}, children: ["t"] }, ...elements }, style: {}, links: [] } });

test("prototype-polluting delta paths do not touch Object.prototype", () => {
  const { send } = runPage();
  send(snap({ t: { type: "Text", props: { text: "x" } } }));
  send({ type: "STATE_DELTA", seq: 2, delta: [{ op: "add", path: "/__proto__/polluted", value: 1 }, { op: "add", path: "/elements/constructor/prototype/polluted", value: 1 }] });
  expect(({} as Record<string, unknown>).polluted).toBeUndefined();
});

test("hostile props render escaped", () => {
  const { root, send } = runPage();
  const evil = `"><img src=x onerror=1>`;
  send(snap({ t: { type: "Badge", props: { text: evil, tone: evil } } }));
  expect(root.innerHTML).not.toContain("<img");
  expect(root.innerHTML).toContain("&lt;img");
  send({ type: "STATE_SNAPSHOT", seq: 2, snapshot: { root: "r", elements: { r: { type: "Stack", props: { dir: evil } } }, style: {}, links: [] } });
  expect(root.innerHTML).not.toContain("<img");
});
