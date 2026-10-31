// Client-observed DO wake: WebSocket connect -> first STATE_SNAPSHOT, plus the DO instance `generation`
// (a new generation means the DO was evicted and rebuilt). Usage: bun measure.ts [idleSeconds]
const base = process.env.GENUI_URL ?? "http://127.0.0.1:8787";
async function connect() {
  const t = performance.now();
  const ws = new WebSocket(base.replace("http", "ws") + "/ws");
  const { promise, resolve, reject } = Promise.withResolvers<void>();
  ws.onmessage = (m) => JSON.parse(String(m.data)).type === "STATE_SNAPSHOT" && resolve();
  ws.onerror = () => reject(new Error("websocket failed"));
  await promise;
  const ms = performance.now() - t; ws.close();
  const stats: { generation: number; seq: number } = await (await fetch(base + "/stats")).json();
  return { connectToSnapshotMs: +ms.toFixed(1), generation: stats.generation, seq: stats.seq };
}
const idle = Number(process.argv[2] ?? 0);
console.log("first ", await connect());
for (let i = 0; i < 5; i++) console.log("warm  ", await connect());
if (idle) { console.log(`idle ${idle}s`); await Bun.sleep(idle * 1000); console.log("after ", await connect()); }
