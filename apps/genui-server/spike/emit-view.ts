// The agent tool call: one `emit_view` call sends one spec; the server streams it as patches.
const base = process.env.GENUI_URL ?? "http://127.0.0.1:8787";
const el = (type: string, props: object, children: string[] = []) => ({ type, props, children });

export const sample = {
  root: "page",
  elements: {
    page: el("Stack", { dir: "column" }, ["head", "grid"]),
    head: el("Card", { title: "Crew" }, ["headline", "badge"]),
    headline: el("Text", { text: "firstmate has 3 crewmates working on genui", tone: "normal" }),
    badge: el("Badge", { text: "on track", tone: "ok" }),
    grid: el("Stack", { dir: "row" }, ["m1", "m2", "m3"]),
    m1: el("Card", { title: "Open PRs" }, ["v1"]), v1: el("Metric", { label: "draft", value: 1 }),
    m2: el("Card", { title: "Phase" }, ["v2"]), v2: el("Metric", { label: "spike", value: "P0" }),
    m3: el("Card", { title: "Op log" }, ["v3"]), v3: el("Metric", { label: "ops per emit", value: 12 }),
  },
};

export async function emitView(spec: unknown, url = base) {
  const r = await fetch(`${url}/emit`, { method: "POST", headers: { "content-type": "application/json", "x-actor": "agent:spike" }, body: JSON.stringify(spec) });
  if (!r.ok) throw new Error(`emit_view ${r.status}: ${await r.text()}`);
  return r.json();
}

if (import.meta.main) console.log(await emitView(sample));
